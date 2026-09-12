import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'cache.dart';
import 'models.dart';
import 'snapshot_projection.dart';

class StafferRepository extends ChangeNotifier {
  StafferRepository(this.session, this.cache);
  final Session session;
  final LocalCache cache;
  bool offline = false, syncing = false;
  String? syncMessage;
  String notificationState = 'NOT_CONFIGURED';
  void updateNotificationState(String value) {
    if (notificationState == value) return;
    notificationState = value;
    notifyListeners();
  }

  int revision = 0;
  List<PendingOperation> operations = [];
  Timer? _timer;
  String get account => session.account ?? '';
  Future<void> start() async {
    operations = await cache.pending(account);
    _timer ??= Timer.periodic(const Duration(seconds: 30), (_) => sync());
    await sync();
  }

  void changed() {
    revision++;
    notifyListeners();
  }

  Future<Json> get(String route, {bool allowCache = true}) async {
    final owner = account;
    final generation = session.generation;
    try {
      final j = await session.request('GET', route);
      if (generation != session.generation || owner != account) {
        throw session.changedSession;
      }
      await cache.write(owner, route, j);
      offline = false;
      return j;
    } on ApiError catch (e) {
      if (e.retryable &&
          allowCache &&
          generation == session.generation &&
          owner == account) {
        final cached = await cache.read(owner, route);
        offline = true;
        if (cached != null) return {...cached, '_cached': true};
      }
      rethrow;
    }
  }

  bool pendingFor(String target) => operations.any((o) => o.target == target);
  Future<Json> command(String command, String target, Json payload) async {
    if (account.isEmpty) {
      throw ApiError('SESSION_EXPIRED', 'Sign in before changing a record.');
    }
    if (pendingFor(target)) {
      throw ApiError(
        'PENDING_OPERATION',
        'This record already has a pending change. Sync or resolve it first.',
      );
    }
    payload = {...payload};
    final effective = DateTime.now().toUtc().toIso8601String();
    if (command == 'apply') payload.putIfAbsent('applied_at', () => effective);
    if (command == 'status') {
      payload.putIfAbsent('effective_at', () => effective);
    }
    final op = PendingOperation(
      id: const Uuid().v4(),
      account: account,
      command: command,
      target: target,
      payload: payload,
      createdAt: DateTime.now().toUtc(),
    );
    await cache.enqueue(op);
    operations = await cache.pending(account);
    changed();
    return _submit(op);
  }

  Future<Json> _submit(PendingOperation op) async {
    if (op.account != account) {
      throw ApiError(
        'ACCOUNT_MISMATCH',
        'This pending change belongs to a different account.',
      );
    }
    if (DateTime.now().toUtc().difference(op.createdAt) >
        const Duration(days: 89)) {
      await cache.enqueue(
        op.failed(
          'This change is older than the safe retry window. Review the current record and issue a new action.',
        ),
      );
      operations = await cache.pending(op.account);
      changed();
      return {'conflict': true};
    }
    try {
      final j = await session.request(
        'POST',
        '/sync/operations',
        body: {
          'operations': [op.forServer()],
        },
      );
      final result = objects(j['results']).firstWhere(
        (r) => r['operation_id'] == op.id,
        orElse: () => throw ApiError(
          'INVALID_RESPONSE',
          'The server did not acknowledge this change.',
          retryable: true,
        ),
      );
      if (result['status'] == 'accepted') {
        await cache.removeOperation(op.id);
        await cache.write(op.account, '__needs_snapshot', {'required': true});
        try {
          await _resnapshot();
          offline = false;
          syncMessage = null;
        } on ApiError catch (error) {
          offline = error.retryable;
          syncMessage =
              'Change recorded; waiting to refresh the complete snapshot.';
        }
        operations = await cache.pending(op.account);
        changed();
        return object(result['result']);
      }
      final error = object(result['error']);
      await cache.enqueue(
        op.failed(
          label(
            error['user_message'] ?? error['message'] ?? result['error'],
            'This record changed on another device. Review its latest history before retrying.',
          ),
        ),
      );
      operations = await cache.pending(op.account);
      changed();
      return {'conflict': true};
    } on ApiError catch (e) {
      if (e.retryable || e.status == 401) {
        offline = e.retryable;
        syncMessage = e.message;
        operations = await cache.pending(op.account);
        changed();
        return {'pending': true};
      }
      await cache.enqueue(op.failed(e.message));
      operations = await cache.pending(op.account);
      changed();
      return {'conflict': true};
    }
  }

