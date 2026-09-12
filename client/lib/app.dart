import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/api.dart';
import 'core/providers.dart';
import 'core/models.dart';
import 'features/shared.dart';
import 'features/jobs.dart';
import 'features/applications.dart';
import 'features/inbox_people.dart';
import 'features/settings.dart';

final navLabels = [
  'Notifications',
  'Homepage',
  'People',
  'Saved Jobs',
  'Applied Jobs',
];
final navPaths = [
  '/notifications',
  '/home',
  '/people',
  '/saved',
  '/applications',
];
final navIcons = [
  Icons.notifications_none,
  Icons.home_outlined,
  Icons.people_outline,
  Icons.bookmark_outline,
  Icons.work_outline,
];
ThemeData stafferTheme() => ThemeData(
  useMaterial3: true,
  colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff087f8c))
      .copyWith(
        primary: const Color(0xff087f8c),
        onPrimary: Colors.white,
        surface: Colors.white,
        onSurface: const Color(0xff172b4d),
        onSurfaceVariant: const Color(0xff526175),
        outline: const Color(0xffd8e0e8),
      ),
  scaffoldBackgroundColor: const Color(0xfff5f7fa),
  appBarTheme: const AppBarTheme(
    backgroundColor: Color(0xfff5f7fa),
    foregroundColor: Color(0xff172b4d),
  ),
  inputDecorationTheme: const InputDecorationTheme(
    border: OutlineInputBorder(),
    contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 16),
  ),
  filledButtonTheme: FilledButtonThemeData(
    style: FilledButton.styleFrom(minimumSize: const Size(48, 48)),
  ),
  outlinedButtonTheme: OutlinedButtonThemeData(
    style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
  ),
  textButtonTheme: TextButtonThemeData(
    style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
  ),
  visualDensity: VisualDensity.standard,
);

GoRouter createRouter(Session session, {String initial = '/home'}) => GoRouter(
  initialLocation: initial,
  refreshListenable: session,
  redirect: (context, state) {
    if (!session.signedIn && state.matchedLocation != '/login') {
      return '/login?next=${Uri.encodeComponent(state.uri.toString())}';
    }
    if (session.signedIn && state.matchedLocation == '/login') {
      final next = state.uri.queryParameters['next'];
      return next != null &&
              (internalDestination(next) != null ||
                  navPaths.contains(next) ||
                  next == '/settings')
          ? next
          : '/home';
    }
    return null;
  },
  routes: [
    GoRoute(path: '/login', builder: (context, state) => const LoginPage()),
    ShellRoute(
      builder: (context, state, child) =>
          AppShell(location: state.uri.path, child: child),
      routes: [
        GoRoute(path: '/home', builder: (_, state) => const HomePage()),
        GoRoute(
          path: '/notifications',
          builder: (_, state) => const NotificationsPage(),
        ),
        GoRoute(
          path: '/notifications/:id',
          builder: (_, state) =>
              NotificationOpen(id: state.pathParameters['id']!),
        ),
        GoRoute(
          path: '/people',
          builder: (_, state) =>
              PeoplePage(job: state.uri.queryParameters['job']),
        ),
        GoRoute(
          path: '/saved',
          builder: (_, state) => const JobsPage(saved: true),
        ),
        GoRoute(
          path: '/jobs/:id',
          builder: (_, state) => JobDetail(id: state.pathParameters['id']!),
        ),
        GoRoute(
          path: '/evidence/:id',
          builder: (_, state) => EvidencePage(id: state.pathParameters['id']!),
        ),
        GoRoute(
          path: '/applications',
          builder: (_, state) => const ApplicationsPage(),
        ),
        GoRoute(
          path: '/applications/new',
          builder: (_, state) => const AddApplicationPage(),
        ),
        GoRoute(
          path: '/applications/:id',
          builder: (_, state) =>
              ApplicationDetail(id: state.pathParameters['id']!),
        ),
        for (final type in ['reports', 'reviews', 'search-runs'])
          GoRoute(
            path: '/$type/:id',
            builder: (_, state) =>
                ContextRecordPage(type: type, id: state.pathParameters['id']!),
          ),
        GoRoute(path: '/settings', builder: (_, state) => const SettingsPage()),
        GoRoute(
          path: '/collection',
          builder: (_, state) => CollectionPage(
            route: state.uri.queryParameters['route'] ?? '/reports',
            title: state.uri.queryParameters['title'] ?? 'Records',
          ),
        ),
      ],
    ),
  ],
  errorBuilder: (context, state) => Scaffold(
    body: EmptyMessage(
      title: 'This destination is unavailable',
      message: 'Return to your saved records or open the notification again.',
      action: TextButton(
        onPressed: () => context.go('/home'),
        child: const Text('Open Homepage'),
      ),
    ),
  ),
);

