import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_staffer/core/cache.dart';

void main() {
  test('AT-55 linked encrypted SQLite stores unreadable bytes and reopens with key', () async {
    final dir = await Directory.systemTemp.createTemp('staffer-cache-test-');
    final file = File('${dir.path}/cache.db');
    final key = List.filled(64, 'a').join();
    var cache = EncryptedCache.openFile(file, key);
    await cache.write('owner', '/jobs', {
      'private': 'sensitive-job-description',
    });
    await cache.close();
    final bytes = await file.readAsBytes();
    expect(
      String.fromCharCodes(bytes.take(16)),
      isNot(startsWith('SQLite format 3')),
    );
    expect(
      String.fromCharCodes(bytes),
      isNot(contains('sensitive-job-description')),
    );
    cache = EncryptedCache.openFile(file, key);
    expect(
      (await cache.read('owner', '/jobs'))?['private'],
      'sensitive-job-description',
    );
    await cache.close();
    final wrong = EncryptedCache.openFile(file, List.filled(64, 'b').join());
    await expectLater(wrong.read('owner', '/jobs'), throwsA(anything));
    await wrong.close();
    await dir.delete(recursive: true);
  });
}
