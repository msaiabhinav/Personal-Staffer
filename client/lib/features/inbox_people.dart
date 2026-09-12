import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';
import 'shared.dart';

class NotificationsPage extends ConsumerStatefulWidget {
  const NotificationsPage({super.key});
  @override
  ConsumerState<NotificationsPage> createState() => _NotificationsState();
}

class _NotificationsState extends ConsumerState<NotificationsPage> {
  bool unread = false;
  @override
  Widget build(BuildContext context) => Column(
    children: [
      PageHeader(
        title: 'Notifications',
        subtitle:
            'Every alert opens its exact job, application, report or review.',
        trailing: FilterChip(
          label: const Text('Unread only'),
          selected: unread,
          onSelected: (v) => setState(() => unread = v),
        ),
      ),
      Expanded(
        child: ResourceView(
          route: '/notifications${unread ? '?unread_only=true' : ''}',
          builder: (data) {
            final items = objects(data['items']);
            if (items.isEmpty) {
              return const EmptyMessage(
                icon: Icons.notifications_none,
                title: 'You’re caught up',
                message: 'Job alerts, application updates and reports will appear here. Every alert opens its specific record.',
              );
            }
            return ListView.builder(
              padding: const EdgeInsets.fromLTRB(24, 4, 24, 24),
              itemCount: items.length,
              itemBuilder: (context, index) {
                final n = items[index];
                final isUnread = n['read_at'] == null;
                final scheme = Theme.of(context).colorScheme;
                return Card(
                  clipBehavior: Clip.antiAlias,
                  child: ListTile(
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 18,
                      vertical: 8,
                    ),
                    leading: CircleAvatar(
                      backgroundColor: isUnread
                          ? scheme.primaryContainer
                          : scheme.surfaceContainerHigh,
                      foregroundColor: isUnread
                          ? scheme.onPrimaryContainer
                          : scheme.onSurfaceVariant,
                      child: Icon(
                        isUnread
                            ? Icons.mark_email_unread_outlined
                            : Icons.drafts_outlined,
                      ),
                    ),
                    title: Text(
                      label(n['title']),
                      style: TextStyle(
                        fontWeight: isUnread
                            ? FontWeight.w600
                            : FontWeight.normal,
                      ),
                    ),
                    subtitle: Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        '${label(n['body'], '')}\n${dateLabel(n['created_at'])}',
                      ),
                    ),
                    isThreeLine: true,
                    onTap: () => context.push('/notifications/${n['id']}'),
                    trailing: IconButton(
                      tooltip: n['read_at'] == null
                          ? 'Mark read'
                          : 'Mark unread',
                      icon: Icon(
                        n['read_at'] == null
                            ? Icons.done
                            : Icons.mark_email_unread_outlined,
                      ),
                      onPressed: () async {
                        try {
                          final repo = ref.read(repositoryProvider);
                          await repo.session.request(
                            'PUT',
                            '/notifications/${n['id']}/read',
                            body: {'read': n['read_at'] == null},
                          );
                          repo.changed();
                        } on ApiError catch (e) {
                          if (context.mounted) showMessage(context, e.message);
                        }
                      },
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

class NotificationOpen extends ConsumerStatefulWidget {
  const NotificationOpen({super.key, required this.id});
  final String id;
  @override
  ConsumerState<NotificationOpen> createState() => _NotificationOpenState();
}

class _NotificationOpenState extends ConsumerState<NotificationOpen> {
  String? error;
  @override
  void initState() {
    super.initState();
    Future.microtask(open);
  }

  Future<void> open() async {
    try {
      final repo = ref.read(repositoryProvider);
      final n = await repo.session.request(
        'POST',
        '/notifications/${widget.id}/open',
        body: {},
      );
      final target = internalDestination(n['destination']);
      if (target == null) {
        throw ApiError(
          'INVALID_DESTINATION',
          'This alert has an unsupported destination. The inbox record has been retained.',
        );
      }
      repo.changed();
      if (mounted) context.replace(target);
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) => error == null
      ? const LoadingRows()
      : EmptyMessage(
          title: 'Could not open this notification',
          message: error!,
          action: TextButton(onPressed: open, child: const Text('Retry')),
        );
}

class PeoplePage extends StatefulWidget {
  const PeoplePage({super.key, this.job});
  final String? job;
  @override
  State<PeoplePage> createState() => _PeoplePageState();
}

class _PeoplePageState extends State<PeoplePage> {
  String query = '';
  @override
  Widget build(BuildContext context) => ResourceView(
    route: widget.job == null ? '/people' : '/jobs/${widget.job}/people',
    builder: (data) {
      final groups = widget.job == null ? objects(data['items']) : [data];
      if (groups.isEmpty) {
        return const EmptyMessage(
          title: 'People connected to your opportunities',
          message: 'Relevant public profiles appear here when evidence supports a connection to a job. People discovery does not delay job delivery.',
        );
      }
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text('People', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 12),
          TextField(
            decoration: const InputDecoration(
              labelText: 'Filter job, company or person',
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: (value) => setState(() => query = value.toLowerCase()),
          ),
          ...groups
              .where(
                (g) =>
                    query.isEmpty || g.toString().toLowerCase().contains(query),
              )
              .map((group) {
                final people = objects(group['people'] ?? group['items'])
                    .take(10)
                    .toList();
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 20),
                    Text(
                      label(
                        group['title'] ?? group['job_title'],
                        'Job connections',
                      ),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    Text(label(group['company'], '')),
                    const SizedBox(height: 8),
                    Text('Discovery: ${friendly(group['state'])}'),
                    if (people.isEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Text(
                          'No supported profiles are available for this job yet.',
                        ),
                      ),
                    ...people.map(
                      (person) => Padding(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              label(person['name']),
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            Text(
                              '${label(person['role'] ?? person['title'] ?? person['headline'])} · ${label(person['company'])}',
                            ),
                            const SizedBox(height: 8),
                            Text(
                              '${friendly(person['group'] ?? person['relationship_group'])} · ${friendly(person['evidence_label'] ?? person['classification'])}',
                            ),
                            Text(
                              label(
                                person['explanation'] ??
                                    person['relationship_explanation'] ??
                                    person['evidence'],
                              ),
                            ),
                            Text(
                              'Evidence checked ${dateLabel(person['checked_at'])}',
                            ),
                            TextButton.icon(
                              onPressed: () => openExternal(
                                context,
                                person['linkedin_url'] ?? person['url'],
                              ),
                              icon: const Icon(Icons.open_in_new),
                              label: const Text('Open LinkedIn Profile'),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                );
              }),
        ],
      );
    },
  );
}

class EvidencePage extends StatelessWidget {
  const EvidencePage({super.key, required this.id});
  final String id;
  @override
  Widget build(BuildContext context) => DetailPage(
    title: 'Job evidence',
    child: ResourceView(
      route: '/jobs/$id/evidence',
      builder: (data) => ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Text(
            'Decisions are tied to the retained evidence below. “Not stated” is different from confirmed availability.',
          ),
          const SizedBox(height: 20),
          ...objects(data['items'])
              .expand(
                (evaluation) => objects(evaluation['rules']).map(
                  (rule) => {
                    ...rule,
                    'evaluated_at': evaluation['evaluated_at'],
                    'ruleset_version': evaluation['ruleset_version'],
                  },
                ),
              )
              .map(
                (row) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label(row['rule_code'] ?? row['rule']),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    Field('Decision', row['decision']),
                    Field('Reason', row['reason_code'] ?? row['reason']),
                    Field('Evidence', row['evidence'] ?? row['evidence_refs']),
                    Field('Rule version', row['rule_version']),
                    const Divider(height: 32),
                  ],
                ),
              ),
        ],
      ),
    ),
  );
}

/// Contextual records retain exact identity for reports, reviews and search runs.
class ContextRecordPage extends ConsumerStatefulWidget {
  const ContextRecordPage({super.key, required this.type, required this.id});
  final String type, id;
  @override
  ConsumerState<ContextRecordPage> createState() => _ContextRecordState();
}

class _ContextRecordState extends ConsumerState<ContextRecordPage> {
  final resolution = TextEditingController();
  final application = TextEditingController();
  String action = 'DISMISS';
  bool busy = false;
  @override
  void dispose() {
    resolution.dispose();
    application.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => DetailPage(
    title: widget.type == 'reports'
        ? 'Daily Search Report'
        : widget.type == 'reviews'
        ? 'Review this update'
        : 'Search run',
    child: ResourceView(
      route: '/${widget.type}/${widget.id}',
      builder: (data) => ListView(
        padding: const EdgeInsets.all(24),
        children: [
          ...data.entries
              .where((e) => !{'items', 'jobs', '_cached', 'id'}.contains(e.key))
              .map((e) => Field(friendly(e.key), e.value)),
          ...objects(data['jobs'] ?? data['items']).map(
            (job) => ListTile(
              title: Text(label(job['title'] ?? job['job_id'])),
              subtitle: Text(label(job['company'], '')),
              onTap: job['job_id'] == null && job['id'] == null
                  ? null
                  : () => context.push('/jobs/${job['job_id'] ?? job['id']}'),
            ),
          ),
          if (widget.type == 'reviews') ...[
            const Divider(height: 32),
            const Text(
              'Check the source evidence before linking or dismissing this update.',
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: action,
              items: const [
                DropdownMenuItem(
                  value: 'DISMISS',
                  child: Text('Dismiss suggestion'),
                ),
                DropdownMenuItem(
                  value: 'LINK',
                  child: Text('Link to an application'),
                ),
              ],
              onChanged: (v) => setState(() => action = v!),
            ),
            if (action == 'LINK')
              SizedBox(
                height: 260,
                child: ResourceView(
                  route: '/applications',
                  builder: (page) => ListView(
                    children: objects(page['items'])
                        .map(
                          (app) => ListTile(
                            title: Text(
                              '${label(app['company'])} · ${label(app['title'])}',
                            ),
                            subtitle: Text(
                              'Applied ${dateLabel(app['applied_at'])}',
                            ),
                            selected: application.text == app['id'],
                            trailing: application.text == app['id']
                                ? const Icon(Icons.check)
                                : null,
                            onTap: () =>
                                setState(() => application.text = app['id']),
                          ),
                        )
                        .toList(),
                  ),
                ),
              ),
            TextField(
              controller: resolution,
              decoration: const InputDecoration(labelText: 'Reason'),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: busy
                  ? null
                  : () async {
                      if (action == 'LINK' && application.text.isEmpty) {
                        showMessage(
                          context,
                          'Choose the application that matches this email.',
                        );
                        return;
                      }
                      if (resolution.text.trim().isEmpty) {
                        showMessage(
                          context,
                          'Add a reason for your resolution.',
                        );
                        return;
                      }
                      setState(() => busy = true);
                      try {
                        final linked = action == 'LINK'
                            ? await ref
                                  .read(repositoryProvider)
                                  .get(
                                    '/applications/${application.text.trim()}',
                                  )
                            : <String, dynamic>{};
                        await ref
                            .read(repositoryProvider)
                            .session
                            .request(
                              'POST',
                              '/reviews/${widget.id}/resolve',
                              body: {
                                'action': action,
                                'expected_revision': data['revision'],
                                if (action == 'LINK')
                                  'application_revision': linked['revision'],
                                'reason': resolution.text.trim(),
                                if (action == 'LINK')
                                  'application_id': application.text.trim(),
                              },
                            );
                        ref.read(repositoryProvider).changed();
                        if (context.mounted) {
                          showMessage(context, 'Review resolution saved.');
                        }
                      } on ApiError catch (e) {
                        if (context.mounted) showMessage(context, e.message);
                      } finally {
                        if (mounted) setState(() => busy = false);
                      }
                    },
              child: const Text('Save resolution'),
            ),
          ],
        ],
      ),
    ),
  );
}
