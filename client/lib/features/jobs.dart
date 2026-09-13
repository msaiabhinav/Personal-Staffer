import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';
import '../core/theme.dart';
import 'dashboard.dart';
import 'shared.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});
  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 2,
    child: Column(
      children: [
        Material(
          color: Theme.of(context).colorScheme.surface,
          child: const TabBar(
            tabAlignment: TabAlignment.start,
            isScrollable: true,
            padding: EdgeInsets.symmetric(horizontal: 12),
            tabs: [
              Tab(text: 'Job Feed'),
              Tab(text: 'Application Dashboard'),
            ],
          ),
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
    final preview = scope == 'scanned';
    final query = Uri(
      queryParameters: {
        'scope': scope,
        if (scope != 'history' && !preview) 'posted_within_hours': hours,
        if (preview) ...{'limit': '5', 'relevant_only': 'true'},
        if (keyword.isNotEmpty) 'keyword': keyword,
        if (arrangement.isNotEmpty) 'work_arrangement': arrangement,
      },
    ).query;
    final route = widget.saved ? '/saved-jobs' : '/jobs?$query';
    final list = Column(
      children: [
        if (widget.saved)
          const PageHeader(
            title: 'Saved Jobs',
            subtitle: 'Kept until you unsave them or record your application; expired postings stay visible.',
          ),
        if (!widget.saved)
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 12),
            child: Wrap(
              spacing: 12,
              runSpacing: 10,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                DropdownMenu<String>(
                  width: 290,
                  initialSelection: scope,
                  leadingIcon: const Icon(Icons.view_agenda_outlined),
                  label: const Text('Scope'),
                  dropdownMenuEntries: const [
                    DropdownMenuEntry(
                      value: 'today',
                      label: 'Today\u2019s report',
                    ),
                    DropdownMenuEntry(
                      value: 'priority',
                      label: 'Additional priority jobs',
                    ),
                    DropdownMenuEntry(
                      value: 'history',
                      label: 'Previously delivered',
                    ),
                    DropdownMenuEntry(
                      value: 'scanned',
                      label: 'Scanned postings (preview)',
                    ),
                  ],
                  onSelected: (v) => setState(() => scope = v ?? scope),
                ),
                if (!preview)
                  DropdownMenu<String>(
                    width: 230,
                    initialSelection: hours,
                    leadingIcon: const Icon(Icons.schedule_outlined),
                    label: const Text('Freshness'),
                    dropdownMenuEntries: ['24', '48', '72']
                        .map(
                          (h) => DropdownMenuEntry(
                            value: h,
                            label: 'Within $h hours',
                          ),
                        )
                        .toList(),
                    onSelected: (v) => setState(() => hours = v ?? hours),
                  ),
                DropdownMenu<String>(
                  width: 240,
                  initialSelection: arrangement,
                  leadingIcon: const Icon(Icons.laptop_outlined),
                  label: const Text('Arrangement'),
                  dropdownMenuEntries: const [
                    DropdownMenuEntry(value: '', label: 'All arrangements'),
                    DropdownMenuEntry(value: 'REMOTE', label: 'Remote'),
                    DropdownMenuEntry(value: 'HYBRID', label: 'Hybrid'),
                    DropdownMenuEntry(value: 'ONSITE', label: 'Onsite'),
                  ],
                  onSelected: (v) =>
                      setState(() => arrangement = v ?? arrangement),
                ),
                SizedBox(
                  width: 260,
                  child: TextField(
                    decoration: const InputDecoration(
                      isDense: true,
                      labelText: 'Search title or company',
                      prefixIcon: Icon(Icons.search),
                      contentPadding: EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 12,
                      ),
                    ),
                    onSubmitted: (v) => setState(() => keyword = v),
                  ),
                ),
              ],
            ),
          ),
        if (!widget.saved && scope == 'today') const ReportSummary(),
        if (!widget.saved && preview)
          const StatusStrip(
            'Preview: the 5 newest open postings your career-site sources collected that match your role families, delivered or not. Each card says whether it qualifies or why it was withheld.',
          ),
        Expanded(
          child: ResourceView(
            route: route,
            builder: (data) {
              final rows = objects(data['items']);
              if (rows.isEmpty) {
                return EmptyMessage(
                  icon: widget.saved
                      ? Icons.bookmark_outline
                      : Icons.work_outline,
                  title: widget.saved
                      ? 'Keep an opportunity for later'
                      : scope == 'priority'
                      ? 'No new priority opportunities'
                      : preview
                      ? 'No relevant postings scanned yet'
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
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                itemCount: rows.length,
                itemBuilder: (context, index) {
                  return JobRow(
                    job: rows[index],
                    showDecision: preview,
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

/// Role-relevance label from the latest evaluation's `role_relevance` rule.
/// Returns null when the posting was never evaluated.
Widget? relevancePill(Json job) {
  final eligibility = object(job['eligibility']);
  if (eligibility.isEmpty) return null;
  final rule = objects(eligibility['rules']).cast<Json?>().firstWhere(
    (r) => r?['rule_code'] == 'role_relevance',
    orElse: () => null,
  );
  if (rule == null) return null;
  final reason = label(rule['reason_code'], '');
  if (reason == 'ROLE_RELEVANT') {
    final match = label(
      object(object(job['snapshot'])['structured_fields'])['match_reason'],
      '',
    );
    final family = match.split(';').first.trim();
    return StatusPill(
      family.isEmpty ? 'Relevant role' : 'Relevant · $family',
      icon: Icons.thumb_up_outlined,
      tone: PillTone.positive,
    );
  }
  if (reason == 'ROLE_RESPONSIBILITIES_UNRESOLVED') {
    return const StatusPill(
      'Title matches · responsibilities unclear',
      icon: Icons.help_outline,
      tone: PillTone.warning,
    );
  }
  return const StatusPill(
    'Unrelated role',
    icon: Icons.thumb_down_outlined,
    tone: PillTone.neutral,
  );
}

/// Delivered / withheld label for a posting, from its latest evaluation.
/// Never colours an unevaluated or withheld posting as a match.
Widget decisionPill(Json job) {
  final eligibility = object(job['eligibility']);
  if (eligibility.isEmpty) {
    return const StatusPill(
      'Not evaluated yet',
      icon: Icons.help_outline,
      tone: PillTone.neutral,
    );
  }
  final decision = label(eligibility['decision'], '');
  if (decision == 'ELIGIBLE') {
    return const StatusPill(
      'Qualifies',
      icon: Icons.verified_outlined,
      tone: PillTone.positive,
    );
  }
  final failed = objects(eligibility['rules'])
      .where((rule) => rule['decision'] != 'PASS')
      .where((rule) => rule['rule_code'] != 'role_relevance')
      .map((rule) => friendly(rule['reason_code'] ?? rule['rule_code']))
      .toList();
  final reason = failed.isEmpty
      ? friendly(decision)
      : failed.take(2).join(', ');
  return StatusPill(
    decision == 'NEEDS_REVIEW'
        ? 'Needs review · $reason'
        : 'Withheld · $reason',
    icon: Icons.block,
    tone: decision == 'NEEDS_REVIEW' ? PillTone.warning : PillTone.danger,
  );
}

class JobRow extends ConsumerWidget {
  const JobRow({
    super.key,
    required this.job,
    required this.onOpen,
    this.showDecision = false,
  });
  final Json job;
  final VoidCallback onOpen;

  /// Show the delivered/withheld verdict (scanned previews and company pages).
  final bool showDecision;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fields = object(object(job['snapshot'])['structured_fields']);
    final state = object(job['state']);
    final pending = ref.watch(repositoryProvider).pendingFor(job['id']);
    final theme = Theme.of(context);
    final locations = job['locations'] is List
        ? (job['locations'] as List).join(' · ')
        : label(job['locations']);
    final colors = context.colors;
    final accentBar = job['application_id'] != null
        ? colors.green
        : state['is_saved'] == true
        ? theme.colorScheme.primary
        : job['availability'] != 'ACTIVE'
        ? colors.amber
        : null;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpen,
        child: Container(
          decoration: accentBar == null
              ? null
              : BoxDecoration(
                  border: Border(left: BorderSide(color: accentBar, width: 4)),
                ),
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          label(job['title']),
                          style: theme.textTheme.titleMedium,
                        ),
                        const SizedBox(height: 3),
                        Text(
                          label(job['company']),
                          style: theme.textTheme.bodyLarge?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 12),
                  if (pending)
                    const StatusPill(
                      'Pending',
                      icon: Icons.sync,
                      tone: PillTone.warning,
                    ),
                  if (state['is_saved'] == true) ...[
                    const SizedBox(width: 8),
                    Tooltip(
                      message: 'Saved',
                      child: Icon(
                        Icons.bookmark,
                        color: theme.colorScheme.primary,
                      ),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  StatusPill(
                    locations,
                    icon: Icons.place_outlined,
                    tone: PillTone.info,
                  ),
                  StatusPill(
                    friendly(job['work_arrangement']),
                    icon: Icons.laptop_outlined,
                    tone: PillTone.violet,
                  ),
                  if (fields['salary'] != null)
                    StatusPill(
                      salaryLabel(fields['salary']),
                      icon: Icons.payments_outlined,
                      // Green only for disclosed pay; undisclosed stays neutral.
                      tone: salaryLabel(fields['salary']) == 'Not stated'
                          ? PillTone.neutral
                          : PillTone.positive,
                    ),
                  if (fields['experience'] != null)
                    StatusPill(
                      '${fields['experience']}',
                      icon: Icons.timeline_outlined,
                      tone: PillTone.warning,
                    ),
                  if (job['availability'] != 'ACTIVE')
                    StatusPill(
                      'Posting ${friendly(job['availability'])} · retained record',
                      icon: Icons.history,
                      tone: PillTone.warning,
                    ),
                  if (showDecision) ...[?relevancePill(job), decisionPill(job)],
                ],
              ),
              const SizedBox(height: 10),
              Text(
                'Published ${publicationLabel(job)}'
                '${state['saved_at'] != null ? ' · Saved ${dateLabel(state['saved_at'])}' : ''}',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              if (fields['summary'] != null)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
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
