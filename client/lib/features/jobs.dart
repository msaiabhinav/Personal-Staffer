import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';
import 'shared.dart';
import 'applications.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});
  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 2,
    child: Column(
      children: [
        const TabBar(
          tabs: [
            Tab(text: 'Job Feed'),
            Tab(text: 'Application Dashboard'),
          ],
        ),
        const Expanded(
          child: TabBarView(children: [JobsPage(), DashboardPage()]),
        ),
      ],
    ),
  );
}

class JobsPage extends ConsumerStatefulWidget {
  const JobsPage({super.key, this.saved = false});
  final bool saved;
  @override
  ConsumerState<JobsPage> createState() => _JobsPageState();
}

class _JobsPageState extends ConsumerState<JobsPage> {
  String scope = 'today', hours = '72', keyword = '', arrangement = '';
  String? selected;
  @override
  Widget build(BuildContext context) {
    final query = Uri(
      queryParameters: {
        'scope': scope,
        if (scope != 'history') 'posted_within_hours': hours,
        if (keyword.isNotEmpty) 'keyword': keyword,
        if (arrangement.isNotEmpty) 'work_arrangement': arrangement,
      },
    ).query;
    final route = widget.saved ? '/saved-jobs' : '/jobs?$query';
    final list = Column(
      children: [
        if (!widget.saved)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Wrap(
              spacing: 12,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                SizedBox(
                  width: 280,
                  child: DropdownButton<String>(
                    isExpanded: true,
                    value: scope,
                    items: const [
                      DropdownMenuItem(
                        value: 'today',
                        child: Text('Today’s report'),
                      ),
                      DropdownMenuItem(
                        value: 'priority',
                        child: Text('Additional priority jobs'),
                      ),
                      DropdownMenuItem(
                        value: 'history',
                        child: Text('Previously delivered'),
                      ),
                    ],
                    onChanged: (v) => setState(() => scope = v!),
                  ),
                ),
                SizedBox(
                  width: 200,
                  child: DropdownButton<String>(
                    isExpanded: true,
                    value: hours,
                    items: ['24', '48', '72']
                        .map(
                          (h) => DropdownMenuItem(
                            value: h,
                            child: Text('Within $h hours'),
                          ),
                        )
                        .toList(),
                    onChanged: (v) => setState(() => hours = v!),
                  ),
                ),
                SizedBox(
                  width: 220,
                  child: DropdownButton<String>(
                    isExpanded: true,
                    value: arrangement,
                    items: const [
                      DropdownMenuItem(
                        value: '',
                        child: Text('All arrangements'),
                      ),
                      DropdownMenuItem(value: 'REMOTE', child: Text('Remote')),
                      DropdownMenuItem(value: 'HYBRID', child: Text('Hybrid')),
                      DropdownMenuItem(value: 'ONSITE', child: Text('Onsite')),
                    ],
                    onChanged: (v) => setState(() => arrangement = v!),
                  ),
                ),
                SizedBox(
                  width: 240,
                  child: TextField(
                    decoration: const InputDecoration(
                      labelText: 'Search title or company',
                      prefixIcon: Icon(Icons.search),
                    ),
                    onSubmitted: (v) => setState(() => keyword = v),
                  ),
                ),
              ],
            ),
          ),
        if (!widget.saved && scope == 'today') const ReportSummary(),
        Expanded(
          child: ResourceView(
            route: route,
            builder: (data) {
              final rows = objects(data['items']);
              if (rows.isEmpty) {
                return EmptyMessage(
                  title: widget.saved
                      ? 'Keep an opportunity for later'
                      : scope == 'priority'
                      ? 'No new priority opportunities'
                      : 'No qualifying jobs delivered yet',
                  message: widget.saved
                      ? 'Save a job from the feed. It stays here until you unsave it or record your application.'
                      : 'Only jobs with complete qualifying evidence appear here. Review source health and the search report for coverage.',
                  action: widget.saved
                      ? null
                      : TextButton(
                          onPressed: () => context.push('/settings'),
                          child: const Text('Open source health'),
                        ),
                );
              }
              return ListView.builder(
                key: PageStorageKey(route),
                padding: const EdgeInsets.all(16),
                itemCount: rows.length,
                itemBuilder: (context, index) {
                  return JobRow(
                    job: rows[index],
                    onOpen: () {
                      if (MediaQuery.sizeOf(context).width >= 1200) {
                        setState(() => selected = rows[index]['id']);
                      } else {
                        context.push('/jobs/${rows[index]['id']}');
                      }
                    },
                  );
                },
              );
            },
          ),
        ),
      ],
    );
    if (MediaQuery.sizeOf(context).width >= 1200 && selected != null) {
      return Row(
        children: [
          Expanded(flex: 4, child: list),
          const VerticalDivider(width: 1),
          Expanded(
            flex: 5,
            child: JobDetail(
              id: selected!,
              embedded: true,
              key: ValueKey(selected),
            ),
          ),
        ],
      );
    }
    return list;
  }
}

