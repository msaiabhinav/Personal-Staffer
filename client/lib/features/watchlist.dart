import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';
import 'shared.dart';

/// Priority employers the user watches. Entries are additional to the daily
/// quota and rotation but never bypass hard eligibility rules (PR-12).
class WatchlistPage extends ConsumerStatefulWidget {
  const WatchlistPage({super.key});
  @override
  ConsumerState<WatchlistPage> createState() => _WatchlistPageState();
}

class _WatchlistPageState extends ConsumerState<WatchlistPage> {
  final name = TextEditingController();
  bool busy = false;
  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  Future<void> add() async {
    final company = name.text.trim();
    if (company.isEmpty || busy) return;
    setState(() => busy = true);
    try {
      final repo = ref.read(repositoryProvider);
      await repo.session.request(
        'POST',
        '/watchlist',
        body: {'company_name': company},
      );
      name.clear();
      repo.changed();
      ref.invalidate(resourceProvider('/watchlist'));
      if (mounted) showMessage(context, 'Added $company to your watchlist.');
    } on ApiError catch (e) {
      if (mounted) showMessage(context, e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> remove(Json entry) async {
    try {
      final repo = ref.read(repositoryProvider);
      await repo.session.request('DELETE', '/watchlist/${entry['id']}');
      repo.changed();
      ref.invalidate(resourceProvider('/watchlist'));
      if (mounted) {
        showMessage(
          context,
          'Removed ${label(entry['company'])} from your watchlist.',
        );
      }
    } on ApiError catch (e) {
      if (mounted) showMessage(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: 'Watchlist',
          subtitle: 'Companies you want watched closely. New qualifying openings at these employers are delivered as priority alerts, in addition to the daily report.',
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: TextField(
                  controller: name,
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => add(),
                  decoration: const InputDecoration(
                    labelText: 'Add a company',
                    hintText: 'e.g. Thermo Fisher Scientific',
                    prefixIcon: Icon(Icons.add_business_outlined),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              FilledButton.icon(
                onPressed: busy ? null : add,
                icon: const Icon(Icons.add),
                label: Text(busy ? 'Adding…' : 'Add'),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
          child: Text(
            'Unverified names stay Pending until the employer identity is resolved. Watching a company never bypasses eligibility rules.',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
        Expanded(
          child: ResourceView(
            route: '/watchlist',
            builder: (data) {
              final items = objects(data['items']);
              if (items.isEmpty) {
                return const EmptyMessage(
                  icon: Icons.star_outline,
                  title: 'No companies watched yet',
                  message: 'Add the employers you care about most. Qualifying openings at watched companies are delivered as priority alerts.',
                );
              }
              return ListView.builder(
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                itemCount: items.length,
                itemBuilder: (context, index) {
                  final entry = items[index];
                  final registered = entry['resolution_state'] == 'REGISTERED';
                  return Card(
                    child: ListTile(
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 18,
                        vertical: 6,
                      ),
                      leading: CircleAvatar(
                        backgroundColor: theme.colorScheme.primaryContainer,
                        foregroundColor: theme.colorScheme.onPrimaryContainer,
                        child: Text(
                          label(
                            entry['company'],
                            '?',
                          ).trim().characters.first.toUpperCase(),
                        ),
                      ),
                      title: Text(
                        label(entry['company']),
                        style: theme.textTheme.titleMedium,
                      ),
                      subtitle: Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Wrap(
                          spacing: 8,
                          runSpacing: 4,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            StatusPill(
                              registered ? 'Registered' : 'Pending',
                              tone: registered
                                  ? PillTone.positive
                                  : PillTone.neutral,
                            ),
                            Text(
                              registered
                                  ? 'Employer identity verified · priority alerts active'
                                  : 'Awaiting employer identity resolution',
                              style: theme.textTheme.bodySmall,
                            ),
                          ],
                        ),
                      ),
                      trailing: IconButton(
                        tooltip: 'Remove from watchlist',
                        icon: const Icon(Icons.delete_outline),
                        onPressed: () => remove(entry),
                      ),
                    ),
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }
}
