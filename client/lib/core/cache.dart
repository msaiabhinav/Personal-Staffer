import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';

import 'models.dart';

abstract class LocalCache {
  Future<Json?> read(String account, String key);
  Future<void> write(String account, String key, Json value);
  Future<void> enqueue(PendingOperation operation);
  Future<List<PendingOperation>> pending(String account);
  Future<void> removeOperation(String id);
  Future<void> clearAccount(String account);
  Future<void> invalidateResponses(String account);
  Future<void> replaceResponses(String account, Map<String, Json> responses);
  Future<void> close();
}

/// Drift owns all SQL access. The linked SQLite must support encryption in
/// release mode as well as debug; a plaintext fallback is deliberately refused.
class StafferDatabase extends GeneratedDatabase {
  StafferDatabase(super.executor);
  @override
  int get schemaVersion => 1;
  @override
  Iterable<TableInfo<Table, Object?>> get allTables => [];
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities => [];
  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (m) async {
      await customStatement(
        'CREATE TABLE cached_responses(account TEXT NOT NULL, cache_key TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(account,cache_key))',
      );
      await customStatement(
        'CREATE TABLE pending_operations(operation_id TEXT PRIMARY KEY, account TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)',
      );
    },
  );
}

class EncryptedCache implements LocalCache {
  EncryptedCache(this.db);
  final StafferDatabase db;
  static Future<EncryptedCache> open(
    FlutterSecureStorage secrets,
    String namespace,
  ) async {
    var key = await secrets.read(key: '$namespace.cache_key');
    key ??= List.generate(
      32,
      (_) => Random.secure().nextInt(256),
    ).map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    await secrets.write(key: '$namespace.cache_key', value: key);
    final dir = await getApplicationSupportDirectory();
    return EncryptedCache.openFile(
      File(path.join(dir.path, 'staffer-$namespace.db')),
      key,
    );
  }

  /// Also used by encryption integration tests on the actual linked library.
  static EncryptedCache openFile(File file, String key) {
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(key)) {
      throw ArgumentError('Invalid cache key');
    }
    return EncryptedCache(
      StafferDatabase(
        NativeDatabase(
          file,
          setup: (raw) {
            if (raw.select('PRAGMA cipher;').isEmpty) {
              throw StateError(
                'Encrypted SQLite unavailable. Sensitive cache refused.',
              );
            }
            raw.execute("PRAGMA key = '$key';");
            raw.execute('PRAGMA foreign_keys = ON;');
          },
        ),
      ),
    );
  }

  @override
  Future<Json?> read(String account, String key) async {
    final rows = await db
        .customSelect(
          'SELECT payload FROM cached_responses WHERE account=? AND cache_key=?',
          variables: [Variable(account), Variable(key)],
        )
        .get();
    return rows.isEmpty
        ? null
        : object(jsonDecode(rows.first.read<String>('payload')));
  }

  @override
  Future<void> write(String account, String key, Json value) =>
      db.customStatement(
        'INSERT INTO cached_responses VALUES(?,?,?) ON CONFLICT(account,cache_key) DO UPDATE SET payload=excluded.payload',
        [account, key, jsonEncode(value)],
      );
  @override
  Future<void> enqueue(PendingOperation op) => db.customStatement(
    'INSERT INTO pending_operations VALUES(?,?,?,?) ON CONFLICT(operation_id) DO UPDATE SET payload=excluded.payload',
    [op.id, op.account, op.createdAt.toUtc().toIso8601String(), op.encode()],
  );
  @override
  Future<List<PendingOperation>> pending(String account) async =>
      (await db
              .customSelect(
                'SELECT payload FROM pending_operations WHERE account=? ORDER BY created_at,operation_id',
                variables: [Variable(account)],
              )
              .get())
          .map(
            (r) => PendingOperation.fromJson(
              object(jsonDecode(r.read<String>('payload'))),
            ),
          )
          .toList();
  @override
  Future<void> removeOperation(String id) => db.customStatement(
    'DELETE FROM pending_operations WHERE operation_id=?',
    [id],
  );
  @override
  Future<void> invalidateResponses(String account) => db.customStatement(
    'DELETE FROM cached_responses WHERE account=? AND cache_key != ?',
    [account, '__sync'],
  );
  @override
  Future<void> replaceResponses(String account, Map<String, Json> responses) =>
      db.transaction(() async {
        await db.customStatement(
          'DELETE FROM cached_responses WHERE account=?',
          [account],
        );
        for (final entry in responses.entries) {
          await write(account, entry.key, entry.value);
        }
      });
  @override
  Future<void> clearAccount(String account) => db.transaction(() async {
    await db.customStatement('DELETE FROM cached_responses WHERE account=?', [
      account,
    ]);
    await db.customStatement('DELETE FROM pending_operations WHERE account=?', [
      account,
    ]);
  });
  @override
  Future<void> close() => db.close();
}

/// Isolated deterministic test adapter; never selected by production bootstrap.
class MemoryCache implements LocalCache {
  final _responses = <String, Json>{};
  final _operations = <String, PendingOperation>{};
  @override
  Future<Json?> read(String a, String k) async => _responses['$a:$k'];
  @override
  Future<void> write(String a, String k, Json v) async {
    _responses['$a:$k'] = v;
  }

  @override
  Future<void> enqueue(PendingOperation o) async {
    _operations[o.id] = o;
  }

  @override
  Future<List<PendingOperation>> pending(String a) async =>
      _operations.values.where((o) => o.account == a).toList()
        ..sort((a, b) => a.createdAt.compareTo(b.createdAt));
  @override
  Future<void> removeOperation(String id) async {
    _operations.remove(id);
  }

  @override
  Future<void> invalidateResponses(String a) async {
    _responses.removeWhere((k, v) => k.startsWith('$a:') && k != '$a:__sync');
  }

  @override
  Future<void> replaceResponses(String a, Map<String, Json> responses) async {
    _responses.removeWhere((k, v) => k.startsWith('$a:'));
    for (final entry in responses.entries) {
      _responses['$a:${entry.key}'] = entry.value;
    }
  }

  @override
  Future<void> clearAccount(String a) async {
    _responses.removeWhere((k, v) => k.startsWith('$a:'));
    _operations.removeWhere((k, v) => v.account == a);
  }

  @override
  Future<void> close() async {}
}
