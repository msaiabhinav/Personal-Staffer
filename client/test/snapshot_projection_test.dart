import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_staffer/core/models.dart';
import 'package:personal_staffer/core/snapshot_projection.dart';

final _now = DateTime.utc(2026, 9, 12, 12);

Json _envelope(
  String type,
  String id,
  Json data, {
  bool tombstone = false,
  String? entityId,
}) => {
  'entity_type': type,
  'entity_id': entityId ?? id,
  'revision': data['revision'] ?? 1,
  'tombstone': tombstone,
  'data': {'id': id, ...data},
};

Json _application(
  String id, {
  String status = 'APPLIED',
  DateTime? appliedAt,
  bool tombstone = false,
  Json extra = const {},
}) => _envelope('applications', id, {
  'job_id': null,
  'title': 'Data analyst',
  'company': 'Example employer',
  'application_url': 'https://employer.example/apply',
  'source_url': 'https://employer.example/jobs',
  'applied_at': (appliedAt ?? _now).toIso8601String(),
  'applied_date_source': 'USER',
  'current_status': status,
  'revision': 1,
  'voided_at': null,
  'selected_snapshot_id': null,
  'manual_description': null,
  'notes': '',
  'added_by_user': true,
  'updated_at': _now.toIso8601String(),
  ...extra,
}, tombstone: tombstone);

List<Json> _completeItems(Map<String, Json> responses, String route) {
  expect(responses, contains(route));
  final page = responses[route]!;
  expect(page['has_more'], isFalse, reason: '$route is a complete snapshot');
  expect(page, contains('next_cursor'));
  expect(page['next_cursor'], isNull);
  return objects(page['items']);
}

