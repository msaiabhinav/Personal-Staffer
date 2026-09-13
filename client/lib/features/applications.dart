import 'dart:convert';

import 'package:uuid/uuid.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';
import '../core/theme.dart';
import 'shared.dart';

const applicationStatuses = [
  'APPLIED',
  'ASSESSMENT',
  'INTERVIEWING',
  'OFFER',
  'REJECTED',
  'POSITION_CLOSED',
];

class ApplicationsPage extends StatefulWidget {
  const ApplicationsPage({super.key, this.initialStatus = ''});

  /// Status filter to open with (dashboard tiles link here with one).
  final String initialStatus;
  @override
  State<ApplicationsPage> createState() => _ApplicationsPageState();
}

class _ApplicationsPageState extends State<ApplicationsPage> {
  String query = '';
  late String status = widget.initialStatus;
  @override
  Widget build(BuildContext context) => Column(
    children: [
      Padding(
        padding: const EdgeInsets.all(16),
        child: Wrap(
          spacing: 16,
          runSpacing: 12,
          children: [
            SizedBox(
              width: 260,
              child: TextField(
                decoration: const InputDecoration(
                  labelText: 'Search applications',
                  prefixIcon: Icon(Icons.search),
                ),
                onSubmitted: (value) => setState(() => query = value),
              ),
            ),
            DropdownButton<String>(
              value: status,
              items: [
                const DropdownMenuItem(value: '', child: Text('All statuses')),
                const DropdownMenuItem(
                  value: 'AWAITING_RESPONSE',
                  child: Text('No reply yet'),
                ),
                ...applicationStatuses.map(
                  (s) => DropdownMenuItem(value: s, child: Text(friendly(s))),
                ),
              ],
              onChanged: (v) => setState(() => status = v!),
            ),
            FilledButton.icon(
              onPressed: () => context.push('/applications/new'),
              icon: const Icon(Icons.add),
              label: const Text('Add Application'),
            ),
          ],
        ),
      ),
      Expanded(
        child: ResourceView(
          route:
              '/applications?${Uri(queryParameters: {if (query.isNotEmpty) 'keyword': query, if (status.isNotEmpty) 'status': status}).query}',
          builder: (data) => ApplicationList(items: objects(data['items'])),
        ),
      ),
    ],
  );
}

class ApplicationList extends StatelessWidget {
  const ApplicationList({super.key, required this.items});
  final List<Json> items;
  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) {
      return const EmptyMessage(
        icon: Icons.work_outline,
        title: 'Your applications, kept together',
        message: 'Mark Applied on a job after you submit it, or add an application you made elsewhere. Your dates, links and history stay here.',
      );
    }
    return ListView.builder(
      itemCount: items.length,
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
      itemBuilder: (context, index) {
        final row = items[index];
        final status = friendly(row['display_status'] ?? row['current_status']);
        return Card(
          clipBehavior: Clip.antiAlias,
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(
              vertical: 8,
              horizontal: 18,
            ),
            leading: CircleAvatar(
              backgroundColor: context.colors.tint(
                hueFor(context, label(row['company'])),
                Theme.of(context).brightness,
              ),
              foregroundColor: hueFor(context, label(row['company'])),
              child: Text(
                label(
                  row['company'],
                  '?',
                ).trim().characters.first.toUpperCase(),
              ),
            ),
            title: Text(
              label(row['title']),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            subtitle: Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Wrap(
                spacing: 8,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(label(row['company'])),
                  StatusPill(status, tone: PillTone.positive),
                  Text(
                    'Applied ${dateLabel(row['applied_at'])}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push('/applications/${row['id']}'),
          ),
        );
      },
    );
  }
}

class AddApplicationPage extends ConsumerStatefulWidget {
  const AddApplicationPage({super.key});
  @override
  ConsumerState<AddApplicationPage> createState() => _AddApplicationState();
}

