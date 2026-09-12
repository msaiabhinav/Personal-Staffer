import 'dart:convert';
import 'dart:async';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_staffer/core/api.dart';
import 'package:personal_staffer/core/cache.dart';
import 'package:personal_staffer/core/models.dart';
import 'package:personal_staffer/core/repository.dart';

void main() {
  test('AT-50 expired cursor consumes complete snapshot, drops stale rows, retains unresolved local operations', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final paths = <String>[];
    final session = Session(
      Uri.parse('http://127.0.0.1:8000'),
      const FlutterSecureStorage(),
      client: MockClient((request) async {
        paths.add(
          request.url.path +
              (request.url.hasQuery ? '?${request.url.query}' : ''),
        );
        if (request.url.query == 'cursor=old') {
          return http.Response(
            jsonEncode({
              'code': 'RESYNC_REQUIRED',
              'user_message': 'Resnapshot required',
            }),
            409,
          );
        }
        final Json result;
        if (request.url.path.endsWith('/sync/snapshot')) {
          result = {
            'snapshot_id': 's1',
            'items': [
              {'entity_type': 'saved', 'tombstone': true},
            ],
            'next_offset': 1,
            'next_cursor': null,
            'has_more': true,
          };
        } else if (request.url.path.endsWith('/sync/snapshot/s1')) {
          result = {
            'snapshot_id': 's1',
            'items': [],
            'next_cursor': 'boundary',
            'has_more': false,
          };
        } else {
          result = {'items': [], 'next_cursor': 'boundary', 'has_more': false};
        }
        return http.Response(jsonEncode(result), 200);
      }),
    );
    await session.restore();
    await session.accept({
      'user_id': 'owner',
      'access_token': 'a',
      'refresh_token': 'r',
    });
    final cache = MemoryCache();
    await cache.write('owner', '__sync', {'cursor': 'old'});
    await cache.write('owner', '/saved-jobs', {
      'items': [
        {'id': 'voided-job'},
      ],
    });
    await cache.enqueue(
      PendingOperation(
        id: 'unresolved',
        account: 'owner',
        command: 'correction',
        target: 'app1',
        payload: {'expected_revision': 1},
        createdAt: DateTime.now(),
        state: 'conflict',
        error: 'Newer event',
      ),
    );
    final repo = StafferRepository(session, cache);
    await repo.sync();
    expect((await cache.read('owner', '/saved-jobs'))?['items'], isEmpty);
    expect((await cache.read('owner', '__sync'))?['cursor'], 'boundary');
    expect((await cache.pending('owner')).single.id, 'unresolved');
    expect(paths, contains('/api/v1/sync/snapshot/s1?offset=1&limit=100'));
    repo.dispose();
  });
  test(
    'expired access rotates refresh and replays the same idempotency key once',
    () async {
      FlutterSecureStorage.setMockInitialValues({});
      var rotates = 0;
      final keys = <String?>[];
      final session = Session(
        Uri.parse('https://private.example'),
        const FlutterSecureStorage(),
        client: MockClient((request) async {
          if (request.url.path.endsWith('/auth/refresh')) {
            rotates++;
            return http.Response(
              jsonEncode({
                'access_token': 'new',
                'refresh_token': 'new-r',
                'user_id': 'owner',
                'device_id': 'device',
              }),
              200,
            );
          }
          keys.add(request.headers['Idempotency-Key']);
          if (request.headers['Authorization'] == 'Bearer old') {
            return http.Response(
              jsonEncode({
                'code': 'SESSION_EXPIRED',
                'user_message': 'Expired',
              }),
              401,
            );
          }
          return http.Response(jsonEncode({'accepted': true}), 200);
        }),
      );
      await session.restore();
      await session.accept({
        'access_token': 'old',
        'refresh_token': 'old-r',
        'user_id': 'owner',
        'device_id': 'device',
      });
      final response = await session.request(
        'POST',
        '/jobs/job1/application-open',
        body: {},
      );
      expect(response['accepted'], true);
      expect(rotates, 1);
      expect(keys.length, 2);
      expect(keys.first, isNotEmpty);
      expect(keys.first, keys.last);
    },
  );
  test('sign-out cannot cache a delayed response under another account',()async{
    FlutterSecureStorage.setMockInitialValues({});final delayed=Completer<http.Response>();
    final session=Session(Uri.parse('https://private.example'),const FlutterSecureStorage(),client:MockClient((r)async{
      if(r.url.path.endsWith('/saved-jobs'))return delayed.future;
      return http.Response('{}',200);
    }));await session.restore();await session.accept({'access_token':'old','refresh_token':'old-r','user_id':'owner'});
    final cache=MemoryCache();final repo=StafferRepository(session,cache);
    final result=repo.get('/saved-jobs');final check=expectLater(result,throwsA(isA<ApiError>()));
    await repo.signOut();delayed.complete(http.Response(jsonEncode({'items':[{'private':'secret'}]}),200));await check;
    expect(await cache.read('', '/saved-jobs'),isNull);expect(await cache.read('owner','/saved-jobs'),isNull);repo.dispose();
  });
  test('a refresh completed after sign-out cannot restore old credentials',()async{
    FlutterSecureStorage.setMockInitialValues({});final refreshStarted=Completer<void>(),refresh=Completer<http.Response>();
    final session=Session(Uri.parse('https://private.example'),const FlutterSecureStorage(),client:MockClient((r)async{
      if(r.url.path.endsWith('/auth/refresh')){refreshStarted.complete();return refresh.future;}
      if(r.url.path.endsWith('/auth/logout'))return http.Response('{}',200);
      return http.Response('{"code":"SESSION_EXPIRED"}',401);
    }));await session.restore();await session.accept({'access_token':'old','refresh_token':'old-r','user_id':'owner'});
    final response=session.request('GET','/saved-jobs');final check=expectLater(response,throwsA(isA<ApiError>()));
    await refreshStarted.future;await session.logout();
    refresh.complete(http.Response(jsonEncode({'access_token':'new','refresh_token':'new-r','user_id':'owner'}),200));await check;
    expect(session.signedIn,false);expect(await session.secrets.read(key:'${session.namespace}.session'),isNull);
  });

}