class StafferApp extends StatelessWidget {
  const StafferApp({super.key, required this.router});
  final GoRouter router;
  @override
  Widget build(BuildContext context) => MaterialApp.router(
    title: 'Personal Staffer',
    debugShowCheckedModeBanner: false,
    theme: stafferTheme(),
    routerConfig: router,
  );
}

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.location, required this.child});
  final String location;
  final Widget child;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.watch(repositoryProvider);
    int selected = navPaths.indexWhere(
      (path) => location == path || location.startsWith('$path/'),
    );
    if (selected < 0) selected = 1;
    final unread =
        ref
            .watch(resourceProvider('/notifications/unread-count'))
            .asData
            ?.value['unread_count'] ??
        0;
    Widget icon(int i) => i == 0
        ? Badge(
            isLabelVisible: unread is int && unread > 0,
            label: Text(unread.toString()),
            child: Icon(navIcons[i]),
          )
        : Icon(navIcons[i]);
    return LayoutBuilder(
      builder: (context, size) {
        final wide = size.maxWidth >= 1000;
        return Scaffold(
          appBar: AppBar(
            title: const Text('Personal Staffer'),
            actions: [
              if (repo.syncing)
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
              IconButton(
                tooltip: 'Settings',
                onPressed: () => context.push('/settings'),
                icon: const Icon(Icons.settings_outlined),
              ),
              const SizedBox(width: 12),
            ],
          ),
          body: SafeArea(
            child: Row(
              children: [
                if (wide) ...[
                  NavigationRail(
                    extended: true,
                    selectedIndex: selected,
                    onDestinationSelected: (i) => context.go(navPaths[i]),
                    destinations: List.generate(
                      5,
                      (i) => NavigationRailDestination(
                        icon: icon(i),
                        label: Text(navLabels[i]),
                      ),
                    ),
                  ),
                  const VerticalDivider(width: 1),
                ],
                Expanded(
                  child: Column(
                    children: [
                      if (const bool.fromEnvironment('DEMO_MODE'))
                        const StatusStrip(
                          'DEMO · Synthetic local records',
                          icon: Icons.science_outlined,
                        ),
                      if (repo.offline || repo.operations.isNotEmpty)
                        StatusStrip(
                          '${repo.offline ? 'Offline · ' : ''}${repo.operations.length} pending change${repo.operations.length == 1 ? '' : 's'}',
                          icon: repo.offline
                              ? Icons.cloud_off_outlined
                              : Icons.sync,
                          action: TextButton(
                            onPressed: () => context.push('/settings'),
                            child: const Text('Review'),
                          ),
                        ),
                      Expanded(child: child),
                    ],
                  ),
                ),
              ],
            ),
          ),
          bottomNavigationBar: wide
              ? null
              : NavigationBar(
                  selectedIndex: selected,
                  onDestinationSelected: (i) => context.go(navPaths[i]),
                  labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
                  destinations: List.generate(
                    5,
                    (i) => NavigationDestination(
                      icon: icon(i),
                      label: navLabels[i],
                    ),
                  ),
                ),
        );
      },
    );
  }
}

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});
  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  Timer? poll;
  bool busy = false;
  String? error;
  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  Future<void> login() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final repository = ref.read(repositoryProvider);
      final session = repository.session;
      await session.startLogin();
      int attempts = 0;
      poll = Timer.periodic(const Duration(seconds: 2), (timer) async {
        attempts++;
        if (attempts > 150) {
          timer.cancel();
          if (mounted) {
            setState(() {
              busy = false;
              error = 'Sign-in timed out. Please start again.';
            });
          }
          return;
        }
        try {
          if (await session.finishLogin()) {
            timer.cancel();
            await repository.start();
          }
        } on ApiError catch (e) {
          timer.cancel();
          if (mounted) {
            setState(() {
              busy = false;
              error = e.message;
            });
          }
        }
      });
    } on ApiError catch (e) {
      if (mounted) {
        setState(() {
          busy = false;
          error = e.message;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: EmptyMessage(
        title: 'Personal Staffer',
        message:
            'Your opportunities and application history, together on Windows and Android. Sign in with the Google account configured for your private server.\n\nNo resume is required.${error == null ? '' : '\n\n$error'}',
        action: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            FilledButton.icon(
              onPressed: busy ? null : login,
              icon: const Icon(Icons.login),
              label: Text(
                busy
                    ? 'Finish sign-in in your browser…'
                    : 'Continue with Google',
              ),
            ),
            if (const bool.fromEnvironment('DEMO_MODE'))
              TextButton(
                onPressed: busy
                    ? null
                    : () async {
                        final repository = ref.read(repositoryProvider);
                        try {
                          await repository.session.startDemo();
                          await repository.start();
                        } on ApiError catch (e) {
                          if (mounted) setState(() => error = e.message);
                        }
                      },
                child: const Text('Open local demo'),
              ),
            const SizedBox(height: 16),
            SelectableText(
              'Server: ${ref.read(repositoryProvider).session.origin}',
            ),
          ],
        ),
      ),
    ),
  );
}