  Future<void> discard(PendingOperation op) async {
    if (op.account != account) return;
    await cache.removeOperation(op.id);
    operations = await cache.pending(account);
    changed();
  }

  Future<void> sync() async {
    if (syncing || !session.signedIn) return;
    syncing = true;
    notifyListeners();
    final owner = account;
    final generation = session.generation;
    try {
      for (final op in await cache.pending(owner)) {
        if (op.state == 'pending') await _submit(op);
      }
      if (owner != account || generation != session.generation) {
        throw session.changedSession;
      }
      var cursor = (await cache.read(owner, '__sync'))?['cursor'];
      if (cursor == null ||
          (await cache.read(owner, '__needs_snapshot'))?['required'] == true) {
        cursor = await _resnapshot();
      }
      bool more = true, needsSnapshot = false;
      while (more) {
        Json page;
        try {
          page = await session.request(
            'GET',
            '/sync/changes?cursor=${Uri.encodeQueryComponent(cursor.toString())}',
          );
        } on ApiError catch (e) {
          if (e.code != 'RESYNC_REQUIRED') rethrow;
          cursor = await _resnapshot();
          page = await session.request(
            'GET',
            '/sync/changes?cursor=${Uri.encodeQueryComponent(cursor.toString())}',
          );
        }
        final changes = objects(page['items'] ?? page['changes']);
        needsSnapshot =
            needsSnapshot ||
            changes.any(
              (c) => (c['entity_type'] ?? c['type']) != 'sync_boundary',
            );
        cursor = page['next_cursor'] ?? page['cursor'];
        more = page['has_more'] == true;
      }
      if (owner != account || generation != session.generation) {
        throw session.changedSession;
      }
      if (needsSnapshot) {
        await _resnapshot();
      } else {
        await cache.write(owner, '__sync', {'cursor': cursor});
      }
      offline = false;
      syncMessage = null;
      changed();
    } on ApiError catch (e) {
      offline = e.retryable;
      syncMessage = e.message;
    } finally {
      syncing = false;
      operations = await cache.pending(account);
      notifyListeners();
    }
  }

  Future<Object?> _resnapshot() async {
    final owner = account;
    final generation = session.generation;
    final items = <Json>[];
    var page = await session.request('POST', '/sync/snapshot', body: {});
    final id = page['snapshot_id'];
    items.addAll(objects(page['items']));
    while (page['has_more'] == true) {
      page = await session.request(
        'GET',
        '/sync/snapshot/$id?offset=${page['next_offset']}&limit=100',
      );
      items.addAll(objects(page['items']));
    }
    final cursor = page['next_cursor'];
    if (cursor == null) {
      throw ApiError(
        'INVALID_SNAPSHOT',
        'The synchronization snapshot did not complete.',
        retryable: true,
      );
    }
    final responses = snapshotResponses(items, now: DateTime.now().toUtc());
    responses['__sync'] = {'cursor': cursor};
    if (owner != account || generation != session.generation) {
      throw session.changedSession;
    }
    // One transaction swaps the completed snapshot and cursor. Pending commands
    // occupy a different table and are never erased by resynchronization.
    await cache.replaceResponses(owner, responses);
    return cursor;
  }

  Future<void> signOut() async {
    final old = account;
    await session.logout();
    await cache.clearAccount(old);
    operations = [];
    changed();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