class ReportSummary extends ConsumerWidget {
  const ReportSummary({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => ref
      .watch(resourceProvider('/reports/today'))
      .when(
        data: (report) {
          final status = label(report['status'], 'Not released');
          return StatusStrip(
            '${label(report['report_date'], 'Today')} · ${label(report['job_count'] ?? report['count'] ?? objects(report['jobs']).length, '0')} jobs · ${friendly(status)}${report['actual_release'] == null ? '' : ' · ${dateLabel(report['actual_release'])}'}',
            action: report['id'] == null
                ? null
                : TextButton(
                    onPressed: () => context.push('/reports/${report['id']}'),
                    child: const Text('View report'),
                  ),
          );
        },
        loading: () => const LinearProgressIndicator(),
        error: (e, s) => const StatusStrip(
          'The daily report has not been released or is unavailable. Check source health.',
        ),
      );
}

class JobRow extends ConsumerWidget {
  const JobRow({super.key, required this.job, required this.onOpen});
  final Json job;
  final VoidCallback onOpen;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fields = object(object(job['snapshot'])['structured_fields']);
    final state = object(job['state']);
    final pending = ref.watch(repositoryProvider).pendingFor(job['id']);
    return Column(
      children: [
        InkWell(
          onTap: onOpen,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 18, horizontal: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                        label(job['title']),
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                    if (pending) const Chip(label: Text('Pending')),
                    if (state['is_saved'] == true)
                      const Tooltip(
                        message: 'Saved',
                        child: Icon(Icons.bookmark),
                      ),
                  ],
                ),
                const SizedBox(height: 5),
                Text(
                  label(job['company']),
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
                const SizedBox(height: 8),
                Text(
                  '${job['locations'] is List ? (job['locations'] as List).join(' · ') : label(job['locations'])} · ${friendly(job['work_arrangement'])}',
                ),
                const SizedBox(height: 6),
                Text('Published ${publicationLabel(job)}'),
                if (fields['salary'] != null)
                  Text('Salary: ${salaryLabel(fields['salary'])}'),
                if (fields['experience'] != null)
                  Text('Experience: ${fields['experience']}'),
                if (state['saved_at'] != null)
                  Text('Saved ${dateLabel(state['saved_at'])}'),
                if (job['availability'] != 'ACTIVE')
                  Text(
                    'Posting ${friendly(job['availability'])} · retained record',
                  ),
                if (fields['summary'] != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      label(fields['summary']),
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
            ),
          ),
        ),
        const Divider(height: 1),
      ],
    );
  }
}

class JobDetail extends ConsumerStatefulWidget {
  const JobDetail({super.key, required this.id, this.embedded = false});
  final String id;
  final bool embedded;
  @override
  ConsumerState<JobDetail> createState() => _JobDetailState();
}

class _JobDetailState extends ConsumerState<JobDetail> {
  bool busy = false;
  bool recordingView = true;
  int? viewedRevision;
  @override
  void initState() {
    super.initState();
    final session = ref.read(repositoryProvider).session;
    final id = widget.id;
    Future.microtask(() async {
      try {
        final result = await session.request(
          'POST',
          '/jobs/$id/view',
          body: {},
        );
        if (mounted) viewedRevision = (result['revision'] as num?)?.toInt();
      } on ApiError {
        // Viewing cached history must remain possible when offline.
      } finally {
        if (mounted) setState(() => recordingView = false);
      }
    });
  }

