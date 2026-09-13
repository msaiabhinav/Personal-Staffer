import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/api.dart';
import 'core/providers.dart';
import 'core/repository.dart';
import 'core/models.dart';
import 'core/history.dart';
import 'core/theme.dart';
import 'features/shared.dart';
import 'features/jobs.dart';
import 'features/applications.dart';
import 'features/inbox_people.dart';
import 'features/settings.dart';
import 'features/watchlist.dart';
import 'features/company.dart';

/// Primary destinations. The first five are the specification's fixed order;
/// Watchlist was added as a primary destination by product decision (ADR-0001).
final navLabels = [
  'Notifications',
  'Homepage',
  'People',
  'Saved Jobs',
  'Applied Jobs',
  'Watchlist',
];
final navPaths = [
  '/notifications',
  '/home',
  '/people',
  '/saved',
  '/applications',
  '/watchlist',
];
final navIcons = [
  Icons.notifications_none,
  Icons.home_outlined,
  Icons.people_outline,
  Icons.bookmark_outline,
  Icons.work_outline,
  Icons.star_outline,
];
final navSelectedIcons = [
  Icons.notifications,
  Icons.home,
  Icons.people,
  Icons.bookmark,
  Icons.work,
  Icons.star,
];
ThemeData stafferTheme() => stafferThemeFor(Brightness.light);

String _clock(DateTime at) {
  final local = at.toLocal();
  return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
}

/// Repository checkout that holds scripts/start_backend.ps1: an explicit build-time
/// define first, otherwise walk up from the executable (client/build/windows/...).
String? backendScript() {
  const configured = String.fromEnvironment('REPO_ROOT');
  final roots = <String>[if (configured.isNotEmpty) configured];
  var dir = File(Platform.resolvedExecutable).parent;
  for (var i = 0; i < 8; i++) {
    roots.add(dir.path);
    dir = dir.parent;
  }
  for (final root in roots) {
    final script = File(
      '$root${Platform.pathSeparator}scripts${Platform.pathSeparator}start_backend.ps1',
    );
    if (script.existsSync()) return script.path;
  }
  return null;
}

/// Runs scripts/start_backend.ps1 (repairs/starts Docker Desktop, `compose up -d`,
/// waits for the API). Never resets Docker or touches data.
Future<void> restartBackend(
  BuildContext context,
  StafferRepository repo,
) async {
  final script = backendScript();
  if (!Platform.isWindows || script == null) {
    showMessage(
      context,
      'Run scripts\\start_backend.ps1 from the Personal Staffer folder to restart the backend.',
    );
    return;
  }
  repo.setRestarting(true);
  try {
    final result = await Process.run('powershell.exe', [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      script,
      '-Mode',
      'live',
    ]).timeout(const Duration(minutes: 9));
    await repo.heartbeat();
    if (context.mounted) {
      showMessage(
        context,
        result.exitCode == 0
            ? 'Backend is running again.'
            : 'Backend did not come back (exit ${result.exitCode}). See %LOCALAPPDATA%\\PersonalStaffer\\start_backend.log.',
      );
    }
  } on Object catch (e) {
    if (context.mounted) showMessage(context, 'Restart failed: $e');
  } finally {
    repo.setRestarting(false);
    if (repo.backendDownSince == null) repo.sync();
  }
}

/// The owner's logo badge (assets/brand), the same artwork as the window icon.
class BrandMark extends StatelessWidget {
  const BrandMark({super.key, this.size = 40});
  final double size;
  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(size * 0.24),
    child: Image.asset(
      'assets/brand/app_icon_256.png',
      width: size,
      height: size,
      filterQuality: FilterQuality.medium,
      errorBuilder: (context, error, stack) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.primary,
          borderRadius: BorderRadius.circular(size * 0.24),
        ),
        child: Icon(
          Icons.auto_awesome,
          color: Theme.of(context).colorScheme.onPrimary,
        ),
      ),
    ),
  );
}

