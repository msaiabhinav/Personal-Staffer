import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';
import '../core/theme.dart';
import 'shared.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.watch(repositoryProvider);
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text('Settings', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 16),
        Text('Appearance', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        const AppearanceSelector(),
        const Divider(height: 32),
        Text('Server: ${repo.session.origin}'),
        const SizedBox(height: 12),
        Text('Device notifications: ${friendly(repo.notificationState)}'),
        if (repo.notificationState == 'NOT_CONFIGURED')
          const Text(
            'Push delivery is not configured for this build. Updates remain available in Notifications.',
          ),
        if (repo.notificationState == 'PERMISSION_DENIED')
          const Text(
            'Allow notifications in Android system settings to receive alerts.',
          ),
        if (repo.notificationState == 'READY_WHILE_RUNNING')
          const Text(
            'Windows alerts are checked while Personal Staffer is running.',
          ),
        if (Platform.isWindows) const DesktopPreferences(),
        const SizedBox(height: 8),
        Text(
          repo.syncing
              ? 'Synchronizing…'
              : repo.offline
              ? 'Offline · cached data'
              : 'Connected',
        ),
        if (repo.syncMessage != null) Text(repo.syncMessage!),
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: repo.syncing ? null : repo.sync,
            icon: const Icon(Icons.sync),
            label: const Text('Sync now'),
          ),
        ),
        const Divider(height: 32),
        Text(
          'Pending changes (${repo.operations.length})',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        if (repo.operations.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: Text('All local changes have been acknowledged.'),
          ),
        ...repo.operations.map(
          (op) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${friendly(op.command)} · ${friendly(op.state)}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text(dateLabel(op.createdAt.toIso8601String())),
                if (op.error != null) Text(op.error!),
                Wrap(
                  spacing: 12,
                  children: [
                    TextButton(
                      onPressed: () => context.push(
                        '/${{'correction', 'notes', 'status'}.contains(op.command) ? 'applications' : 'jobs'}/${op.target}',
                      ),
                      child: const Text('Review current record'),
                    ),
                    if (op.state == 'conflict')
                      TextButton(
                        onPressed: () => repo.discard(op),
                        child: const Text('Discard conflicting change'),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
        const Divider(height: 32),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.star_outline),
          title: const Text('Watchlist'),
          subtitle: const Text(
            'Priority employers, now in the main navigation',
          ),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => context.go('/watchlist'),
        ),
        ...[
          ('Search profile', '/profile'),
          ('Daily Search Reports', '/reports'),
          ('Previously Shown Companies', '/reports/companies'),
          ('Source health', '/connectors/health'),
          ('Search run history', '/search-runs'),
          ('Gmail connection', '/gmail/status'),
          ('Connected devices', '/devices'),
          ('Review ambiguous updates', '/reviews'),
        ].map(
          (entry) => ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(entry.$1),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push(
              '/collection?route=${Uri.encodeComponent(entry.$2)}&title=${Uri.encodeComponent(entry.$1)}',
            ),
          ),
        ),
        const Divider(height: 32),
        TextButton(
          onPressed: () async {
            if (repo.operations.isNotEmpty) {
              final leave = await showDialog<bool>(
                context: context,
                builder: (context) => AlertDialog(
                  title: const Text('Sign out with pending changes?'),
                  content: const Text(
                    'Signing out clears this device’s cached records and unsent changes. Server records are retained.',
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Keep working'),
                    ),
                    FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Sign out'),
                    ),
                  ],
                ),
              );
              if (leave != true) return;
            }
            await repo.signOut();
          },
          child: const Text('Sign out'),
        ),
      ],
    );
  }
}

