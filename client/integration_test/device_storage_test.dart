import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:personal_staffer/core/cache.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Device secure key round-trip and encrypted cache reopen', (
    tester,
  ) async {
    const storage = FlutterSecureStorage();
    const namespace = 'device-acceptance-test';
    var cache = await EncryptedCache.open(storage, namespace);
    await cache.write('acceptance', 'probe', {'value': 'retained'});
    await cache.close();
    cache = await EncryptedCache.open(storage, namespace);
    expect((await cache.read('acceptance', 'probe'))?['value'], 'retained');
    await cache.clearAccount('acceptance');
    await cache.close();
  });
}
