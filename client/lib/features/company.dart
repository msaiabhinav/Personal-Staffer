import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';
import '../core/theme.dart';
import 'dashboard.dart';
import 'shared.dart';

/// Search box that opens a company page. Suggestions come from everything the
/// owner already tracks (applications, employer email, watchlist, postings).
class CompanySearch extends ConsumerStatefulWidget {
  const CompanySearch({super.key, this.compact = false});
  final bool compact;
  @override
  ConsumerState<CompanySearch> createState() => _CompanySearchState();
}

class _CompanySearchState extends ConsumerState<CompanySearch> {
  final controller = TextEditingController();
  List<Json> results = const [];
  bool busy = false;
  String lastQuery = '';

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> search(String text) async {
    final query = text.trim();
    lastQuery = query;
    if (query.length < 2) {
      setState(() => results = const []);
      return;
    }
    setState(() => busy = true);
    try {
      final data = await ref
          .read(repositoryProvider)
          .session
          .request('GET', '/companies?q=${Uri.encodeQueryComponent(query)}');
      if (!mounted || lastQuery != query) return;
      setState(() => results = objects(data['items']));
    } on ApiError catch (e) {
      if (mounted) showMessage(context, e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void open(String name) {
    controller.clear();
    setState(() => results = const []);
    context.push('/company?name=${Uri.encodeQueryComponent(name)}');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: widget.compact ? 320 : double.infinity,
          child: TextField(
            controller: controller,
            onChanged: search,
            onSubmitted: (v) {
              if (results.isNotEmpty) {
                open(label(results.first['name']));
              } else if (v.trim().isNotEmpty) {
                open(v.trim());
              }
            },
            decoration: InputDecoration(
              isDense: true,
              hintText: 'Search a company: status, emails and threads',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: busy
                  ? const Padding(
                      padding: EdgeInsets.all(10),
                      child: SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    )
                  : null,
            ),
          ),
        ),
        if (results.isNotEmpty)
          Container(
            margin: const EdgeInsets.only(top: 6),
            constraints: const BoxConstraints(maxHeight: 280),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHigh,
              borderRadius: BorderRadius.circular(12),
            ),
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final row in results)
                  ListTile(
                    dense: true,
                    leading: CircleAvatar(
                      radius: 14,
                      backgroundColor: context.colors.tint(
                        hueFor(context, label(row['name'])),
                        theme.brightness,
                      ),
                      foregroundColor: hueFor(context, label(row['name'])),
                      child: Text(
                        label(
                          row['name'],
                          '?',
                        ).trim().characters.first.toUpperCase(),
                        style: const TextStyle(fontSize: 12),
                      ),
                    ),
                    title: Text(label(row['name'])),
                    subtitle: Text(
                      '${row['applications']} application(s) · ${row['emails']} email(s)'
                      '${row['watched'] == true ? ' · watched' : ''}'
                      '${(row['postings'] ?? 0) > 0 ? ' · ${row['postings']} open posting(s)' : ''}',
                    ),
                    onTap: () => open(label(row['name'])),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

/// One company: status of every application, the employer's emails grouped
/// by thread, and what the scanners currently see.
class CompanyPage extends ConsumerWidget {
  const CompanyPage({super.key, required this.name});
  final String name;
  @override
  Widget build(BuildContext context, WidgetRef ref) => ResourceView(
    route: '/companies/view?name=${Uri.encodeQueryComponent(name)}',
    builder: (data) {
      final theme = Theme.of(context);
      final summary = object(data['summary']);
      final apps = objects(data['applications']);
      final threads = objects(data['threads']);
      final postings = object(data['postings']);
      final watch = object(data['watchlist']);
      final latest = label(summary['latest_status'], '');
      return LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 1000;
          final applicationsPanel = _ApplicationsPanel(apps: apps);
          final threadsPanel = _ThreadsPanel(threads: threads);
          return ListView(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 32),
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  CircleAvatar(
                    radius: 26,
                    backgroundColor: context.colors.tint(
                      hueFor(context, label(data['name'])),
                      theme.brightness,
                    ),
                    foregroundColor: hueFor(context, label(data['name'])),
                    child: Text(
                      label(
                        data['name'],
                        '?',
                      ).trim().characters.first.toUpperCase(),
                      style: theme.textTheme.titleLarge,
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          label(data['name']),
                          style: theme.textTheme.headlineSmall,
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            if (latest.isNotEmpty)
                              StatusPill(
                                statusName(latest),
                                icon: statusIcon(latest),
                                hue: statusHue(context, latest),
                              ),
                            StatusPill(
                              '${summary['applications'] ?? 0} application(s)',
                              icon: Icons.work_outline,
                              tone: PillTone.info,
                            ),
                            StatusPill(
                              '${summary['emails'] ?? 0} email(s) in ${summary['threads'] ?? 0} thread(s)',
                              icon: Icons.mail_outline,
                              tone: PillTone.violet,
                            ),
                            if ((summary['open_reviews'] ?? 0) > 0)
                              StatusPill(
                                '${summary['open_reviews']} awaiting your decision',
                                icon: Icons.rate_review_outlined,
                                tone: PillTone.warning,
                              ),
                            if (summary['watched'] == true)
                              const StatusPill(
                                'Watched',
                                icon: Icons.star,
                                tone: PillTone.positive,
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              _PostingsStrip(postings: postings, watch: watch),
              const SizedBox(height: 16),
              if (wide)
                IntrinsicHeight(
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(flex: 2, child: applicationsPanel),
                      const SizedBox(width: 16),
                      Expanded(flex: 3, child: threadsPanel),
                    ],
                  ),
                )
              else ...[
                applicationsPanel,
                const SizedBox(height: 16),
                threadsPanel,
              ],
            ],
          );
        },
      );
    },
  );
}

class _PostingsStrip extends StatelessWidget {
  const _PostingsStrip({required this.postings, required this.watch});
  final Json postings, watch;
  @override
  Widget build(BuildContext context) {
    final sources = (postings['sources'] ?? 0) as num;
    final open = (postings['open'] ?? 0) as num;
    final relevant = (postings['relevant'] ?? 0) as num;
    final groupId = postings['employer_group_id'];
    final text = sources == 0
        ? (watch.isEmpty
              ? 'Not on your watchlist and no career site is scanned for this company.'
              : 'On your watchlist, but no career site is registered, so postings are not collected.')
        : '$sources career site(s) scanned · $open open posting(s) · $relevant relevant to your profile.';
    return StatusStrip(
      text,
      action: groupId == null || sources == 0
          ? null
          : TextButton(
              onPressed: () => watch['id'] != null
                  ? context.push('/watchlist/${watch['id']}')
                  : context.go('/watchlist'),
              child: const Text('See postings'),
            ),
    );
  }
}

class _ApplicationsPanel extends StatelessWidget {
  const _ApplicationsPanel({required this.apps});
  final List<Json> apps;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Applications', style: theme.textTheme.titleMedium),
            const SizedBox(height: 12),
            if (apps.isEmpty)
              Text(
                'No application recorded at this company. Emails below may still describe one; add it from Applied Jobs if so.',
                style: theme.textTheme.bodySmall,
              ),
            for (final app in apps) ...[
              InkWell(
                borderRadius: BorderRadius.circular(10),
                onTap: () => context.push('/applications/${app['id']}'),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              label(app['title']),
                              style: theme.textTheme.titleSmall,
                            ),
                          ),
                          StatusPill(
                            statusName(
                              label(
                                app['display_status'] ?? app['current_status'],
                                '',
                              ),
                            ),
                            hue: statusHue(
                              context,
                              label(
                                app['display_status'] ?? app['current_status'],
                                '',
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'Applied ${dateLabel(app['applied_at'])}',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: 6),
                      for (final event in objects(app['events']))
                        Padding(
                          padding: const EdgeInsets.only(left: 8, top: 4),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(
                                statusIcon(label(event['status'], '')),
                                size: 16,
                                color: statusHue(
                                  context,
                                  label(event['status'], ''),
                                ),
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  '${statusName(label(event['status'], ''))} · ${dateLabel(event['effective_at'])}'
                                  '${event['actor'] == 'EMAIL' ? ' · from email' : ''}'
                                  '${event['reason'] != null ? '\n${event['reason']}' : ''}',
                                  style: theme.textTheme.bodySmall,
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              if (app != apps.last) const Divider(height: 16),
            ],
          ],
        ),
      ),
    );
  }
}

