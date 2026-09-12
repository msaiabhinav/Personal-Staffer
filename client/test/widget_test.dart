import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_staffer/app.dart';
import 'package:personal_staffer/features/jobs.dart';
import 'package:personal_staffer/main.dart' as entrypoint;
import 'package:personal_staffer/core/api.dart';
import 'package:personal_staffer/core/cache.dart';
import 'package:personal_staffer/core/models.dart';
import 'package:personal_staffer/core/providers.dart';
import 'package:personal_staffer/core/repository.dart';

Future<StafferRepository> repository(
  Json Function(http.Request) response,
) async {
  FlutterSecureStorage.setMockInitialValues({});
  final session = Session(
    Uri.parse('http://127.0.0.1:8000'),
    const FlutterSecureStorage(),
    client: MockClient(
      (request) async => http.Response(
        jsonEncode(response(request)),
        200,
        headers: {'content-type': 'application/json'},
      ),
    ),
  );
  await session.restore();
  await session.accept({
    'access_token': 'unit-token',
    'refresh_token': 'unit-refresh',
    'user_id': 'test-owner',
    'device_id': 'test-device',
  });
  return StafferRepository(session, MemoryCache());
}

void main() {
  test('AT-44 destination allowlist retains exact record and rejects unsafe routes', () {
    for (final type in [
      'jobs',
      'applications',
      'reviews',
      'reports',
      'search-runs',
    ]) {
      expect(
        internalDestination('personalstaffer://$type/abc-123'),
        '/$type/abc-123',
      );
    }
    for (final bad in [
      'https://evil.example/jobs/a',
      'javascript:alert(1)',
      'personalstaffer://jobs/a/extra',
      'personalstaffer://jobs/a?token=x',
      '//evil/jobs/a',
      'personalstaffer://settings/a',
    ]) {
      expect(internalDestination(bad), isNull);
    }
  });
  test(
    'API origin accepts loopback development and requires HTTPS remotely',
    () {
      expect(validateApiOrigin('http://127.0.0.1:8000').host, '127.0.0.1');
      expect(
        () => validateApiOrigin('http://example.com'),
        throwsArgumentError,
      );
      expect(
        () => validateApiOrigin('https://user:pass@example.com'),
        throwsArgumentError,
      );
    },
  );
  test(
    'AT-49 offline operation is persisted with original account and revision',
    () async {
      FlutterSecureStorage.setMockInitialValues({});
      final session = Session(
        Uri.parse('http://127.0.0.1:8000'),
        const FlutterSecureStorage(),
        client: MockClient((_) async => throw const SocketException('offline')),
      );
      await session.restore();
      await session.accept({
        'access_token': 't',
        'refresh_token': 'r',
        'user_id': 'owner-a',
      });
      final cache = MemoryCache();
      final repo = StafferRepository(session, cache);
      final result = await repo.command('save', 'job-a', {
        'saved': true,
        'expected_revision': 7,
      });
      expect(result['pending'], true);
      final pending = await cache.pending('owner-a');
      expect(pending.single.payload['expected_revision'], 7);
      expect(await cache.pending('owner-b'), isEmpty);
      expect(
        () => repo.command('apply', 'job-a', {'expected_revision': 7}),
        throwsA(isA<ApiError>()),
      );
      repo.dispose();
    },
  );
  test('AT-49 conflict never overwrites newer server activity', () async {
    final repo = await repository((r) {
      final op = objects(object(jsonDecode(r.body))['operations']).single;
      return {
        'results': [
          {
            'operation_id': op['operation_id'],
            'status': 'conflict',
            'error': {'user_message': 'New interview activity exists'},
          },
        ],
      };
    });
    final result = await repo.command('correction', 'application-a', {
      'expected_revision': 1,
      'event_id': 'apply-event',
      'action': 'UNDO_APPLIED',
    });
    expect(result['conflict'], true);
    expect(repo.operations.single.state, 'conflict');
    expect(repo.operations.single.error, contains('interview'));
    repo.dispose();
  });
  testWidgets('First viewed job saves against the acknowledged view revision', (
    tester,
  ) async {
    Json? submitted;
    final repo = await repository((request) {
      if (request.url.path.endsWith('/view')) return {'revision': 1};
      if (request.url.path.endsWith('/sync/operations')) {
        final operation = objects(
          object(jsonDecode(request.body))['operations'],
        ).single;
        submitted = object(operation['payload']);
        return {
          'results': [
            {
              'operation_id': operation['operation_id'],
              'status': 'accepted',
              'result': {'revision': 2},
            },
          ],
        };
      }
      if (request.url.path.endsWith('/sync/snapshot')) {
        return {
          'snapshot_id': 's',
          'items': [],
          'next_cursor': 'boundary',
          'has_more': false,
        };
      }
      return {
        'id': 'job1',
        'title': 'Analyst',
        'company': 'Example',
        'availability': 'ACTIVE',
        'state': {'revision': 0, 'is_saved': false},
        'snapshot': {'description': 'Retained job description'},
        'sources': [],
      };
    });
    await tester.pumpWidget(
      ProviderScope(
        overrides: [repositoryProvider.overrideWith((_) => repo)],
        child: const MaterialApp(
          home: Scaffold(body: JobDetail(id: 'job1')),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(OutlinedButton, 'Save'));
    await tester.pumpAndSettle();
    expect(submitted?['expected_revision'], 1);
    expect(submitted?['saved'], true);
  });
  testWidgets(
    'Malformed stored session never exposes its contents at startup',
    (tester) async {
      final session = Session(
        Uri.parse('http://127.0.0.1:8000'),
        const FlutterSecureStorage(),
      );
      FlutterSecureStorage.setMockInitialValues({
        '${session.namespace}.session':
            'SENSITIVE_SESSION_SENTINEL malformed JSON',
      });
      await entrypoint.main();
      await tester.pumpAndSettle();
      expect(find.text('Personal Staffer could not start'), findsOneWidget);
      expect(find.textContaining('SENSITIVE_SESSION_SENTINEL'), findsNothing);
      expect(find.textContaining('FormatException'), findsNothing);
    },
  );
  testWidgets('AT-60 exact native navigation and Homepage tabs', (
    tester,
  ) async {
    tester.view.resetPhysicalSize();
    tester.view.physicalSize = const Size(1400, 950);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repo = await repository(
      (r) => r.url.path.endsWith('unread-count')
          ? {'unread_count': 0}
          : {'items': [], 'has_more': false},
    );
    final router = createRouter(repo.session);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [repositoryProvider.overrideWith((_) => repo)],
        child: StafferApp(router: router),
      ),
    );
    await tester.pumpAndSettle();
    for (final name in navLabels) {
      expect(find.text(name), findsWidgets);
    }
    expect(find.text('Job Feed'), findsOneWidget);
    expect(find.text('Application Dashboard'), findsOneWidget);
    expect(find.text('No qualifying jobs delivered yet'), findsOneWidget);
    await tester.tap(find.text('Saved Jobs').first);
    await tester.pumpAndSettle();
    expect(find.text('Keep an opportunity for later'), findsOneWidget);
    router.dispose();
  });
  testWidgets('AT-58 narrow large-font layout remains usable', (tester) async {
    tester.view.physicalSize = const Size(430, 932);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repo = await repository(
      (r) => r.url.path.endsWith('unread-count')
          ? {'unread_count': 3}
          : {'items': []},
    );
    final router = createRouter(repo.session);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [repositoryProvider.overrideWith((_) => repo)],
        child: MediaQuery(
          data: const MediaQueryData(textScaler: TextScaler.linear(1.3)),
          child: StafferApp(router: router),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(NavigationBar), findsOneWidget);
    router.dispose();
  });
  testWidgets(
    'AT-44 signed-out notification keeps destination through sign-in',
    (tester) async {
      final repo = await repository((r) => {'items': []});
      repo.session.accessToken = null;
      final router = createRouter(
        repo.session,
        initial: '/notifications/abc-123',
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [repositoryProvider.overrideWith((_) => repo)],
          child: StafferApp(router: router),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Continue with Google'), findsOneWidget);
      expect(
        router.routeInformationProvider.value.uri.queryParameters['next'],
        '/notifications/abc-123',
      );
      router.dispose();
    },
  );
}
