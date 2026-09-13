import 'models.dart';

/// Builds complete, account-scoped API responses from an already completed
/// server snapshot. The caller commits these responses and its boundary cursor
/// together; no partial page is an authoritative replacement for cached records.
///
/// [now] is explicit so derived application states are deterministic. Snapshot
/// references stay pinned separately for saved jobs, applications and reports.
/// Missing evaluation/Gmail/provider data is left unknown, never inferred from
/// the presence of a job or an application.
Map<String, Json> snapshotResponses(List<Json> items, {required DateTime now}) {
  final entities = <String, Map<String, Json>>{};
  for (final source in items) {
    final type = source['entity_type'];
    final id = source['entity_id'];
    if (type is! String || id is! String || id.isEmpty) continue;
    final rows = entities.putIfAbsent(type, () => <String, Json>{});
    final previous = rows[id];
    // A repeated entity can occur when callers concatenate overlapping pages.
    // Older copies, including a live copy preceding a tombstone, cannot win.
    if (previous != null) {
      final order = _revision(source).compareTo(_revision(previous));
      if (order < 0 || (order == 0 && previous['tombstone'] == true)) {
        continue;
      }
    }
    rows[id] = _copyMap(source);
  }

  Map<String, Json> records(String type) => {
    for (final entry in (entities[type] ?? <String, Json>{}).entries)
      if (entry.value['tombstone'] != true)
        entry.key: {
          'id': entry.key,
          ...object(entry.value['data']),
          if (!object(entry.value['data']).containsKey('revision'))
            'revision': entry.value['revision'] ?? 1,
        },
  };

  final jobs = records('job');
  final employers = records('employer_group');
  final states = records('user_job_state');
  final snapshots = records('job_snapshot');
  final evaluations = _group(records('job_evaluation').values, 'snapshot_id');
  final sources = _group(records('job_source').values, 'job_id');
  final savedVersions = _group(records('saved_job_version').values, 'job_id');
  final events = _group(records('application_event').values, 'application_id');
  final memberships = _group(records('report_job').values, 'report_id');
  final activeApplications = records('applications')
    ..removeWhere((id, application) => application['voided_at'] != null);
  final appsByJob = <String, Json>{
    for (final application in activeApplications.values)
      if (application['job_id'] is String)
        application['job_id'] as String: application,
  };
  final output = <String, Json>{};

  Json renderJob(Json job, {String? pinnedSnapshot}) {
    final id = job['id'] as String;
    final state =
        states[id] ??
        {
          'is_saved': false,
          'saved_at': null,
          'viewed_at': null,
          'dismissed_at': null,
          'revision': 0,
        };
    var selected = pinnedSnapshot;
    if (selected == null && state['is_saved'] == true) {
      final versions =
          (savedVersions[id] ?? [])
              .where((version) => version['ended_at'] == null)
              .toList()
            ..sort(
              (a, b) => _ordered(
                a,
                b,
                'saved_at',
                descending: true,
                descendingId: false,
              ),
            );
      if (versions.isNotEmpty) {
        selected = versions.first['snapshot_id'] as String?;
      }
    }
    selected ??= job['current_snapshot_id'] as String?;
    final candidates = List<Json>.of(evaluations[selected] ?? [])
      ..removeWhere((evaluation) => evaluation['job_id'] != id)
      ..sort(
        (a, b) => _ordered(
          a,
          b,
          'evaluated_at',
          descending: true,
          descendingId: true,
        ),
      );
    final evaluation = candidates.isEmpty ? null : candidates.first;
    final evidence = object(evaluation?['evidence']);
    final storedSnapshot = snapshots[selected];
    Json? snapshot;
    if (storedSnapshot != null) {
      final fields = object(storedSnapshot['structured_fields']);
      final relevance = object(evidence['relevance']);
      final jobEvidence = object(fields['job_evidence']);
      final experience = <String>{
        for (final fact in objects(evidence['facts']))
          if (fact['field'] == 'experience')
            for (final reference in objects(fact['evidence']))
              if (reference['text'] is String && reference['text'] != '')
                reference['text'] as String,
      };
      snapshot = {
        ...storedSnapshot,
        'structured_fields': {
          ...fields,
          if (evaluation != null) ...{
            'summary': relevance['summary'],
            'match_reason': relevance['reason'],
            'matched_skills': relevance['direct_skills'] ?? [],
            'missing_skills': relevance['missing_requested_skills'] ?? [],
            'related_skills': relevance['related_skills'] ?? {},
          },
          if (jobEvidence.containsKey('employment_type'))
            'employment_type': jobEvidence['employment_type'],
          if (jobEvidence.containsKey('salary'))
            'salary': jobEvidence['salary'],
          if (experience.isNotEmpty) 'experience': experience.join('; '),
        },
      };
    }
    final jobSources = List<Json>.of(sources[id] ?? [])
      ..sort((a, b) => _identifier(a).compareTo(_identifier(b)));
    return {
      ...job,
      'company':
          employers[job['employer_group_id']]?['canonical_name'] ??
          job['company'],
      'snapshot': snapshot,
      'state': state,
      'sources': jobSources,
      'application_id': appsByJob[id]?['id'],
      'eligibility': evaluation == null
          ? null
          : {
              'decision': evaluation['decision'],
              'evaluated_at': evaluation['evaluated_at'],
              'valid_until': evaluation['valid_until'],
              'rules': objects(evidence['rules']),
            },
    };
  }

  for (final job in jobs.values) {
    output['/jobs/${job['id']}'] = renderJob(job);
  }
  final savedJobs =
      jobs.values
          .where((job) => states[job['id']]?['is_saved'] == true)
          .map(renderJob)
          .toList()
        ..sort((a, b) {
          final dateOrder = _compareDates(
            object(a['state'])['saved_at'],
            object(b['state'])['saved_at'],
            descending: true,
          );
          return dateOrder != 0
              ? dateOrder
              : _identifier(b).compareTo(_identifier(a));
        });
  output['/saved-jobs'] = _collection(savedJobs);

  final applicationRows = <Json>[];
  for (final application in activeApplications.values) {
    final applied = DateTime.tryParse(label(application['applied_at'], ''));
    final awaiting =
        application['current_status'] == 'APPLIED' &&
        applied != null &&
        now.toUtc().difference(applied.toUtc()) >= const Duration(hours: 24);
    final row = {
      ...application,
      'display_status': awaiting
          ? 'AWAITING_RESPONSE'
          : application['current_status'],
      'display_status_derived': awaiting,
    };
    applicationRows.add(row);
    final timeline = List<Json>.of(events[application['id']] ?? [])
      ..sort((a, b) => _ordered(a, b, 'recorded_at'));
    final selected = application['selected_snapshot_id'];
    // A missing referenced snapshot must not silently use today's job text.
    final snapshot = selected != null
        ? snapshots[selected]
        : application['manual_description'] != null &&
              application['manual_description'] != ''
        ? {
            'id': null,
            'description': application['manual_description'],
            'origin': 'MANUAL',
          }
        : null;
    output['/applications/${application['id']}'] = {
      ...row,
      'snapshot': snapshot,
      'events': timeline,
    };
  }
  applicationRows.sort(
    (a, b) =>
        _ordered(a, b, 'applied_at', descending: true, descendingId: true),
  );
  output['/applications'] = _collection(applicationRows);
  output['/applications?'] = _copyMap(output['/applications']!);
  final counts = <String, int>{};
  for (final application in applicationRows) {
    final status = application['display_status'];
    if (status is String) counts[status] = (counts[status] ?? 0) + 1;
  }
  final byApplication = {for (final row in applicationRows) row['id']: row};
  final superseded = <Object?>{};
  final statusEvents = <Json>[];
  for (final event in records('application_event').values) {
    if (event['correction_of_event_id'] != null) {
      superseded.add(event['correction_of_event_id']);
    }
  }
  for (final event in records('application_event').values) {
    final app = byApplication[event['application_id']];
    final type = event['event_type'];
    if (app == null ||
        event['status'] == null ||
        superseded.contains(event['id']) ||
        (type != 'APPLIED' && type != 'STATUS_CHANGED')) {
      continue;
    }
    statusEvents.add({
      'application_id': app['id'],
      'company': app['company'],
      'title': app['title'],
      'status': event['status'],
      'actor': event['actor'],
      'effective_at': event['effective_at'],
    });
  }
  statusEvents.sort(
    (a, b) =>
        _compareDates(a['effective_at'], b['effective_at'], descending: true),
  );

  final notifications = records('notifications').values.toList()
    ..sort(
      (a, b) =>
          _ordered(a, b, 'created_at', descending: true, descendingId: true),
    );
  final unread = notifications.where((row) => row['read_at'] == null).toList();
  output['/notifications'] = {
    ..._collection(notifications),
    'unread_count': unread.length,
  };
  output['/notifications?unread_only=true'] = {
    ..._collection(unread),
    'unread_count': unread.length,
  };
  output['/notifications/unread-count'] = {'unread_count': unread.length};
  output['/dashboard'] = {
    'total': applicationRows.length,
    'counts': counts,
    'items': applicationRows,
    'recent_events': statusEvents.take(10).toList(),
    'unread_notifications': unread.length,
    'open_reviews': records('reviews').values
        .where((row) => row['admin_only'] != true && row['state'] == 'OPEN')
        .length,
    'watchlist_companies': records('watchlist').values
        .where((row) => row['enabled'] == true)
        .length,
  };

  final profiles = records('profile').values.toList()
    ..sort((a, b) => _revision(b).compareTo(_revision(a)));
  if (profiles.isNotEmpty) output['/profile'] = profiles.first;

  final reports = records('reports').values.toList()
    ..sort(
      (a, b) =>
          _ordered(a, b, 'report_date', descending: true, descendingId: true),
    );
  final reportRows = <Json>[];
  for (final report in reports) {
    final members = memberships[report['id']] ?? [];
    final reportJobs =
        <Json>[
          for (final member in members)
            if (jobs[member['job_id']] != null)
              renderJob(
                jobs[member['job_id']]!,
                pinnedSnapshot: member['snapshot_id'] as String?,
              ),
        ]..sort(
          (a, b) => _ordered(
            a,
            b,
            'published_at',
            descending: true,
            descendingId: false,
          ),
        );
    final summary = {...report, 'count': reportJobs.length};
    reportRows.add(summary);
    output['/reports/${report['id']}'] = {...summary, 'jobs': reportJobs};
  }
  output['/reports'] = _collection(reportRows);

  final reviews =
      records('reviews').values
          .where((row) => row['admin_only'] != true)
          .map((row) => {...row, 'type': row['review_type'] ?? row['type']})
          .toList()
        ..sort((a, b) => _identifier(a).compareTo(_identifier(b)));
  output['/reviews'] = _collection(
    reviews.where((row) => row['state'] == 'OPEN').toList(),
  );
  for (final review in reviews) {
    output['/reviews/${review['id']}'] = review;
  }

  final watchlist =
      records('watchlist').values
          .where((row) => row['enabled'] == true)
          .map(
            (row) => {
              ...row,
              'company': row['employer_group_id'] == null
                  ? row['requested_name']
                  : employers[row['employer_group_id']]?['canonical_name'],
              'resolution_state': row['employer_group_id'] == null
                  ? 'PENDING'
                  : 'REGISTERED',
            },
          )
          .toList()
        ..sort(
          (a, b) => _ordered(
            a,
            b,
            'created_at',
            descending: true,
            descendingId: true,
          ),
        );
  output['/watchlist'] = _collection(watchlist);
  return output;
}

