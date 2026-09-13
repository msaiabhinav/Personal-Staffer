import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../core/models.dart';
import '../core/theme.dart';
import 'company.dart';
import 'shared.dart';

/// Statuses that mean the application is still open, in pipeline order.
const _openStatuses = [
  'APPLIED',
  'AWAITING_RESPONSE',
  'ASSESSMENT',
  'INTERVIEWING',
  'OFFER',
];
const _closedStatuses = ['REJECTED', 'POSITION_CLOSED', 'WITHDRAWN'];

/// Plain-language names for the derived and stored statuses.
String statusName(String status) => switch (status) {
  'APPLIED' => 'Applied',
  'AWAITING_RESPONSE' => 'No reply yet',
  'ASSESSMENT' => 'Assessment',
  'INTERVIEWING' => 'Interviewing',
  'OFFER' => 'Offer',
  'REJECTED' => 'Rejected',
  'POSITION_CLOSED' => 'Position closed',
  'WITHDRAWN' => 'Withdrawn',
  _ => friendly(status),
};

Color statusHue(BuildContext context, String status) {
  final colors = context.colors;
  return switch (status) {
    'APPLIED' => colors.blue,
    'AWAITING_RESPONSE' => colors.amber,
    'ASSESSMENT' || 'INTERVIEWING' => colors.violet,
    'OFFER' => colors.green,
    'REJECTED' || 'POSITION_CLOSED' || 'WITHDRAWN' => colors.coral,
    _ => Theme.of(context).colorScheme.primary,
  };
}

IconData statusIcon(String status) => switch (status) {
  'APPLIED' => Icons.send_outlined,
  'AWAITING_RESPONSE' => Icons.hourglass_bottom,
  'ASSESSMENT' => Icons.quiz_outlined,
  'INTERVIEWING' => Icons.forum_outlined,
  'OFFER' => Icons.celebration_outlined,
  'REJECTED' => Icons.cancel_outlined,
  'POSITION_CLOSED' => Icons.block,
  _ => Icons.label_outline,
};

/// Everything the panels need, derived once from the `/dashboard` payload so
/// each number on screen comes from the same list of applications.
class _Summary {
  _Summary(Json data, DateTime now) : items = objects(data['items']) {
    for (final row in items) {
      final status = label(row['display_status'] ?? row['current_status'], '');
      counts[status] = (counts[status] ?? 0) + 1;
      final applied = DateTime.tryParse(label(row['applied_at'], ''));
      if (applied == null) continue;
      final age = now.difference(applied.toUtc());
      if (status == 'AWAITING_RESPONSE' || status == 'APPLIED') {
        waiting.add((row, age));
      }
      final weeksAgo = age.inDays ~/ 7;
      if (weeksAgo >= 0 && weeksAgo < weekly.length) {
        weekly[weekly.length - 1 - weeksAgo] += 1;
      }
    }
    waiting.sort((a, b) => b.$2.compareTo(a.$2));
    recent = objects(data['recent_events']);
    unread = (data['unread_notifications'] as num?)?.toInt() ?? 0;
    openReviews = (data['open_reviews'] as num?)?.toInt() ?? 0;
    watched = (data['watchlist_companies'] as num?)?.toInt() ?? 0;
    gmail = label(data['email_sync_health'], 'NOT_CONFIGURED');
  }

  final List<Json> items;
  final counts = <String, int>{};
  final waiting = <(Json, Duration)>[];
  final weekly = List<int>.filled(12, 0);
  late final List<Json> recent;
  late final int unread, openReviews, watched;
  late final String gmail;

  int get total => items.length;
  int of(String status) => counts[status] ?? 0;
  int get open => _openStatuses.fold(0, (sum, s) => sum + of(s));
  int get closed => _closedStatuses.fold(0, (sum, s) => sum + of(s));
  int get noReply => of('APPLIED') + of('AWAITING_RESPONSE');
  int get interviews => of('ASSESSMENT') + of('INTERVIEWING');
  int get offers => of('OFFER');

  /// Applications where an employer has said anything at all.
  int get replied => total - noReply;
  int get stale => waiting.where((w) => w.$2.inDays >= 30).length;
}

