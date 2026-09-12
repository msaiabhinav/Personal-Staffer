import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import 'package:uuid/uuid.dart';

import 'models.dart';

class ApiError implements Exception {
  ApiError(
    this.code,
    this.message, {
    this.status = 0,
    this.retryable = false,
    this.details = const {},
  });
  final String code, message;
  final int status;
  final bool retryable;
  final Json details;
  @override
  String toString() => message;
}

class Session extends ChangeNotifier {
  Session(this.origin, this.secrets, {http.Client? client})
    : client = client ?? http.Client();
  final Uri origin;
  final FlutterSecureStorage secrets;
  final http.Client client;
  String? accessToken, refreshToken, account, deviceId;
  String? flowId, verifier;
  int generation = 0;
  Future<void> _secretWrites = Future.value();
  ApiError get changedSession => ApiError(
    'SESSION_CHANGED',
    'Your session changed. Open the record again.',
    status: 401,
  );
  bool get signedIn => accessToken != null && account != null;
  String get namespace =>
      '${sha256.convert(utf8.encode(origin.toString())).toString().substring(0, 16)}-${const bool.fromEnvironment('DEMO_MODE') ? 'demo' : 'live'}';
  Future<void> restore() async {
    deviceId =
        await secrets.read(key: '$namespace.device') ?? const Uuid().v4();
    await secrets.write(key: '$namespace.device', value: deviceId);
    final raw = await secrets.read(key: '$namespace.session');
    if (raw != null) {
      final j = object(jsonDecode(raw));
      accessToken = j['access_token'];
      refreshToken = j['refresh_token'];
      account = j['user_id'];
    }
    final login = await secrets.read(key: '$namespace.login');
    if (login != null) {
      final j = object(jsonDecode(login));
      flowId = j['flow_id'];
      verifier = j['verifier'];
    }
    notifyListeners();
  }

  Future<void> _persist(Json? value, int expectedGeneration) {
    _secretWrites = _secretWrites.catchError((Object _) {}).then((_) async {
      if (generation != expectedGeneration) return;
      if (value == null) {
        await secrets.delete(key: '$namespace.session');
        await secrets.delete(key: '$namespace.login');
      } else {
        await secrets.write(
          key: '$namespace.session',
          value: jsonEncode(value),
        );
      }
    });
    return _secretWrites;
  }

  Future<void> accept(Json j, {int? expectedGeneration}) async {
    if (expectedGeneration != null && expectedGeneration != generation) {
      throw changedSession;
    }
    if (j['access_token'] == null ||
        j['refresh_token'] == null ||
        j['user_id'] == null) {
      throw ApiError(
        'INVALID_SESSION',
        'The server returned an incomplete session.',
      );
    }
    if (account != j['user_id']) generation++;
    final acceptedGeneration = generation;
    accessToken = j['access_token'];
    refreshToken = j['refresh_token'];
    account = j['user_id'];
    deviceId = j['device_id'] ?? deviceId;
    await _persist(j, acceptedGeneration);
    if (generation != acceptedGeneration) throw changedSession;
    notifyListeners();
  }

  Future<Json> startGmail() async {
    final value = base64UrlEncode(
      List.generate(32, (_) => Random.secure().nextInt(256)),
    ).replaceAll('=', '');
    final challenge = base64UrlEncode(sha256.convert(utf8.encode(value)).bytes)
        .replaceAll('=', '');
    return request(
      'POST',
      '/gmail/connect',
      body: {
        'device_id': deviceId,
        'platform': Platform.isWindows ? 'WINDOWS' : 'ANDROID',
        'device_label': 'Gmail connection',
        'challenge': challenge,
      },
    );
  }

  Future<void> startDemo() async {
    final startedGeneration = generation;
    if (!const bool.fromEnvironment('DEMO_MODE')) {
      throw ApiError(
        'DEMO_DISABLED',
        'This build does not include demo sign-in.',
      );
    }
    final version = await request('GET', '/version', authenticated: false);
    if (version['demo_mode'] != true) {
      throw ApiError(
        'DEMO_DISABLED',
        'The server has not enabled isolated local demo mode.',
      );
    }
    await accept(
      await request(
        'POST',
        '/auth/demo',
        authenticated: false,
        body: {
          'device_id': deviceId,
          'platform': Platform.isWindows ? 'WINDOWS' : 'ANDROID',
          'device_label': 'Local demo device',
        },
      ),
      expectedGeneration: startedGeneration,
    );
  }

  Future<Json> startLogin() async {
    verifier = base64UrlEncode(
      List.generate(32, (_) => Random.secure().nextInt(256)),
    ).replaceAll('=', '');
    final challenge = base64UrlEncode(
      sha256.convert(utf8.encode(verifier!)).bytes,
    ).replaceAll('=', '');
    final j = await request(
      'POST',
      '/auth/login/start',
      body: {
        'device_id': deviceId,
        'platform': Platform.isWindows ? 'WINDOWS' : 'ANDROID',
        'device_label': Platform.isWindows
            ? 'Windows desktop'
            : 'Android phone',
        'challenge': challenge,
      },
      authenticated: false,
    );
    flowId = j['flow_id'];
    await secrets.write(
      key: '$namespace.login',
      value: jsonEncode({'flow_id': flowId, 'verifier': verifier}),
    );
    final uri = externalDestination(j['authorization_url']);
    if (uri == null ||
        !await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      throw ApiError(
        'BROWSER_UNAVAILABLE',
        'Could not open Google sign-in. Check your default browser.',
      );
    }
    return j;
  }