/// Header title for the current location. Primary destinations use their
/// sidebar label; secondary pages name themselves instead of borrowing the
/// nearest destination's label.
String shellTitle(String location) {
  final uri = Uri.parse(location);
  final path = uri.path;
  final index = navPaths.indexWhere((p) => path == p || path.startsWith('$p/'));
  if (index >= 0) return navLabels[index];
  if (path == '/settings') return 'Settings';
  if (path == '/collection') return uri.queryParameters['title'] ?? 'Records';
  if (path == '/company') return uri.queryParameters['name'] ?? 'Company';
  if (path.startsWith('/jobs/')) return 'Job';
  if (path.startsWith('/evidence/')) return 'Evidence';
  if (path.startsWith('/reports/')) return 'Daily report';
  if (path.startsWith('/reviews/')) return 'Review';
  if (path.startsWith('/search-runs/')) return 'Search run';
  return navLabels[1];
}

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
        GoRoute(
          path: '/home',
          builder: (_, state) =>
              HomePage(tab: state.uri.queryParameters['tab'] ?? 'feed'),
        ),
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
          builder: (_, state) => ApplicationsPage(
            initialStatus: state.uri.queryParameters['status'] ?? '',
            key: ValueKey(state.uri.queryParameters['status'] ?? ''),
          ),
        ),
        GoRoute(
          path: '/company',
          builder: (_, state) =>
              CompanyPage(name: state.uri.queryParameters['name'] ?? ''),
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
          path: '/watchlist',
          builder: (_, state) => const WatchlistPage(),
        ),
        GoRoute(
          path: '/watchlist/:id',
          builder: (_, state) =>
              WatchlistCompanyPage(id: state.pathParameters['id']!),
        ),
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

class StafferApp extends ConsumerWidget {
  const StafferApp({super.key, required this.router});
  final GoRouter router;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeControllerProvider).mode;
    return MaterialApp.router(
      title: 'Personal Staffer',
      debugShowCheckedModeBanner: false,
      theme: stafferThemeFor(Brightness.light),
      darkTheme: stafferThemeFor(Brightness.dark),
      themeMode: mode,
      routerConfig: router,
    );
  }
}