class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});
  @override
  Widget build(BuildContext context) => ResourceView(
    route: '/dashboard',
    builder: (data) {
      final s = _Summary(data, DateTime.now().toUtc());
      if (s.total == 0) {
        return const EmptyMessage(
          icon: Icons.dashboard_outlined,
          title: 'Your dashboard fills in as you apply',
          message: 'Mark Applied on a job, add an application you made elsewhere, or connect Gmail to import confirmations. Pipeline, response rate and activity appear here.',
        );
      }
      return LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 980;
          return ListView(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 32),
            children: [
              const CompanySearch(),
              const SizedBox(height: 16),
              _Kpis(s),
              const SizedBox(height: 16),
              _Grid(
                wide: wide,
                left: _PipelineCard(s),
                right: _AttentionCard(s),
                leftFlex: 3,
                rightFlex: 2,
              ),
              const SizedBox(height: 16),
              _Grid(
                wide: wide,
                left: _WeeklyCard(s),
                right: _ActivityCard(s),
                leftFlex: 3,
                rightFlex: 2,
              ),
              const SizedBox(height: 16),
              _WaitingCard(s),
            ],
          );
        },
      );
    },
  );
}

class _Grid extends StatelessWidget {
  const _Grid({
    required this.wide,
    required this.left,
    required this.right,
    required this.leftFlex,
    required this.rightFlex,
  });
  final bool wide;
  final Widget left, right;
  final int leftFlex, rightFlex;
  @override
  Widget build(BuildContext context) => wide
      ? IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(flex: leftFlex, child: left),
              const SizedBox(width: 16),
              Expanded(flex: rightFlex, child: right),
            ],
          ),
        )
      : Column(children: [left, const SizedBox(height: 16), right]);
}

/// Card with a title row; the body decides its own layout.
class _Panel extends StatelessWidget {
  const _Panel({
    required this.title,
    required this.child,
    this.subtitle,
    this.action,
  });
  final String title;
  final String? subtitle;
  final Widget child;
  final Widget? action;
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
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: theme.textTheme.titleMedium),
                      if (subtitle != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(
                            subtitle!,
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
                ?action,
              ],
            ),
            const SizedBox(height: 14),
            child,
          ],
        ),
      ),
    );
  }
}

class _Kpis extends StatelessWidget {
  const _Kpis(this.s);
  final _Summary s;
  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final rate = s.total == 0 ? 0 : (s.replied * 100 / s.total).round();
    final tiles = [
      _Kpi(
        label: 'Tracked applications',
        value: '${s.total}',
        detail: '${s.open} in progress · ${s.closed} closed',
        icon: Icons.work_outline,
        hue: colors.blue,
        onTap: () => context.go('/applications'),
      ),
      _Kpi(
        label: 'No reply yet',
        value: '${s.noReply}',
        detail: s.stale > 0
            ? '${s.stale} quiet for 30+ days'
            : 'Employer has not responded',
        icon: Icons.hourglass_bottom,
        hue: colors.amber,
        onTap: () => context.go('/applications?status=AWAITING_RESPONSE'),
      ),
      _Kpi(
        label: 'Interviews & offers',
        value: '${s.interviews + s.offers}',
        detail:
            '${s.interviews} interviewing/assessment · ${s.offers} offer${s.offers == 1 ? '' : 's'}',
        icon: Icons.forum_outlined,
        hue: colors.violet,
        onTap: () => context.go(
          s.offers > 0 && s.interviews == 0
              ? '/applications?status=OFFER'
              : '/applications?status=INTERVIEWING',
        ),
      ),
      _Kpi(
        label: 'Response rate',
        value: '$rate%',
        detail:
            '${s.replied} of ${s.total} heard back · ${s.closed} rejected/closed',
        icon: Icons.mark_email_read_outlined,
        hue: s.closed > s.interviews + s.offers ? colors.coral : colors.green,
        onTap: () => context.go('/applications?status=REJECTED'),
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 1100
            ? 4
            : constraints.maxWidth >= 640
            ? 2
            : 1;
        final width = (constraints.maxWidth - 16 * (columns - 1)) / columns;
        return Wrap(
          spacing: 16,
          runSpacing: 16,
          children: [
            for (final tile in tiles) SizedBox(width: width, child: tile),
          ],
        );
      },
    );
  }
}