  Future<void> action(String command, Json payload) async {
    setState(() => busy = true);
    try {
      final repo = ref.read(repositoryProvider);
      final result = await repo.command(command, widget.id, payload);
      if (!mounted) return;
      if (result['pending'] == true) {
        showMessage(context, 'Pending · Your change will sync when connected.');
      } else if (result['conflict'] == true) {
        showMessage(
          context,
          'This change needs review. Open Pending changes in Settings.',
        );
      } else if (command == 'apply') {
        showMessage(
          context,
          result['can_undo'] == true
              ? 'Application recorded.'
              : 'Application is already recorded.',
          undo: result['can_undo'] == true && result['event_id'] != null
              ? () {
                  repo
                      .command('correction', result['application_id'], {
                        'event_id': result['event_id'],
                        'expected_revision':
                            result['application_revision'] ?? 1,
                        'reason': 'Accidentally marked applied',
                        'action': 'UNDO_APPLIED',
                      })
                      .then((result) {
                        if (mounted && result['conflict'] == true) {
                          showMessage(
                            context,
                            'Newer activity prevents Undo. Review the application timeline.',
                          );
                        }
                      });
                }
              : null,
        );
      } else {
        showMessage(context, 'Change saved.');
      }
    } on ApiError catch (e) {
      if (mounted) showMessage(context, e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final body = ResourceView(
      route: '/jobs/${widget.id}',
      builder: (job) {
        final snapshot = object(job['snapshot']);
        final fields = object(snapshot['structured_fields']);
        final state = object(job['state']);
        final sources = objects(job['sources']);
        final pending = ref.watch(repositoryProvider).pendingFor(widget.id);
        final serverRevision = (state['revision'] as num?)?.toInt() ?? 0;
        // The first view increments server state. A concurrent detail GET can
        // arrive with the preceding revision; use the acknowledged view state.
        final expectedRevision = (viewedRevision ?? 0) > serverRevision
            ? viewedRevision!
            : serverRevision;
        final disabled = busy || pending || recordingView;
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Text(
              label(job['title']),
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              label(job['company']),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton.icon(
                  icon: const Icon(Icons.open_in_new),
                  label: const Text('Open Job Posting / Apply Now'),
                  onPressed: busy
                      ? null
                      : () async {
                          try {
                            final result = await ref
                                .read(repositoryProvider)
                                .session
                                .request(
                                  'POST',
                                  '/jobs/${widget.id}/application-open',
                                  body: {},
                                );
                            if (context.mounted) {
                              await openExternal(
                                context,
                                result['url'] ?? result['application_url'],
                              );
                            }
                          } on ApiError catch (e) {
                            if (context.mounted) {
                              showMessage(context, e.message);
                              if (e.retryable && sources.isNotEmpty) {
                                await openExternal(
                                  context,
                                  sources.first['application_url'] ??
                                      sources.first['source_url'],
                                );
                              }
                            }
                          }
                        },
                ),
                OutlinedButton.icon(
                  icon: Icon(
                    state['is_saved'] == true
                        ? Icons.bookmark
                        : Icons.bookmark_border,
                  ),
                  label: Text(state['is_saved'] == true ? 'Unsave' : 'Save'),
                  onPressed: disabled || job['application_id'] != null
                      ? null
                      : () => action('save', {
                          'saved': state['is_saved'] != true,
                          'expected_revision': expectedRevision,
                        }),
                ),
                OutlinedButton(
                  onPressed: disabled || job['application_id'] != null
                      ? null
                      : () => action('apply', {
                          'expected_revision': expectedRevision,
                        }),
                  child: const Text('Mark Applied'),
                ),
                TextButton(
                  onPressed: disabled
                      ? null
                      : () => action('dismiss', {
                          'dismissed': true,
                          'expected_revision': expectedRevision,
                        }),
                  child: const Text('Not Interested'),
                ),
                TextButton(
                  onPressed: () => context.push('/people?job=${widget.id}'),
                  child: const Text('People'),
                ),
                if (job['application_id'] != null)
                  TextButton(
                    onPressed: () =>
                        context.push('/applications/${job['application_id']}'),
                    child: const Text('View application'),
                  ),
              ],
            ),
            if (pending)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  'Pending · This action has not been confirmed by the server.',
                ),
              ),
            const SizedBox(height: 24),
            Field(
              'Location',
              job['locations'] is List
                  ? (job['locations'] as List).join(' · ')
                  : job['locations'],
            ),
            Field('Work arrangement', friendly(job['work_arrangement'])),
            Field('Published', publicationLabel(job)),
            Field('First discovered', dateLabel(job['first_seen'])),
            Field('Employment type', fields['employment_type']),
            Field(
              'Required experience as published',
              fields['experience'] ?? fields['experience_text'],
            ),
            Field('Salary as published', salaryLabel(fields['salary'])),
            Field('Matched skills', fields['matched_skills']),
            Field('Requested skills not found', fields['missing_skills']),
            Field('Why this matches', fields['match_reason']),
            const SizedBox(height: 12),
            Text(
              'Eligibility evidence',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            ...objects(object(job['eligibility'])['rules']).map(
              (rule) => Field(
                '${label(rule['rule'] ?? rule['rule_code'])} · ${friendly(rule['decision'])}',
                rule['message'] ??
                    rule['reason'] ??
                    friendly(rule['reason_code']),
              ),
            ),
            TextButton(
              onPressed: () => context.push('/evidence/${widget.id}'),
              child: const Text('Inspect all evidence and source dates'),
            ),
            const Divider(height: 40),
            Text(
              'Full job description',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text('Retained snapshot ${label(snapshot['id'])}'),
            const SizedBox(height: 16),
            SelectableText(
              label(
                snapshot['description'],
                'The description is not available for this retained record.',
              ),
            ),
            const Divider(height: 40),
            Text(
              'Retained source links',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            ...sources.map(
              (source) => Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Last checked ${dateLabel(source['last_verified'])} · ${friendly(source['availability'])}',
                  ),
                  TextButton.icon(
                    icon: const Icon(Icons.open_in_new),
                    label: const Text('View Original Listing'),
                    onPressed: () =>
                        openExternal(context, source['source_url']),
                  ),
                  if (source['employer_url'] != null)
                    TextButton(
                      onPressed: () =>
                          openExternal(context, source['employer_url']),
                      child: const Text('Employer opening'),
                    ),
                ],
              ),
            ),
          ],
        );
      },
    );
    return widget.embedded
        ? body
        : DetailPage(title: 'Job details', child: body);
  }
}
