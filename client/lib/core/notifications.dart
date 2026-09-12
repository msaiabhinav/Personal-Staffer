import 'dart:async';
import 'dart:io';

import 'package:app_links/app_links.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:go_router/go_router.dart';

import 'api.dart';
import 'models.dart';
import 'repository.dart';

@pragma('vm:entry-point')
Future<void> stafferBackgroundMessage(RemoteMessage message) async {
  // Provider delivery is only a hint. Never insert inbox rows or change an
  // application from an untrusted push payload; fetch authorized API on open.
  if (Firebase.apps.isEmpty) await Firebase.initializeApp();
}

class NativeNotifications {
  NativeNotifications(this.repository, this.router);
  final StafferRepository repository;
  final GoRouter router;
  final local = FlutterLocalNotificationsPlugin();
  final links = AppLinks();
  final List<StreamSubscription<dynamic>> subscriptions = [];
  Timer? poll;
  bool showing = false;
  String get state => repository.notificationState;
  set state(String value) => repository.updateNotificationState(value);
  final seen = <String>{};
  bool baseline = false;
  void navigate(String? raw) {
    final route = internalDestination(raw);
    if (route == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      router.go(route);
      if (Platform.isWindows) {
        const MethodChannel('personalstaffer/desktop').invokeMethod('show');
      }
    });
  }

  void pushOpen(RemoteMessage message) {
    final id = message.data['notification_id'];
    if (id is String) navigate('personalstaffer://notifications/$id');
  }

  Future<void> initialize() async {
    subscriptions.add(
      links.uriLinkStream.listen((uri) async {
        if (uri.scheme == 'personalstaffer' && uri.host == 'auth') {
          // Redemption still requires the device-local verifier and bound flow;
          // callback payload cannot choose or replace either value.
          if (uri.queryParameters['flow_id'] == repository.session.flowId) {
            try {
              if (await repository.session.finishLogin()) {
                await repository.start();
              }
            } on ApiError {
              /* Login page presents failure or expiry. */
            }
          }
        } else {
          navigate(uri.toString());
        }
      }),
    );
    final first = await links.getInitialLink();
    if (first != null &&
        first.scheme == 'personalstaffer' &&
        first.host == 'auth' &&
        first.queryParameters['flow_id'] == repository.session.flowId) {
      try {
        await repository.session.finishLogin();
      } on ApiError {
        // Expired login intents return to the normal Google sign-in screen.
      }
    } else if (first != null) {
      navigate(first.toString());
    }
    try {
      await local.initialize(
        settings: const InitializationSettings(
          android: AndroidInitializationSettings('@mipmap/ic_launcher'),
          windows: WindowsInitializationSettings(
            appName: 'Personal Staffer',
            appUserModelId: 'PersonalStaffer.Desktop',
            guid: '920acec5-0950-413f-9494-a8f2f450c002',
          ),
        ),
        onDidReceiveNotificationResponse: (response) =>
            navigate(response.payload),
      );
      final launch = await local.getNotificationAppLaunchDetails();
      if (launch?.didNotificationLaunchApp == true) {
        navigate(launch?.notificationResponse?.payload);
      }
      if (Platform.isWindows) {
        state = 'READY_WHILE_RUNNING';
        poll = Timer.periodic(
          const Duration(seconds: 30),
          (_) => pollWindows(),
        );
      }
    } on Object {
      state = 'UNAVAILABLE';
    }
    if (Platform.isAndroid) {
      if (!const bool.fromEnvironment('FCM_ENABLED', defaultValue: false)) {
        state = 'NOT_CONFIGURED';
        return;
      }
      try {
        await Firebase.initializeApp();
        FirebaseMessaging.onBackgroundMessage(stafferBackgroundMessage);
        subscriptions.add(
          FirebaseMessaging.onMessage.listen((message) {
            repository.sync();
            showHint(message);
          }),
        );
        subscriptions.add(
          FirebaseMessaging.onMessageOpenedApp.listen(pushOpen),
        );
        subscriptions.add(
          FirebaseMessaging.instance.onTokenRefresh.listen(registerToken),
        );
        final initial = await FirebaseMessaging.instance.getInitialMessage();
        if (initial != null) pushOpen(initial);
        final permission = await FirebaseMessaging.instance.requestPermission();
        state = permission.authorizationStatus == AuthorizationStatus.authorized
            ? 'READY'
            : 'PERMISSION_DENIED';
        if (state == 'READY') {
          final token = await FirebaseMessaging.instance.getToken();
          if (token != null) await registerToken(token);
        }
        repository.session.addListener(refreshRegistration);
      } on Object {
        state = 'UNAVAILABLE';
      }
    }
  }

  Future<void> refreshRegistration() async {
    if (repository.session.signedIn &&
        Platform.isAndroid &&
        Firebase.apps.isNotEmpty) {
      try {
        final token = await FirebaseMessaging.instance.getToken();
        if (token != null) await registerToken(token);
      } on Object {
        state = 'REGISTRATION_PENDING';
      }
    }
  }

  Future<void> registerToken(String token) async {
    if (!repository.session.signedIn) return;
    try {
      await repository.session.request(
        'PUT',
        '/devices/${repository.session.deviceId}/push-token',
        body: {'push_token': token, 'platform': 'ANDROID'},
      );
      state = 'READY';
    } on ApiError {
      state = 'REGISTRATION_PENDING';
    }
  }

  Future<void> showHint(RemoteMessage message) async {
    final id = message.data['notification_id'];
    if (id is! String || !seen.add(id)) return;
    try {
      await local.show(
        id: id.hashCode & 0x7fffffff,
        title: 'Personal Staffer',
        body: 'A new update is available in your inbox.',
        notificationDetails: const NotificationDetails(
          android: AndroidNotificationDetails(
            'staffer_updates',
            'Application and job updates',
            channelDescription:
                'Updates from your private Personal Staffer server',
          ),
        ),
        payload: 'personalstaffer://notifications/$id',
      );
    } on Object {
      state = 'UNAVAILABLE';
    }
  }

  Future<void> pollWindows() async {
    if (showing || !repository.session.signedIn) return;
    showing = true;
    try {
      final inbox = await repository.session.request(
        'GET',
        '/notifications?unread_only=true&limit=100',
      );
      final rows = objects(inbox['items']);
      final fresh = rows.where((r) => !seen.contains(r['id'])).toList();
      seen.addAll(rows.map((r) => r['id'].toString()));
      // First launch reconstructs inbox without flooding old alerts. Later
      // batches summarize a backlog, preserving a concrete notification target.
      if (baseline && fresh.isNotEmpty) {
        final row = fresh.first;
        await local.show(
          id: row['id'].hashCode & 0x7fffffff,
          title: 'Personal Staffer',
          body: fresh.length > 1
              ? '${fresh.length} new updates in your inbox.'
              : 'A new update is available in your inbox.',
          notificationDetails: const NotificationDetails(
            windows: WindowsNotificationDetails(),
          ),
          payload: 'personalstaffer://notifications/${row['id']}',
        );
        repository.changed();
      }
      baseline = true;
      state = 'READY_WHILE_RUNNING';
    } on Object {
      state = 'UNAVAILABLE';
    } finally {
      showing = false;
    }
  }
}