class _AddApplicationState extends ConsumerState<AddApplicationPage> {
  String requestId = const Uuid().v4();
  String? requestFingerprint;
  final form = GlobalKey<FormState>();
  final company = TextEditingController(),
      title = TextEditingController(),
      url = TextEditingController(),
      description = TextEditingController();
  DateTime applied = DateTime.now();
  bool busy = false;
  @override
  void dispose() {
    company.dispose();
    title.dispose();
    url.dispose();
    description.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (!form.currentState!.validate()) return;
    setState(() => busy = true);
    try {
      final repo = ref.read(repositoryProvider);
      final payload = <String, dynamic>{
        'company': company.text.trim(),
        'title': title.text.trim(),
        'application_url': url.text.trim().isEmpty ? null : url.text.trim(),
        'applied_at': applied.toUtc().toIso8601String(),
        'description': description.text.trim().isEmpty
            ? null
            : description.text.trim(),
      };
      final fingerprint = jsonEncode(payload);
      if (requestFingerprint != null && requestFingerprint != fingerprint) {
        requestId = const Uuid().v4();
      }
      requestFingerprint = fingerprint;
      final j = await repo.session.request(
        'POST',
        '/applications',
        operationId: requestId,
        body: payload,
      );
      repo.changed();
      if (mounted) {
        context.go('/applications/${j['id'] ?? j['application_id']}');
      }
    } on ApiError catch (e) {
      if (mounted) showMessage(context, e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => DetailPage(
    title: 'Add Application',
    child: SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 700),
          child: Form(
            key: form,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Record a role you already applied to. This will be labeled “Added by you.”',
                ),
                const SizedBox(height: 24),
                TextFormField(
                  controller: company,
                  decoration: const InputDecoration(labelText: 'Company'),
                  validator: (v) => v == null || v.trim().isEmpty
                      ? 'Enter the company'
                      : null,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: title,
                  decoration: const InputDecoration(labelText: 'Job title'),
                  validator: (v) => v == null || v.trim().isEmpty
                      ? 'Enter the job title'
                      : null,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: url,
                  decoration: const InputDecoration(
                    labelText: 'Application or source link (optional)',
                  ),
                  validator: (v) =>
                      v != null &&
                          v.trim().isNotEmpty &&
                          externalDestination(v.trim()) == null
                      ? 'Use a complete http or https link'
                      : null,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: description,
                  minLines: 4,
                  maxLines: 12,
                  decoration: const InputDecoration(
                    labelText: 'Job description (optional)',
                  ),
                ),
                const SizedBox(height: 16),
                TextButton.icon(
                  onPressed: () async {
                    final date = await showDatePicker(
                      context: context,
                      initialDate: applied,
                      firstDate: DateTime(2000),
                      lastDate: DateTime.now(),
                    );
                    if (date != null) setState(() => applied = date);
                  },
                  icon: const Icon(Icons.calendar_today_outlined),
                  label: Text(
                    'Applied ${dateLabel(applied.toIso8601String())}',
                  ),
                ),
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: busy ? null : submit,
                  child: Text(busy ? 'Recording…' : 'Record application'),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class ApplicationDetail extends ConsumerStatefulWidget {
  const ApplicationDetail({super.key, required this.id});
  final String id;
  @override
  ConsumerState<ApplicationDetail> createState() => _ApplicationDetailState();
}

class _ApplicationDetailState extends ConsumerState<ApplicationDetail> {
  final notes = TextEditingController(), reason = TextEditingController();
  String? initialized;
  String status = 'APPLIED';
  bool busy = false;
  String? correctionEvent;
  String correctionAction = 'REVERT_EVENT';
  @override
  void dispose() {
    notes.dispose();
    reason.dispose();
    super.dispose();
  }

  Future<void> mutate(String command, Json payload) async {
    setState(() => busy = true);
    try {
      final result = await ref
          .read(repositoryProvider)
          .command(command, widget.id, payload);
      if (mounted) {
        showMessage(
          context,
          result['pending'] == true
              ? 'Pending · This change will sync when connected.'
              : result['conflict'] == true
              ? 'Newer activity conflicts with this change. Review Pending changes in Settings.'
              : 'Application updated.',
        );
        setState(() => correctionEvent = null);
      }
    } on ApiError catch (e) {
      if (mounted) showMessage(context, e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => DetailPage(
    title: 'Application timeline',
    child: ResourceView(
      route: '/applications/${widget.id}',
      builder: (app) {
        if (initialized != app['id']) {
          notes.text = label(app['notes'], '');
          initialized = app['id'];
          status = applicationStatuses.contains(app['current_status'])
              ? app['current_status']
              : 'APPLIED';
        }
        final events = objects(app['events']);
        final revision = app['revision'];
        final disabled =
            busy || ref.watch(repositoryProvider).pendingFor(widget.id);
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Text(
              label(app['title']),
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              label(app['company']),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 16),
            Field(
              'Current status',
              friendly(app['display_status'] ?? app['current_status']),
            ),
            Field('Applied date', dateLabel(app['applied_at'])),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: disabled
                    ? null
                    : () async {
                        final parsed =
                            DateTime.tryParse(label(app['applied_at'], '')) ??
                            DateTime.now();
                        final selected = await showDatePicker(
                          context: context,
                          initialDate: parsed.isAfter(DateTime.now())
                              ? DateTime.now()
                              : parsed,
                          firstDate: DateTime(2000),
                          lastDate: DateTime.now(),
                        );
                        if (selected != null) {
                          await mutate('notes', {
                            'applied_at': selected.toUtc().toIso8601String(),
                            'expected_revision': revision,
                          });
                        }
                      },
                child: const Text('Correct applied date'),
              ),
            ),
            if (app['job_id'] == null) const Field('Origin', 'Added by you'),
            if (app['voided_at'] != null)
              const StatusStrip(
                'Mistaken application corrected · excluded from active totals',
              ),
            Wrap(
              spacing: 12,
              children: [
                if (app['application_url'] != null)
                  TextButton.icon(
                    onPressed: () =>
                        openExternal(context, app['application_url']),
                    icon: const Icon(Icons.open_in_new),
                    label: const Text('Revisit application link'),
                  ),
                if (app['source_url'] != null)
                  TextButton(
                    onPressed: () => openExternal(context, app['source_url']),
                    child: const Text('View Original Listing'),
                  ),
                if (app['job_id'] != null)
                  TextButton(
                    onPressed: () =>
                        context.push('/people?job=${app['job_id']}'),
                    child: const Text('People'),
                  ),
              ],
            ),
            const SizedBox(height: 24),
            TextField(
              controller: notes,
              minLines: 3,
              maxLines: 8,
              decoration: const InputDecoration(labelText: 'Your notes'),
            ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(
                onPressed: disabled
                    ? null
                    : () => mutate('notes', {
                        'notes': notes.text,
                        'expected_revision': revision,
                      }),
                child: const Text('Save notes'),
              ),
            ),
            const Divider(height: 40),
            Text(
              'Update application',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: status,
              items: applicationStatuses
                  .map(
                    (s) => DropdownMenuItem(value: s, child: Text(friendly(s))),
                  )
                  .toList(),
              onChanged: disabled ? null : (s) => setState(() => status = s!),
              decoration: const InputDecoration(labelText: 'Status'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: reason,
              decoration: const InputDecoration(labelText: 'Reason / evidence'),
            ),
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.tonal(
                onPressed: disabled
                    ? null
                    : () {
                        if (reason.text.trim().isEmpty) {
                          showMessage(
                            context,
                            'Add a reason for this status change.',
                          );
                          return;
                        }
                        mutate('status', {
                          'status': status,
                          'reason': reason.text.trim(),
                          'expected_revision': revision,
                        });
                      },
                child: const Text('Record status change'),
              ),
            ),
            const Divider(height: 40),
            Text(
              'Event history',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            ...events.map(
              (event) => Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${friendly(event['event_type'] ?? event['type'])} · ${dateLabel(event['effective_at'] ?? event['recorded_at'])}',
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    Field('Recorded by', event['actor']),
                    if (event['evidence'] != null)
                      Field('Source evidence', event['evidence']),
                    if (event['reason'] != null)
                      Field('Reason', event['reason']),
                    TextButton(
                      onPressed: disabled
                          ? null
                          : () => setState(() {
                              correctionEvent = event['id'];
                              correctionAction =
                                  (event['event_type'] ?? event['type']) ==
                                      'APPLIED'
                                  ? 'UNDO_APPLIED'
                                  : 'REVERT_EVENT';
                            }),
                      child: const Text('Correct this event'),
                    ),
                  ],
                ),
              ),
            ),
            if (correctionEvent != null) ...[
              const Divider(),
              Text(
                correctionAction == 'UNDO_APPLIED'
                    ? 'Correct accidental Applied'
                    : 'Correct the selected event',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              const Text(
                'The server checks for later activity. A conflict preserves newer events and asks you to review them.',
              ),
              const SizedBox(height: 12),
              TextField(
                decoration: const InputDecoration(
                  labelText: 'Correction reason',
                ),
                onChanged: (v) => reason.text = v,
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 12,
                children: [
                  FilledButton(
                    onPressed: disabled
                        ? null
                        : () {
                            if (reason.text.trim().isEmpty) {
                              showMessage(
                                context,
                                'Enter a correction reason.',
                              );
                              return;
                            }
                            mutate('correction', {
                              'event_id': correctionEvent,
                              'expected_revision': revision,
                              'reason': reason.text.trim(),
                              'action': correctionAction,
                            });
                          },
                    child: const Text('Confirm correction'),
                  ),
                  TextButton(
                    onPressed: () => setState(() => correctionEvent = null),
                    child: const Text('Cancel'),
                  ),
                ],
              ),
            ],
            const Divider(height: 40),
            Text(
              'Retained job description',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            SelectableText(
              label(
                object(app['snapshot'])['description'],
                'No description was supplied for this application.',
              ),
            ),
          ],
        );
      },
    ),
  );
}