  bool _exchanging = false;
  Future<bool> finishLogin() async {
    if (_exchanging) return false;
    if (flowId == null || verifier == null) return false;
    _exchanging = true;
    final startedGeneration = generation;
    try {
      final j = await request(
        'POST',
        '/auth/login/exchange',
        body: {'flow_id': flowId, 'verifier': verifier, 'device_id': deviceId},
        authenticated: false,
      );
      await accept(j, expectedGeneration: startedGeneration);
      flowId = null;
      verifier = null;
      await secrets.delete(key: '$namespace.login');
      return true;
    } on ApiError catch (e) {
      if (e.code == 'AUTH_PENDING') return false;
      rethrow;
    } finally {
      _exchanging = false;
    }
  }

  Future<void> logout() async {
    // Build the revocation request while its original access token is present;
    // invalidate in-memory identity immediately. A stale refresh cannot re-login.
    final revocation = request(
      'POST',
      '/auth/logout',
      body: {},
    ).catchError((Object _) => <String, dynamic>{});
    generation++;
    accessToken = null;
    refreshToken = null;
    account = null;
    flowId = null;
    verifier = null;
    final logoutGeneration = generation;
    notifyListeners();
    await _persist(null, logoutGeneration);
    try {
      await revocation;
    } on ApiError {
      /* Offline local sign-out still clears secrets. */
    }
  }

  Future<Json>? _rotation;
  Future<Json> request(
    String method,
    String route, {
    Json? body,
    String? operationId,
    bool authenticated = true,
    bool retried = false,
  }) async {
    final requestGeneration = generation;
    if (method != 'GET') operationId ??= const Uuid().v4();
    if (!route.startsWith('/') || route.startsWith('//')) {
      throw ArgumentError('Relative API route required');
    }
    final uri = Uri.parse(
      '${origin.toString().replaceAll(RegExp(r'/$'), '')}/api/v1$route',
    );
    final req = http.Request(method, uri)
      ..headers['Accept'] = 'application/json';
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    if (authenticated && accessToken != null) {
      req.headers['Authorization'] = 'Bearer $accessToken';
    }
    if (operationId != null) req.headers['Idempotency-Key'] = operationId;
    http.Response response;
    try {
      response = await http.Response.fromStream(
        await client.send(req).timeout(const Duration(seconds: 30)),
      ).timeout(const Duration(seconds: 30));
    } on Object catch (e) {
      if (e is SocketException ||
          e is http.ClientException ||
          e is TimeoutException) {
        throw ApiError(
          'OFFLINE',
          'Cannot reach the server. Cached records are available; changes stay Pending.',
          retryable: true,
        );
      }
      rethrow;
    }
    if (authenticated && generation != requestGeneration) throw changedSession;
    if (response.statusCode == 401 &&
        authenticated &&
        !retried &&
        refreshToken != null) {
      try {
        _rotation ??= request(
          'POST',
          '/auth/refresh',
          body: {'refresh_token': refreshToken, 'device_id': deviceId},
          authenticated: false,
        );
        await accept(await _rotation!, expectedGeneration: requestGeneration);
      } on ApiError catch (e) {
        if (e.retryable || requestGeneration != generation) rethrow;
        accessToken = null;
        notifyListeners();
        throw ApiError(
          'SESSION_EXPIRED',
          'Sign in again to sync your pending changes.',
          status: 401,
        );
      } finally {
        _rotation = null;
      }
      return request(
        method,
        route,
        body: body,
        operationId: operationId,
        retried: true,
      );
    }
    Json data = {};
    if (response.body.isNotEmpty) {
      try {
        data = object(jsonDecode(response.body));
      } on FormatException {
        throw ApiError(
          'INVALID_RESPONSE',
          'The server response could not be read.',
          status: response.statusCode,
          retryable: response.statusCode >= 500,
        );
      }
    }
    if (response.statusCode >= 400) {
      final error = data.containsKey('error') ? object(data['error']) : data;
      throw ApiError(
        label(error['code'], 'HTTP_${response.statusCode}'),
        label(
          error['user_message'] ?? error['message'],
          'Request failed. Please try again.',
        ),
        status: response.statusCode,
        retryable: error['retryable'] == true || response.statusCode >= 500,
        details: object(error['details']),
      );
    }
    return data;
  }
}

Uri validateApiOrigin(String value) {
  final uri = Uri.parse(value);
  final local = {
    'localhost',
    '127.0.0.1',
    '10.0.2.2',
    '::1',
  }.contains(uri.host);
  if (uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      (uri.path != '' && uri.path != '/') ||
      uri.host.isEmpty ||
      (uri.scheme != 'https' &&
          !(uri.scheme == 'http' && local && !kReleaseMode))) {
    throw ArgumentError(
      'Use an HTTPS server origin. Debug allows local loopback only.',
    );
  }
  return uri;
}