void main() {
  test('uses the latest evaluation of the pinned saved snapshot only', () {
    final oldRules = <Json>[
      {
        'rule_id': 'experience',
        'decision': 'PASS',
        'reason': 'Original evidence',
      },
    ];
    final sourceFields = <String, dynamic>{
      'source_specific': {
        'requisition_id': 'JR-42',
        'tags': ['analytics'],
      },
      'job_evidence': {
        'employment_type': 'FULL_TIME',
        'salary': {'minimum': 70000, 'currency': 'USD'},
      },
    };
    final items = <Json>[
      _envelope('job', 'job-1', {
        'title': 'Data analyst',
        'current_snapshot_id': 'snapshot-current',
      }),
      _envelope('user_job_state', 'state-1', {
        'job_id': 'job-1',
        'is_saved': true,
        'saved_at': '2026-09-09T09:00:00Z',
      }, entityId: 'job-1'),
      _envelope('saved_job_version', 'saved-active', {
        'job_id': 'job-1',
        'snapshot_id': 'snapshot-old',
        'saved_at': '2026-09-09T09:00:00Z',
        'ended_at': null,
      }),
      _envelope('job_snapshot', 'snapshot-old', {
        'job_id': 'job-1',
        'description': 'The original saved description.',
        'structured_fields': sourceFields,
      }),
      _envelope('job_snapshot', 'snapshot-current', {
        'job_id': 'job-1',
        'description': 'A later description with different requirements.',
        'structured_fields': {'source_specific': 'CURRENT_ONLY'},
      }),
      _envelope('job_evaluation', 'evaluation-old-latest', {
        'job_id': 'job-1',
        'snapshot_id': 'snapshot-old',
        'evaluated_at': '2026-09-10T09:00:00Z',
        'valid_until': '2026-09-13T09:00:00Z',
        'decision': 'ELIGIBLE',
        'evidence': {
          'rules': oldRules,
          'facts': [
            {
              'field': 'experience',
              'evidence': [
                {'text': '2 years using SQL'},
                {'text': 'Experience building dashboards'},
                {'text': '2 years using SQL'},
              ],
            },
            {
              'field': 'education',
              'evidence': [
                {'text': 'Not an experience requirement'},
              ],
            },
          ],
          'relevance': {
            'summary': 'Summary of the saved description',
            'reason': 'The original SQL requirements match',
            'direct_skills': ['SQL'],
            'missing_requested_skills': ['Tableau'],
          },
        },
      }),
      _envelope('job_evaluation', 'evaluation-old-earlier', {
        'job_id': 'job-1',
        'snapshot_id': 'snapshot-old',
        'evaluated_at': '2026-09-09T09:00:00Z',
        'decision': 'REVIEW_REQUIRED',
        'evidence': {
          'rules': [
            {'reason': 'SUPERSEDED_OLD_EVALUATION'},
          ],
          'relevance': {'summary': 'SUPERSEDED_OLD_EVALUATION'},
        },
      }),
      _envelope('job_evaluation', 'evaluation-current', {
        'job_id': 'job-1',
        'snapshot_id': 'snapshot-current',
        'evaluated_at': '2026-09-12T09:00:00Z',
        'decision': 'INELIGIBLE',
        'evidence': {
          'rules': [
            {'reason': 'CURRENT_ONLY'},
          ],
          'facts': [
            {
              'field': 'experience',
              'evidence': [
                {'text': '10 years in the new description'},
              ],
            },
          ],
          'relevance': {
            'summary': 'CURRENT_ONLY',
            'reason': 'CURRENT_ONLY',
            'direct_skills': ['Java'],
            'missing_requested_skills': ['Kubernetes'],
          },
        },
      }),
    ];
    final original = jsonDecode(jsonEncode(items));

    final responses = snapshotResponses(items, now: _now);

    final saved = _completeItems(responses, '/saved-jobs').single;
    final snapshot = object(saved['snapshot']);
    expect(snapshot['id'], 'snapshot-old');
    expect(snapshot['description'], 'The original saved description.');
    expect(saved['eligibility'], {
      'decision': 'ELIGIBLE',
      'evaluated_at': '2026-09-10T09:00:00Z',
      'valid_until': '2026-09-13T09:00:00Z',
      'rules': oldRules,
    });
    final fields = object(snapshot['structured_fields']);
    expect(fields['source_specific'], sourceFields['source_specific']);
    expect(fields['job_evidence'], sourceFields['job_evidence']);
    expect(fields['summary'], 'Summary of the saved description');
    expect(fields['match_reason'], 'The original SQL requirements match');
    expect(fields['matched_skills'], ['SQL']);
    expect(fields['missing_skills'], ['Tableau']);
    expect(
      fields['experience'],
      '2 years using SQL; Experience building dashboards',
    );
    expect(fields['employment_type'], 'FULL_TIME');
    expect(fields['salary'], {'minimum': 70000, 'currency': 'USD'});
    expect(responses['/jobs/job-1']!['eligibility'], saved['eligibility']);
    expect(items, original, reason: 'Projection must preserve its source data');
  });

  test(
    'retains distinct saved, application and report description versions',
    () {
      final responses = snapshotResponses([
        _envelope('employer_group', 'company-1', {
          'canonical_name': 'Verified employer',
        }),
        _envelope('job', 'job-1', {
          'employer_group_id': 'company-1',
          'title': 'Data analyst',
          'current_snapshot_id': 'snapshot-current',
          'published_at': '2026-09-10T09:00:00Z',
          'availability': 'OPEN',
        }),
        _envelope('user_job_state', 'state-1', {
          'job_id': 'job-1',
          'is_saved': true,
          'saved_at': '2026-09-09T09:00:00Z',
          'viewed_at': '2026-09-10T09:00:00Z',
          'dismissed_at': null,
          'revision': 4,
        }, entityId: 'job-1'),
        _envelope('saved_job_version', 'saved-active', {
          'job_id': 'job-1',
          'snapshot_id': 'snapshot-saved',
          'saved_at': '2026-09-09T09:00:00Z',
          'ended_at': null,
        }),
        _envelope('saved_job_version', 'saved-ended', {
          'job_id': 'job-1',
          'snapshot_id': 'snapshot-current',
          'saved_at': '2026-09-08T09:00:00Z',
          'ended_at': '2026-09-08T10:00:00Z',
        }),
        for (final version in ['current', 'saved', 'application', 'report'])
          _envelope('job_snapshot', 'snapshot-$version', {
            'job_id': 'job-1',
            'source_id': 'source-1',
            'description': 'Description retained for $version',
            'fetched_at': '2026-09-08T09:00:00Z',
            'content_complete': true,
          }),
        _envelope('job_source', 'source-1', {
          'job_id': 'job-1',
          'source_url': 'https://board.example/job-1',
          'employer_url': 'https://employer.example/jobs/job-1',
          'application_url': 'https://employer.example/apply/job-1',
          'availability': 'OPEN',
        }),
        _application(
          'application-1',
          extra: {
            'job_id': 'job-1',
            'selected_snapshot_id': 'snapshot-application',
          },
        ),
        _envelope('reports', 'report-1', {
          'report_date': '2026-09-08',
          'status': 'RELEASED',
          'summary': {},
        }),
        _envelope('report_job', 'report-member-1', {
          'report_id': 'report-1',
          'job_id': 'job-1',
          'snapshot_id': 'snapshot-report',
          'selection_order': 1,
        }),
      ], now: _now);

      final saved = _completeItems(responses, '/saved-jobs').single;
      expect(saved['company'], 'Verified employer');
      expect(object(saved['state'])['revision'], 4);
      expect(object(saved['state'])['is_saved'], isTrue);
      expect(object(saved['snapshot'])['id'], 'snapshot-saved');
      expect(
        object(saved['snapshot'])['description'],
        'Description retained for saved',
      );
      expect(saved['application_id'], 'application-1');
      expect(
        objects(saved['sources']).single['application_url'],
        'https://employer.example/apply/job-1',
      );
      expect(
        object(responses['/jobs/job-1']!['snapshot'])['id'],
        'snapshot-saved',
      );

      final application = responses['/applications/application-1']!;
      expect(object(application['snapshot'])['id'], 'snapshot-application');
      final report = responses['/reports/report-1']!;
      expect(report['count'], 1);
      expect(
        object(objects(report['jobs']).single['snapshot'])['id'],
        'snapshot-report',
      );
      expect(_completeItems(responses, '/reports').single['count'], 1);
    },
  );

  test(
    'excludes removed applications and restores manual description and events',
    () {
      final responses = snapshotResponses([
        _application(
          'manual',
          extra: {
            'manual_description': 'The description entered when applying.',
          },
        ),
        _application('voided', extra: {'voided_at': '2026-09-12T10:00:00Z'}),
        _application('deleted', tombstone: true),
        _envelope('application_event', 'event-later', {
          'application_id': 'manual',
          'recorded_at': '2026-09-12T11:00:00Z',
          'effective_at': '2026-09-10T08:00:00Z',
          'event_type': 'CORRECTION',
          'correction_of_event_id': 'event-first',
        }),
        _envelope('application_event', 'event-first', {
          'application_id': 'manual',
          'recorded_at': '2026-09-10T09:00:00Z',
          'effective_at': '2026-09-10T09:00:00Z',
          'event_type': 'APPLIED',
        }),
        _envelope('application_event', 'event-middle', {
          'application_id': 'manual',
          'recorded_at': '2026-09-11T09:00:00Z',
          'effective_at': '2026-09-11T09:00:00Z',
          'event_type': 'STATUS_CHANGED',
        }),
        _envelope('application_event', 'event-other', {
          'application_id': 'deleted',
          'recorded_at': '2026-09-09T09:00:00Z',
          'event_type': 'APPLIED',
        }),
      ], now: _now);

      expect(_completeItems(responses, '/applications').single['id'], 'manual');
      expect(responses, isNot(contains('/applications/voided')));
      expect(responses, isNot(contains('/applications/deleted')));
      expect(responses['/dashboard']!['total'], 1);
      final detail = responses['/applications/manual']!;
      expect(detail['snapshot'], {
        'id': null,
        'description': 'The description entered when applying.',
        'origin': 'MANUAL',
      });
      final events = objects(detail['events']);
      expect(events.map((event) => event['id']), [
        'event-first',
        'event-middle',
        'event-later',
      ]);
      expect(events.last['correction_of_event_id'], 'event-first');
    },
  );

  test(
    'derives awaiting response only from APPLIED and the 24 hour boundary',
    () {
      final responses = snapshotResponses([
        _application('old', appliedAt: _now.subtract(const Duration(days: 2))),
        _application(
          'boundary',
          appliedAt: _now.subtract(const Duration(hours: 24)),
        ),
        _application(
          'recent',
          appliedAt: _now.subtract(
            const Duration(hours: 23, minutes: 59, seconds: 59),
          ),
        ),
        _application(
          'interview',
          status: 'INTERVIEWING',
          appliedAt: _now.subtract(const Duration(days: 7)),
        ),
        _application(
          'rejected',
          status: 'REJECTED',
          appliedAt: _now.subtract(const Duration(days: 7)),
        ),
      ], now: _now);

      final applications = {
        for (final row in _completeItems(responses, '/applications'))
          row['id']: row,
      };
      expect(applications['old']!['display_status'], 'AWAITING_RESPONSE');
      expect(applications['boundary']!['display_status'], 'AWAITING_RESPONSE');
      expect(applications['boundary']!['display_status_derived'], isTrue);
      expect(applications['recent']!['display_status'], 'APPLIED');
      expect(applications['recent']!['display_status_derived'], isFalse);
      expect(applications['interview']!['display_status'], 'INTERVIEWING');
      expect(applications['rejected']!['display_status'], 'REJECTED');
      expect(responses['/applications?'], responses['/applications']);
      expect(responses['/dashboard']!['total'], 5);
      expect(responses['/dashboard']!['counts'], {
        'AWAITING_RESPONSE': 2,
        'APPLIED': 1,
        'INTERVIEWING': 1,
        'REJECTED': 1,
      });
    },
  );

  test('dashboard summarises activity, attention counts and watchlist', () {
    Json event(
      String id,
      String app,
      String type,
      String? status,
      int daysAgo, {
      String? corrects,
    }) => _envelope('application_event', id, {
      'application_id': app,
      'event_type': type,
      'status': status,
      'effective_at': _now.subtract(Duration(days: daysAgo)).toIso8601String(),
      'recorded_at': _now.subtract(Duration(days: daysAgo)).toIso8601String(),
      'actor': 'EMAIL',
      'source_reference': null,
      'evidence': const {},
      'correction_of_event_id': corrects,
    });
    final responses = snapshotResponses([
      _application('a', appliedAt: _now.subtract(const Duration(days: 9))),
      _application(
        'b',
        status: 'REJECTED',
        appliedAt: _now.subtract(const Duration(days: 20)),
      ),
      _application(
        'gone',
        status: 'APPLIED',
        appliedAt: _now.subtract(const Duration(days: 3)),
        extra: {'voided_at': _now.toIso8601String()},
      ),
      event('e1', 'a', 'APPLIED', 'APPLIED', 9),
      event('e2', 'b', 'APPLIED', 'APPLIED', 20),
      event('e3', 'b', 'STATUS_CHANGED', 'REJECTED', 1),
      event('e4', 'b', 'EVIDENCE_RECEIVED', null, 0), // no status: not activity
      event('e5', 'b', 'CORRECTION', 'OFFER', 0, corrects: 'e3'),
      event('e6', 'gone', 'APPLIED', 'APPLIED', 3), // voided application
      _envelope('notifications', 'n1', {
        'type': 'EMAIL_REVIEW',
        'created_at': _now.toIso8601String(),
        'read_at': null,
        'revision': 1,
      }),
      _envelope('notifications', 'n2', {
        'type': 'EMAIL_REVIEW',
        'created_at': _now.toIso8601String(),
        'read_at': _now.toIso8601String(),
        'revision': 2,
      }),
      _envelope('reviews', 'r1', {
        'review_type': 'EMAIL_APPLICATION',
        'state': 'OPEN',
      }),
      _envelope('reviews', 'r2', {
        'review_type': 'EMAIL_APPLICATION',
        'state': 'RESOLVED',
      }),
      _envelope('reviews', 'r3', {
        'review_type': 'X',
        'state': 'OPEN',
        'admin_only': true,
      }),
      _envelope('watchlist', 'w1', {'enabled': true, 'requested_name': 'Acme'}),
      _envelope('watchlist', 'w2', {'enabled': false, 'requested_name': 'Old'}),
    ], now: _now);
    final dashboard = responses['/dashboard']!;
    expect(dashboard['total'], 2);
    expect(dashboard['unread_notifications'], 1);
    expect(dashboard['open_reviews'], 1);
    expect(dashboard['watchlist_companies'], 1);
    final recent = (dashboard['recent_events'] as List).cast<Json>();
    // e3 is superseded by the correction e5; e4 has no status; e6 belongs to a voided row.
    expect(recent.map((e) => e['status']), ['APPLIED', 'APPLIED']);
    expect(recent.first['application_id'], 'a'); // newest effective_at first
    expect(recent.first['company'], 'Example employer');
    expect(recent.first['actor'], 'EMAIL');
  });

  test('reconstructs complete inbox and unread views from read state', () {
    final responses = snapshotResponses([
      _envelope('notifications', 'read', {
        'type': 'APPLICATION_UPDATE',
        'created_at': '2026-09-12T10:00:00Z',
        'read_at': '2026-09-12T11:00:00Z',
        'route': '/applications/application-1',
      }),
      _envelope('notifications', 'unread', {
        'type': 'REPORT_READY',
        'created_at': '2026-09-12T09:00:00Z',
        'read_at': null,
        'route': '/reports/report-1',
        'revision': 3,
      }),
      _envelope('notifications', 'deleted', {
        'created_at': '2026-09-12T12:00:00Z',
        'read_at': null,
      }, tombstone: true),
    ], now: _now);

    expect(
      _completeItems(responses, '/notifications').map((row) => row['id']),
      unorderedEquals(['read', 'unread']),
    );
    final unread = _completeItems(
      responses,
      '/notifications?unread_only=true',
    ).single;
    expect(unread['id'], 'unread');
    expect(unread['revision'], 3);
    expect(unread['route'], '/reports/report-1');
    expect(responses['/notifications/unread-count'], {'unread_count': 1});
  });

  test('restores profile, open reviews and enabled watchlist API shapes', () {
    final responses = snapshotResponses([
      _envelope('profile', 'profile-1', {
        'version': 4,
        'revision': 7,
        'skills': ['SQL', 'Python'],
        'geography': {
          'countries': ['US'],
        },
      }),
      _envelope('employer_group', 'company-1', {
        'canonical_name': 'Registered company',
      }),
      _envelope('reviews', 'review-open', {
        'review_type': 'EMAIL_APPLICATION',
        'state': 'OPEN',
        'reason': 'Choose the matching application.',
        'evidence': {
          'application_ids': ['application-1'],
        },
        'target_id': 'message-1',
        'revision': 2,
      }),
      _envelope('reviews', 'review-resolved', {
        'review_type': 'EMAIL_APPLICATION',
        'state': 'RESOLVED',
        'resolution': {'action': 'LINK', 'application_id': 'application-1'},
      }),
      _envelope('reviews', 'review-deleted', {
        'review_type': 'EMAIL_APPLICATION',
        'state': 'OPEN',
      }, tombstone: true),
      _envelope('watchlist', 'registered', {
        'employer_group_id': 'company-1',
        'requested_name': null,
        'enabled': true,
      }),
      _envelope('watchlist', 'pending', {
        'employer_group_id': null,
        'requested_name': 'Requested company',
        'enabled': true,
      }),
      _envelope('watchlist', 'disabled', {
        'employer_group_id': null,
        'requested_name': 'Disabled company',
        'enabled': false,
      }),
    ], now: _now);

    expect(responses['/profile']!['skills'], ['SQL', 'Python']);
    expect(responses['/profile']!['revision'], 7);
    final review = _completeItems(responses, '/reviews').single;
    expect(review['id'], 'review-open');
    expect(review['type'], 'EMAIL_APPLICATION');
    expect(responses['/reviews/review-open']!['evidence'], {
      'application_ids': ['application-1'],
    });
    expect(responses['/reviews/review-resolved']!['resolution'], {
      'action': 'LINK',
      'application_id': 'application-1',
    });
    expect(responses, isNot(contains('/reviews/review-deleted')));
    final watchlist = {
      for (final row in _completeItems(responses, '/watchlist')) row['id']: row,
    };
    expect(watchlist.keys, unorderedEquals(['registered', 'pending']));
    expect(watchlist['registered']!['company'], 'Registered company');
    expect(watchlist['registered']!['resolution_state'], 'REGISTERED');
    expect(watchlist['pending']!['company'], 'Requested company');
    expect(watchlist['pending']!['resolution_state'], 'PENDING');
  });
}
