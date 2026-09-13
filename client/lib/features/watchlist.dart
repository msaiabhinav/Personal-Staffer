import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';
import '../core/theme.dart';
import 'jobs.dart';
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
                        backgroundColor: context.colors.tint(
                          hueFor(context, label(entry['company'])),
                          theme.brightness,
                        ),
                        foregroundColor: hueFor(
                          context,
                          label(entry['company']),
                        ),
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
                              icon: registered
                                  ? Icons.verified_outlined
                                  : Icons.hourglass_empty,
                              tone: registered
                                  ? PillTone.positive
                                  : PillTone.warning,
                            ),
                            // Counts come from the live API; the offline snapshot omits them.
                            if (registered && entry['source_count'] == 0)
                              const StatusPill(
                                'No career site registered',
                                icon: Icons.link_off,
                                tone: PillTone.neutral,
                              ),
                            if (registered && (entry['source_count'] ?? 0) > 0)
                              StatusPill(
                                '${label(entry['open_postings'], '0')} open posting(s)',
                                icon: Icons.work_outline,
                                tone: PillTone.info,
                              ),
                            Text(
                              registered
                                  ? 'Priority alerts active · tap to see postings'
                                  : 'Awaiting employer identity resolution',
                              style: theme.textTheme.bodySmall,
                            ),
                          ],
                        ),
                      ),
                      onTap: () => context.push('/watchlist/${entry['id']}'),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            tooltip: 'Remove from watchlist',
                            icon: const Icon(Icons.delete_outline),
                            onPressed: () => remove(entry),
                          ),
                          const Icon(Icons.chevron_right),
                        ],
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

/// One watched employer: which career sites are scanned for it and every open
/// posting those sites collected, with the delivered/withheld verdict on each.
class WatchlistCompanyPage extends ConsumerWidget {
  const WatchlistCompanyPage({super.key, required this.id});
  final String id;
  @override
  Widget build(BuildContext context, WidgetRef ref) => ResourceView(
    route: '/watchlist/$id',
    builder: (entry) {
      final theme = Theme.of(context);
      final sources = objects(entry['sources']);
      final groupId = entry['employer_group_id'];
      final registered = entry['resolution_state'] == 'REGISTERED';
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          PageHeader(
            title: label(entry['company']),
            subtitle: registered
                ? '${label(entry['open_postings'], '0')} open posting(s) collected · ${label(object(entry['breakdown'])['relevant'], '0')} in your role families · ${label(object(entry['breakdown'])['qualifying'], '0')} pass every rule · ${label(entry['delivered'], '0')} delivered'
                : 'Awaiting employer identity resolution; no career site can be scanned yet.',
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (sources.isEmpty)
                  const StatusPill(
                    'No career site registered for this company',
                    icon: Icons.link_off,
                    tone: PillTone.warning,
                  ),
                for (final source in sources)
                  StatusPill(
                    '${friendly(source['connector_type'])} · ${friendly(source['configuration_state'])}'
                    '${source['last_success'] != null ? ' · last scan ${dateLabel(source['last_success'])}' : ''}',
                    icon: Icons.travel_explore_outlined,
                    tone: source['configuration_state'] == 'HEALTHY'
                        ? PillTone.positive
                        : PillTone.warning,
                  ),
              ],
            ),
          ),
          if (sources.isEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 4, 24, 8),
              child: Text(
                'Jobs appear here once a career-site source for this employer is registered and scanned. Watching alone does not fetch postings.',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ),
          Expanded(
            child: groupId == null
                ? const EmptyMessage(
                    icon: Icons.hourglass_empty,
                    title: 'Identity still pending',
                    message: 'Postings are listed once the employer is resolved to a registered identity.',
                  )
                : ResourceView(
                    route:
                        '/jobs?scope=scanned&qualifying_only=true&employer_group_id=$groupId&limit=25',
                    builder: (data) {
                      final rows = objects(data['items']);
                      if (rows.isEmpty) {
                        final b = object(entry['breakdown']);
                        final reasons = objects(b['withheld_reasons'])
                            .map(
                              (r) => '${friendly(r['reason'])} (${r['count']})',
                            )
                            .join(', ');
                        return EmptyMessage(
                          icon: Icons.work_outline,
                          title:
                              'No posting passes your search rules right now',
                          message: sources.isEmpty
                              ? 'Register a career-site source for this employer to start collecting its postings.'
                              : '${label(b['open'], '0')} open posting(s) collected · ${label(b['relevant'], '0')} match your role families · none passes every rule.'
                                    '${reasons.isEmpty ? '' : '\nWithheld for: $reasons.'}',
                        );
                      }
                      return ListView.builder(
                        padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                        itemCount: rows.length,
                        itemBuilder: (context, index) => JobRow(
                          job: rows[index],
                          showDecision: true,
                          onOpen: () =>
                              context.push('/jobs/${rows[index]['id']}'),
                        ),
                      );
                    },
                  ),
          ),
        ],
      );
    },
  );
}