class ThemeToggleButton extends ConsumerWidget {
  const ThemeToggleButton({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.watch(themeControllerProvider);
    final dark = Theme.of(context).brightness == Brightness.dark;
    return IconButton(
      tooltip: dark ? 'Switch to light mode' : 'Switch to dark mode',
      onPressed: () => controller.set(dark ? ThemeMode.light : ThemeMode.dark),
      icon: Icon(dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined),
    );
  }
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
    final history = ref.watch(navigationHistoryProvider);
    Widget icon(int i, {bool selected = false}) {
      final glyph = Icon(selected ? navSelectedIcons[i] : navIcons[i]);
      return i == 0
          ? Badge(
              isLabelVisible: unread is int && unread > 0,
              label: Text(unread.toString()),
              child: glyph,
            )
          : glyph;
    }

    return LayoutBuilder(
      builder: (context, size) {
        final wide = size.maxWidth >= 1000;
        final actions = [
          if (repo.syncing)
            const Padding(
              padding: EdgeInsets.all(16),
              child: SizedBox(
                height: 18,
                width: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
          const ThemeToggleButton(),
          IconButton(
            tooltip: 'Settings',
            onPressed: () => context.push('/settings'),
            icon: const Icon(Icons.settings_outlined),
          ),
          const SizedBox(width: 12),
        ];
        final content = Column(
          children: [
            if (wide)
              // Header spans only the content column so the sidebar runs full height.
              SizedBox(
                height: 64,
                child: Row(
                  children: [
                    HistoryButtons(history: history),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        shellTitle(location),
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    ...actions,
                  ],
                ),
              ),
            if (const bool.fromEnvironment('DEMO_MODE'))
              const StatusStrip(
                'DEMO · Synthetic local records',
                icon: Icons.science_outlined,
              ),
            if (repo.offline || repo.operations.isNotEmpty)
              StatusStrip(
                '${repo.offline ? 'Offline · ' : ''}${repo.operations.length} pending change${repo.operations.length == 1 ? '' : 's'}',
                icon: repo.offline ? Icons.cloud_off_outlined : Icons.sync,
                action: TextButton(
                  onPressed: () => context.push('/settings'),
                  child: const Text('Review'),
                ),
              ),
            Expanded(child: child),
          ],
        );
        final shell = Scaffold(
          appBar: wide
              ? null
              : AppBar(
                  leadingWidth: 104,
                  leading: HistoryButtons(history: history),
                  title: const Text('Personal Staffer'),
                  actions: actions,
                ),
          body: SafeArea(
            child: Row(
              children: [
                if (wide)
                  Sidebar(
                    selected: selected,
                    unread: unread is int ? unread : 0,
                    onSelect: (i) => context.go(navPaths[i]),
                  ),
                Expanded(
                  child: Material(
                    color: Theme.of(context).scaffoldBackgroundColor,
                    child: content,
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
                    navLabels.length,
                    (i) => NavigationDestination(
                      icon: icon(i),
                      selectedIcon: icon(i, selected: true),
                      label: navLabels[i],
                    ),
                  ),
                ),
        );
        if (history == null) return shell;
        return CallbackShortcuts(
          bindings: {
            const SingleActivator(LogicalKeyboardKey.arrowLeft, alt: true):
                history.back,
            const SingleActivator(LogicalKeyboardKey.arrowRight, alt: true):
                history.forward,
          },
          child: Focus(autofocus: true, child: shell),
        );
      },
    );
  }
}

/// Browser-style Back / Forward controls, always visible in the shell.
class HistoryButtons extends StatelessWidget {
  const HistoryButtons({super.key, required this.history});
  final NavigationHistory? history;
  @override
  Widget build(BuildContext context) {
    final h = history;
    return Padding(
      padding: const EdgeInsets.only(left: 8),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: 'Back (Alt+Left)',
            icon: const Icon(Icons.arrow_back),
            onPressed: h != null && h.canGoBack ? h.back : null,
          ),
          IconButton(
            tooltip: 'Forward (Alt+Right)',
            icon: const Icon(Icons.arrow_forward),
            onPressed: h != null && h.canGoForward ? h.forward : null,
          ),
        ],
      ),
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
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context);
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              scheme.primary.withValues(alpha: 0.10),
              theme.scaffoldBackgroundColor,
              scheme.primary.withValues(alpha: 0.05),
            ],
          ),
        ),
        child: SafeArea(
          child: Stack(
            children: [
              const Positioned(top: 8, right: 8, child: ThemeToggleButton()),
              Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(24),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 520),
                    child: Card(
                      margin: EdgeInsets.zero,
                      child: Padding(
                        padding: const EdgeInsets.all(36),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const BrandMark(size: 56),
                                const SizedBox(width: 16),
                                Flexible(
                                  child: Text(
                                    'Personal Staffer',
                                    style: theme.textTheme.headlineSmall,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 24),
                            Text(
                              'Your opportunities and application history, together on Windows and Android.',
                              style: theme.textTheme.bodyLarge,
                            ),
                            const SizedBox(height: 8),
                            Text(
                              'Sign in with the Google account configured for your private server. No resume is required.',
                              style: theme.textTheme.bodyMedium?.copyWith(
                                color: scheme.onSurfaceVariant,
                              ),
                            ),
                            if (error != null) ...[
                              const SizedBox(height: 16),
                              Container(
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: scheme.tertiary.withValues(
                                    alpha: 0.12,
                                  ),
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                child: Row(
                                  children: [
                                    Icon(
                                      Icons.info_outline,
                                      size: 18,
                                      color: scheme.tertiary,
                                    ),
                                    const SizedBox(width: 10),
                                    Expanded(child: Text(error!)),
                                  ],
                                ),
                              ),
                            ],
                            const SizedBox(height: 28),
                            SizedBox(
                              width: double.infinity,
                              child: FilledButton.icon(
                                onPressed: busy ? null : login,
                                icon: const Icon(Icons.login),
                                label: Text(
                                  busy
                                      ? 'Finish sign-in in your browser…'
                                      : 'Continue with Google',
                                ),
                              ),
                            ),
                            if (const bool.fromEnvironment('DEMO_MODE')) ...[
                              const SizedBox(height: 10),
                              SizedBox(
                                width: double.infinity,
                                child: OutlinedButton.icon(
                                  onPressed: busy
                                      ? null
                                      : () async {
                                          final repository = ref.read(
                                            repositoryProvider,
                                          );
                                          try {
                                            await repository.session
                                                .startDemo();
                                            await repository.start();
                                          } on ApiError catch (e) {
                                            if (mounted) {
                                              setState(() => error = e.message);
                                            }
                                          }
                                        },
                                  icon: const Icon(Icons.science_outlined),
                                  label: const Text('Open local demo'),
                                ),
                              ),
                            ],
                            const SizedBox(height: 20),
                            SelectableText(
                              'Server: ${ref.read(repositoryProvider).session.origin}',
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: scheme.onSurfaceVariant,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Wide-layout navigation: a navy sidebar in both appearance modes so the
/// destinations, brand and account state read as one anchored surface.
class Sidebar extends ConsumerWidget {
  const Sidebar({
    super.key,
    required this.selected,
    required this.unread,
    required this.onSelect,
  });
  final int selected;
  final int unread;
  final ValueChanged<int> onSelect;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.colors;
    final scheme = Theme.of(context).colorScheme;
    final repo = ref.watch(repositoryProvider);
    // The sidebar is the logo badge in both modes, so the gold accent works on it directly.
    final accent = scheme.primary;
    return Container(
      width: 248,
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [colors.sidebar, colors.sidebarLow],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 22, 20, 18),
            child: Row(
              children: [
                const BrandMark(size: 40),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Personal Staffer',
                        style: Theme.of(context).textTheme.titleMedium
                            ?.copyWith(color: colors.onSidebar),
                      ),
                      Text(
                        const bool.fromEnvironment('DEMO_MODE')
                            ? 'Synthetic demo'
                            : 'Private workspace',
                        style: Theme.of(context).textTheme.labelSmall
                            ?.copyWith(color: colors.onSidebarMuted),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 8),
            child: Text(
              'WORKSPACE',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: colors.onSidebarMuted,
                letterSpacing: 1.2,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          for (var i = 0; i < navLabels.length; i++)
            SidebarItem(
              icon: i == selected ? navSelectedIcons[i] : navIcons[i],
              label: navLabels[i],
              selected: i == selected,
              badge: i == 0 && unread > 0 ? unread : null,
              accent: accent,
              onTap: () => onSelect(i),
            ),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.06),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
              ),
              child: Row(
                children: [
                  Container(
                    width: 10,
                    height: 10,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: repo.backendDownSince != null
                          ? colors.coral
                          : repo.offline
                          ? colors.amber
                          : repo.syncing
                          ? colors.blue
                          : colors.green,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Tooltip(
                      message: repo.backendDownSince != null
                          ? 'The local Personal Staffer service (Docker) is not answering. '
                                'Your internet is not the problem. Restart it with the button.'
                          : '',
                      child: Text(
                        repo.backendDownSince != null
                            ? 'Backend offline since ${_clock(repo.backendDownSince!)}'
                            : repo.offline
                            ? 'Offline \u00b7 cached records'
                            : repo.syncing
                            ? 'Synchronizing\u2026'
                            : 'Connected',
                        style: Theme.of(context).textTheme.bodySmall
                            ?.copyWith(color: colors.onSidebar),
                      ),
                    ),
                  ),
                  if (repo.backendDownSince != null)
                    IconButton(
                      tooltip: repo.restartingBackend
                          ? 'Restarting the backend\u2026'
                          : 'Restart backend',
                      visualDensity: VisualDensity.compact,
                      onPressed: repo.restartingBackend
                          ? null
                          : () => restartBackend(context, repo),
                      icon: repo.restartingBackend
                          ? SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: colors.onSidebar,
                              ),
                            )
                          : Icon(
                              Icons.restart_alt,
                              size: 20,
                              color: colors.coral,
                            ),
                    ),
                  IconButton(
                    tooltip: 'Settings',
                    visualDensity: VisualDensity.compact,
                    onPressed: () => context.push('/settings'),
                    icon: Icon(
                      Icons.settings_outlined,
                      size: 20,
                      color: colors.onSidebarMuted,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class SidebarItem extends StatelessWidget {
  const SidebarItem({
    super.key,
    required this.icon,
    required this.label,
    required this.selected,
    required this.onTap,
    required this.accent,
    this.badge,
  });
  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;
  final Color accent;
  final int? badge;
  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final foreground = selected ? Colors.white : colors.onSidebarMuted;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
      child: Material(
        color: selected
            ? Colors.white.withValues(alpha: 0.10)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          hoverColor: Colors.white.withValues(alpha: 0.06),
          onTap: onTap,
          child: Container(
            height: 44,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(
              children: [
                Container(
                  width: 3,
                  height: 20,
                  decoration: BoxDecoration(
                    color: selected ? accent : Colors.transparent,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                const SizedBox(width: 12),
                Icon(icon, size: 21, color: selected ? accent : foreground),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    label,
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      color: foreground,
                      fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                    ),
                  ),
                ),
                if (badge != null)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: accent,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      '$badge',
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