class _Kpi extends StatelessWidget {
  const _Kpi({
    required this.label,
    required this.value,
    required this.detail,
    required this.icon,
    required this.hue,
    this.onTap,
  });
  final String label, value, detail;
  final IconData icon;
  final Color hue;

  /// Every number opens the list behind it.
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Stack(
          children: [
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              child: Container(width: 4, color: hue),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(22, 18, 18, 18),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          label,
                          style: theme.textTheme.labelLarge?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          value,
                          style: theme.textTheme.headlineMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          detail,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 12),
                  HueBadge(icon: icon, hue: hue, size: 40),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PipelineCard extends StatelessWidget {
  const _PipelineCard(this.s);
  final _Summary s;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final order = [
      ..._openStatuses,
      ..._closedStatuses,
    ].where((status) => s.of(status) > 0).toList();
    final stages = [
      ('Applied', s.total, context.colors.blue),
      ('Heard back', s.replied, context.colors.amber),
      (
        'Interview or assessment',
        s.interviews + s.offers,
        context.colors.violet,
      ),
      ('Offer', s.offers, context.colors.green),
    ];
    return _Panel(
      title: 'Pipeline',
      subtitle: 'Where every tracked application stands right now',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: SizedBox(
              height: 18,
              child: Row(
                children: [
                  for (final status in order)
                    Expanded(
                      flex: s.of(status),
                      child: Tooltip(
                        message: '${statusName(status)} · ${s.of(status)}',
                        child: Container(color: statusHue(context, status)),
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 14,
            runSpacing: 8,
            children: [
              for (final status in order)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        color: statusHue(context, status),
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      '${statusName(status)} ${s.of(status)}',
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                ),
            ],
          ),
          const SizedBox(height: 18),
          for (final (name, count, hue) in stages)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                children: [
                  SizedBox(
                    width: 170,
                    child: Text(name, style: theme.textTheme.bodyMedium),
                  ),
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(6),
                      child: LinearProgressIndicator(
                        minHeight: 10,
                        value: s.total == 0 ? 0 : count / s.total,
                        color: hue,
                        backgroundColor: theme.colorScheme.surfaceContainerHigh,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  SizedBox(
                    width: 70,
                    child: Text(
                      '$count · ${s.total == 0 ? 0 : (count * 100 / s.total).round()}%',
                      textAlign: TextAlign.right,
                      style: theme.textTheme.bodySmall?.copyWith(
                        fontFeatures: const [FontFeature.tabularFigures()],
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _AttentionCard extends StatelessWidget {
  const _AttentionCard(this.s);
  final _Summary s;
  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final gmailOk = const {'HEALTHY', 'CONNECTED', 'SYNCING'}.contains(s.gmail);
    final rows = [
      (
        Icons.notifications_none,
        colors.blue,
        'Unread notifications',
        '${s.unread}',
        '/notifications',
      ),
      (
        Icons.mail_outline,
        colors.violet,
        'Emails waiting for your decision',
        '${s.openReviews}',
        '/collection?route=%2Freviews&title=Review%20ambiguous%20updates',
      ),
      (
        Icons.star_outline,
        colors.amber,
        'Watchlist companies being scanned',
        '${s.watched}',
        '/watchlist',
      ),
      (
        gmailOk ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
        gmailOk ? colors.green : colors.coral,
        'Gmail sync',
        friendly(s.gmail),
        '/settings',
      ),
    ];
    return _Panel(
      title: 'Needs your attention',
      child: Column(
        children: [
          for (final (icon, hue, title, value, route) in rows)
            ListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              leading: HueBadge(icon: icon, hue: hue, size: 36),
              title: Text(title),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    value,
                    style: Theme.of(context).textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(width: 4),
                  const Icon(Icons.chevron_right, size: 18),
                ],
              ),
              onTap: () => context.go(route),
            ),
        ],
      ),
    );
  }
}

class _WeeklyCard extends StatelessWidget {
  const _WeeklyCard(this.s);
  final _Summary s;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final max = s.weekly.fold(0, (a, b) => a > b ? a : b);
    final recent = s.weekly.skip(8).fold(0, (a, b) => a + b);
    return _Panel(
      title: 'Applications per week',
      subtitle: 'Last 12 weeks · $recent in the last four',
      child: SizedBox(
        height: 150,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            for (var i = 0; i < s.weekly.length; i++)
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      Text(
                        s.weekly[i] == 0 ? '' : '${s.weekly[i]}',
                        style: theme.textTheme.labelSmall,
                      ),
                      const SizedBox(height: 4),
                      Tooltip(
                        message: i == s.weekly.length - 1
                            ? 'This week · ${s.weekly[i]}'
                            : '${s.weekly.length - 1 - i} week(s) ago · ${s.weekly[i]}',
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 300),
                          height: max == 0 ? 4 : 4 + 96 * s.weekly[i] / max,
                          decoration: BoxDecoration(
                            color: i == s.weekly.length - 1
                                ? theme.colorScheme.primary
                                : context.colors.blue.withValues(alpha: 0.55),
                            borderRadius: BorderRadius.circular(4),
                          ),
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        i == s.weekly.length - 1
                            ? 'now'
                            : '-${s.weekly.length - 1 - i}w',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _ActivityCard extends StatelessWidget {
  const _ActivityCard(this.s);
  final _Summary s;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return _Panel(
      title: 'Recent activity',
      subtitle: 'Latest status changes, newest first',
      child: s.recent.isEmpty
          ? Text(
              'Employer replies and your own updates will show here.',
              style: theme.textTheme.bodySmall,
            )
          : Column(
              children: [
                for (final event in s.recent.take(8))
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    leading: HueBadge(
                      icon: statusIcon(label(event['status'], '')),
                      hue: statusHue(context, label(event['status'], '')),
                      size: 34,
                    ),
                    title: Text(
                      label(event['company']),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text(
                      '${statusName(label(event['status'], ''))} · ${_shortDate(event['effective_at'])}'
                      '${event['actor'] == 'EMAIL' ? ' · from email' : ''}',
                    ),
                    onTap: () => context.push(
                      '/applications/${event['application_id']}',
                    ),
                  ),
              ],
            ),
    );
  }
}

class _WaitingCard extends StatelessWidget {
  const _WaitingCard(this.s);
  final _Summary s;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = s.waiting.take(6).toList();
    return _Panel(
      title: 'Waiting longest',
      subtitle: 'Applications with no employer reply — consider a follow-up or mark them closed',
      action: TextButton(
        onPressed: () => context.go('/applications'),
        child: const Text('All applications'),
      ),
      child: rows.isEmpty
          ? Text(
              'Nothing is waiting on an employer.',
              style: theme.textTheme.bodySmall,
            )
          : Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                for (final (row, age) in rows)
                  SizedBox(
                    width: 300,
                    child: Material(
                      color: theme.colorScheme.surfaceContainerLow,
                      borderRadius: BorderRadius.circular(12),
                      child: InkWell(
                        borderRadius: BorderRadius.circular(12),
                        onTap: () => context.push('/applications/${row['id']}'),
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Row(
                            children: [
                              CircleAvatar(
                                backgroundColor: context.colors.tint(
                                  hueFor(context, label(row['company'])),
                                  theme.brightness,
                                ),
                                foregroundColor: hueFor(
                                  context,
                                  label(row['company']),
                                ),
                                child: Text(
                                  label(
                                    row['company'],
                                    '?',
                                  ).trim().characters.first.toUpperCase(),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      label(row['company']),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: theme.textTheme.titleSmall,
                                    ),
                                    Text(
                                      label(row['title']),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: theme.textTheme.bodySmall,
                                    ),
                                  ],
                                ),
                              ),
                              const SizedBox(width: 8),
                              StatusPill(
                                '${age.inDays}d',
                                hue: age.inDays >= 30
                                    ? context.colors.coral
                                    : context.colors.amber,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
    );
  }
}

String _shortDate(Object? input) {
  final date = DateTime.tryParse(input?.toString() ?? '')?.toLocal();
  if (date == null) return 'date unknown';
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  return '${date.day} ${months[date.month - 1]}';
}