class CollectionPage extends ConsumerWidget {
  const CollectionPage({super.key, required this.route, required this.title});
  final String route, title;
  @override
  Widget build(BuildContext context, WidgetRef ref) => DetailPage(
    title: title,
    child: ResourceView(
      route: route,
      builder: (data) {
        final items = objects(data['items']);
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            ...data.entries
                .where(
                  (e) => !{
                    'items',
                    'next_cursor',
                    'has_more',
                    '_cached',
                  }.contains(e.key),
                )
                .map((e) => Field(friendly(e.key), e.value)),
            if (route == '/gmail/status')
              Wrap(
                spacing: 12,
                children: [
                  FilledButton(
                    onPressed: () async {
                      try {
                        final j = await ref
                            .read(repositoryProvider)
                            .session
                            .startGmail();
                        if (context.mounted) {
                          await openExternal(context, j['authorization_url']);
                        }
                      } on ApiError catch (e) {
                        if (context.mounted) showMessage(context, e.message);
                      }
                    },
                    child: const Text('Connect / reconnect Gmail'),
                  ),
                  TextButton(
                    onPressed: () async {
                      try {
                        await ref
                            .read(repositoryProvider)
                            .session
                            .request('DELETE', '/gmail/connection');
                        ref.read(repositoryProvider).changed();
                        if (context.mounted) {
                          showMessage(
                            context,
                            'Gmail disconnected. Application history is retained.',
                          );
                        }
                      } on ApiError catch (e) {
                        if (context.mounted) showMessage(context, e.message);
                      }
                    },
                    child: const Text('Disconnect Gmail'),
                  ),
                  OutlinedButton(
                    onPressed: () async {
                      try {
                        await ref
                            .read(repositoryProvider)
                            .session
                            .request('POST', '/gmail/sync', body: {});
                        if (context.mounted) {
                          showMessage(context, 'Gmail synchronization queued.');
                        }
                      } on ApiError catch (e) {
                        if (context.mounted) showMessage(context, e.message);
                      }
                    },
                    child: const Text('Sync Gmail'),
                  ),
                ],
              ),
            if (route == '/profile') const ProfileEditor(),
            if (route == '/watchlist') const WatchlistEditor(),
            if (items.isEmpty &&
                data.keys.every(
                  (k) => {
                    'items',
                    'next_cursor',
                    'has_more',
                    '_cached',
                  }.contains(k),
                ))
              const Text('No records are available yet.'),
            ...items.map(
              (item) => Padding(
                padding: const EdgeInsets.only(bottom: 20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ...item.entries
                        .where((e) => e.key != 'id')
                        .map((e) => Field(friendly(e.key), e.value)),
                    if (item['id'] != null &&
                        {
                          '/reports',
                          '/search-runs',
                          '/reviews',
                        }.contains(route))
                      TextButton(
                        onPressed: () => context.push('$route/${item['id']}'),
                        child: const Text('Open details'),
                      ),
                    if (route == '/watchlist')
                      TextButton(
                        onPressed: () async {
                          try {
                            await ref
                                .read(repositoryProvider)
                                .session
                                .request('DELETE', '/watchlist/${item['id']}');
                            ref.invalidate(resourceProvider(route));
                          } on ApiError catch (e) {
                            if (context.mounted) {
                              showMessage(context, e.message);
                            }
                          }
                        },
                        child: const Text('Remove from watchlist'),
                      ),
                    if (route == '/devices')
                      TextButton(
                        onPressed: () async {
                          try {
                            await ref
                                .read(repositoryProvider)
                                .session
                                .request('DELETE', '/devices/${item['id']}');
                            ref.invalidate(resourceProvider(route));
                          } on ApiError catch (e) {
                            if (context.mounted) {
                              showMessage(context, e.message);
                            }
                          }
                        },
                        child: const Text('Revoke this device'),
                      ),
                    const Divider(),
                  ],
                ),
              ),
            ),
            if (data['has_more'] == true)
              TextButton(
                onPressed: () => context.push(
                  '/collection?route=${Uri.encodeComponent('$route${route.contains('?') ? '&' : '?'}cursor=${data['next_cursor']}')}&title=${Uri.encodeComponent(title)}',
                ),
                child: const Text('Next page'),
              ),
          ],
        );
      },
    ),
  );
}

class ProfileEditor extends ConsumerStatefulWidget {
  const ProfileEditor({super.key});
  @override
  ConsumerState<ProfileEditor> createState() => _ProfileEditorState();
}

class _ProfileEditorState extends ConsumerState<ProfileEditor> {
  final titles = TextEditingController(), skills = TextEditingController();
  bool busy = false;
  @override
  void dispose() {
    titles.dispose();
    skills.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const SizedBox(height: 16),
      const Text(
        'Customize role titles and skills. Discovery hard rules remain enforced.',
      ),
      const SizedBox(height: 12),
      TextField(
        controller: titles,
        decoration: const InputDecoration(
          labelText: 'Role families, separated by commas',
        ),
      ),
      const SizedBox(height: 12),
      TextField(
        controller: skills,
        decoration: const InputDecoration(
          labelText: 'Skills, separated by commas',
        ),
      ),
      const SizedBox(height: 12),
      OutlinedButton(
        onPressed: busy
            ? null
            : () async {
                setState(() => busy = true);
                try {
                  final repo = ref.read(repositoryProvider);
                  final profile = await repo.get('/profile');
                  await repo.session.request(
                    'PATCH',
                    '/profile',
                    body: {
                      'expected_revision':
                          profile['revision'] ?? profile['version'],
                      if (titles.text.trim().isNotEmpty)
                        'role_families': titles.text
                            .split(',')
                            .map((v) => v.trim())
                            .where((v) => v.isNotEmpty)
                            .toList(),
                      if (skills.text.trim().isNotEmpty)
                        'skills': skills.text
                            .split(',')
                            .map((v) => v.trim())
                            .where((v) => v.isNotEmpty)
                            .toList(),
                    },
                  );
                  repo.changed();
                  if (context.mounted) {
                    showMessage(context, 'Search profile updated.');
                  }
                } on ApiError catch (e) {
                  if (context.mounted) showMessage(context, e.message);
                } finally {
                  if (mounted) setState(() => busy = false);
                }
              },
        child: const Text('Update profile'),
      ),
      const SizedBox(height: 24),
    ],
  );
}

