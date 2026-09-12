import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'app.dart';
import 'core/api.dart';
import 'core/cache.dart';
import 'core/providers.dart';
import 'core/repository.dart';
import 'core/history.dart';
import 'core/notifications.dart';
import 'core/theme.dart';
import 'features/shared.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    const origin = String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: 'http://127.0.0.1:5555',
    );
    const secrets = FlutterSecureStorage();
    final theme = ThemeController(secrets);
    await theme.restore();
    final session = Session(validateApiOrigin(origin), secrets);
    await session.restore();
    final cache = await EncryptedCache.open(secrets, session.namespace);
    // Force the encrypted database to open before any authenticated data is read.
    await cache.read(session.account ?? '', '__sync');
    final repository = StafferRepository(session, cache);
    final router = createRouter(session);
    final history = NavigationHistory(router);
    final notifications = NativeNotifications(repository, router);
    await notifications.initialize();
    runApp(
      ProviderScope(
        overrides: [
          repositoryProvider.overrideWith((ref) => repository),
          themeControllerProvider.overrideWith((ref) => theme),
          navigationHistoryProvider.overrideWith((ref) => history),
        ],
        child: StafferApp(router: router),
      ),
    );
    if (session.signedIn) await repository.start();
  } on Object {
    runApp(
      MaterialApp(
        theme: stafferTheme(),
        home: Scaffold(
          body: EmptyMessage(
            title: 'Personal Staffer could not start',
            message: 'Device initialization failed. Check the configured server address and access to the operating system secure storage, then restart Personal Staffer. Consult the setup guide if this continues.',
          ),
        ),
      ),
    );
  }
}