Json _collection(List<Json> rows) => {
  'items': rows,
  'has_more': false,
  'next_cursor': null,
};

Map<String, List<Json>> _group(Iterable<Json> rows, String field) {
  final groups = <String, List<Json>>{};
  for (final row in rows) {
    final key = row[field];
    if (key is String) groups.putIfAbsent(key, () => []).add(row);
  }
  return groups;
}

int _revision(Json row) {
  final value = row['revision'];
  return value is num ? value.toInt() : 0;
}

String _identifier(Json row) => label(row['id'], '');

int _ordered(
  Json a,
  Json b,
  String dateField, {
  bool descending = false,
  bool descendingId = false,
}) {
  final order = _compareDates(
    a[dateField],
    b[dateField],
    descending: descending,
  );
  if (order != 0) return order;
  return descendingId
      ? _identifier(b).compareTo(_identifier(a))
      : _identifier(a).compareTo(_identifier(b));
}

int _compareDates(Object? a, Object? b, {required bool descending}) {
  // PostgreSQL's API pages use NULLS LAST in either direction.
  if (a == null) return b == null ? 0 : 1;
  if (b == null) return -1;
  final left = DateTime.tryParse(a.toString());
  final right = DateTime.tryParse(b.toString());
  final order = left != null && right != null
      ? left.compareTo(right)
      : a.toString().compareTo(b.toString());
  return descending ? -order : order;
}

Json _copyMap(Json value) => {
  for (final entry in value.entries) entry.key: _copyValue(entry.value),
};

Object? _copyValue(Object? value) => value is Map
    ? _copyMap(object(value))
    : value is List
    ? value.map(_copyValue).toList()
    : value;