class AppearanceSelector extends ConsumerWidget {
  const AppearanceSelector({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.watch(themeControllerProvider);
    return Align(
      alignment: Alignment.centerLeft,
      child: SegmentedButton<ThemeMode>(
        segments: const [
          ButtonSegment(
            value: ThemeMode.system,
            label: Text('System'),
            icon: Icon(Icons.brightness_auto_outlined),
          ),
          ButtonSegment(
            value: ThemeMode.light,
            label: Text('Light'),
            icon: Icon(Icons.light_mode_outlined),
          ),
          ButtonSegment(
            value: ThemeMode.dark,
            label: Text('Dark'),
            icon: Icon(Icons.dark_mode_outlined),
          ),
        ],
        selected: {controller.mode},
        onSelectionChanged: (selection) => controller.set(selection.first),
      ),
    );
  }
}

class DesktopPreferences extends StatefulWidget {
  const DesktopPreferences({super.key});
  @override
  State<DesktopPreferences> createState() => _DesktopPreferencesState();
}

class _DesktopPreferencesState extends State<DesktopPreferences> {
  static const channel = MethodChannel('personalstaffer/desktop');
  bool tray = false, startup = false, ready = false;
  String? error;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final result = object(await channel.invokeMethod('preferences'));
      if (mounted) {
        setState(() {
          tray = result['tray'] == true;
          startup = result['startup'] == true;
          ready = true;
        });
      }
    } on PlatformException catch (e) {
      if (mounted) setState(() => error = e.message);
    } on MissingPluginException {
      if (mounted) {
        setState(
          () => error = 'Desktop preferences are unavailable in this build.',
        );
      }
    }
  }

  Future<void> change(bool newTray, bool newStartup) async {
    try {
      await channel.invokeMethod('configure', {
        'tray': newTray,
        'startup': newStartup,
      });
      if (mounted) {
        setState(() {
          tray = newTray;
          startup = newStartup;
        });
      }
    } on PlatformException catch (e) {
      if (mounted) setState(() => error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    children: [
      const Divider(height: 32),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Keep notifications running when window closes'),
        subtitle: const Text(
          'Keep Personal Staffer in the system tray. Use its menu to exit.',
        ),
        value: tray,
        onChanged: ready ? (v) => change(v, startup) : null,
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Open Personal Staffer when I sign in to Windows'),
        subtitle: const Text(
          'Start quietly in the tray when background notifications are enabled.',
        ),
        value: startup,
        onChanged: ready ? (v) => change(tray, v) : null,
      ),
      if (error != null) Text(error!),
    ],
  );
}

class WatchlistEditor extends ConsumerStatefulWidget {
  const WatchlistEditor({super.key});
  @override
  ConsumerState<WatchlistEditor> createState() => _WatchlistEditorState();
}

class _WatchlistEditorState extends ConsumerState<WatchlistEditor> {
  final name = TextEditingController();
  bool busy = false;
  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const SizedBox(height: 16),
      TextField(
        controller: name,
        decoration: const InputDecoration(labelText: 'Company to watch'),
      ),
      const SizedBox(height: 8),
      const Text(
        'Unresolved company names remain Pending until their identity is verified. Priority monitoring never bypasses eligibility rules.',
      ),
      const SizedBox(height: 12),
      OutlinedButton(
        onPressed: busy
            ? null
            : () async {
                if (name.text.trim().isEmpty) return;
                setState(() => busy = true);
                try {
                  await ref
                      .read(repositoryProvider)
                      .session
                      .request(
                        'POST',
                        '/watchlist',
                        body: {'company_name': name.text.trim()},
                      );
                  ref.read(repositoryProvider).changed();
                  name.clear();
                  if (context.mounted) {
                    showMessage(context, 'Watchlist request recorded.');
                  }
                } on ApiError catch (e) {
                  if (context.mounted) showMessage(context, e.message);
                } finally {
                  if (mounted) setState(() => busy = false);
                }
              },
        child: const Text('Add company'),
      ),
      const SizedBox(height: 24),
    ],
  );
}