class _ThreadsPanel extends StatelessWidget {
  const _ThreadsPanel({required this.threads});
  final List<Json> threads;

  PillTone _tone(String kind) => switch (kind) {
    'Rejected' || 'Position closed' => PillTone.danger,
    'Interview' || 'Assessment' || 'Offer' => PillTone.violet,
    'Application confirmed' => PillTone.positive,
    'Information requested' || 'Status update' => PillTone.warning,
    _ => PillTone.neutral,
  };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Emails and threads', style: theme.textTheme.titleMedium),
            Text(
              'Newest thread first · each message shows how the parser read it',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 10),
            if (threads.isEmpty)
              Text(
                'No email from or about this company in the synced window.',
                style: theme.textTheme.bodySmall,
              ),
            for (final thread in threads)
              Theme(
                data: theme.copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: const EdgeInsets.only(left: 12, bottom: 8),
                  initiallyExpanded: thread == threads.first,
                  title: Text(
                    label(thread['subject']),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      StatusPill(
                        label(thread['latest_kind']),
                        tone: _tone(label(thread['latest_kind'], '')),
                      ),
                      Text(
                        '${objects(thread['messages']).length} message(s) · ${dateLabel(thread['last_at'])}',
                        style: theme.textTheme.bodySmall,
                      ),
                    ],
                  ),
                  children: [
                    for (final m in objects(thread['messages']))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 6),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Wrap(
                              spacing: 8,
                              runSpacing: 4,
                              crossAxisAlignment: WrapCrossAlignment.center,
                              children: [
                                StatusPill(
                                  label(m['kind']),
                                  tone: _tone(label(m['kind'], '')),
                                ),
                                if (m['linked_application_id'] != null)
                                  const StatusPill(
                                    'Linked to application',
                                    icon: Icons.link,
                                    tone: PillTone.info,
                                  ),
                                if (m['open_review_id'] != null)
                                  StatusPill(
                                    'Needs your decision',
                                    icon: Icons.rate_review_outlined,
                                    tone: PillTone.warning,
                                  ),
                                Text(
                                  dateLabel(m['received_at']),
                                  style: theme.textTheme.bodySmall,
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'From ${label(m['sender'])}',
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                            ),
                            Text(
                              label(m['subject']),
                              style: theme.textTheme.bodyMedium?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            Text(
                              label(m['excerpt'], ''),
                              maxLines: 6,
                              overflow: TextOverflow.ellipsis,
                            ),
                            if (m['open_review_id'] != null)
                              TextButton(
                                onPressed: () => context.push(
                                  '/reviews/${m['open_review_id']}',
                                ),
                                child: const Text('Open review'),
                              ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
