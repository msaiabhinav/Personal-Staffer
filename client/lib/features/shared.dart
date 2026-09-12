import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/providers.dart';

class ResourceView extends ConsumerStatefulWidget {
  const ResourceView({super.key, required this.route, required this.builder});
  final String route;
  final Widget Function(Json) builder;
  @override
  ConsumerState<ResourceView> createState() => _ResourceViewState();
}

class _ResourceViewState extends ConsumerState<ResourceView> {
  Json? original, current;
  final extra = <Json>[];
  bool loadingMore = false;
  String? pageError;
  @override
  void didUpdateWidget(covariant ResourceView old) {
    super.didUpdateWidget(old);
    if (old.route != widget.route) {
      original = null;
      current = null;
      extra.clear();
    }
  }

  Future<void> next() async {
    final cursor = current?['next_cursor'];
    if (cursor == null || loadingMore) return;
    final base = Uri.parse(widget.route);
    final next = base
        .replace(
          queryParameters: {
            ...base.queryParameters,
            'cursor': cursor.toString(),
          },
        )
        .toString();
    final repo = ref.read(repositoryProvider);
    final account = repo.account;
    setState(() {
      loadingMore = true;
      pageError = null;
    });
    try {
      final page = await repo.get(next);
      if (!mounted || repo.account != account) return;
      setState(() {
        extra.addAll(objects(page['items']));
        current = page;
      });
      await repo.cache.write(account, widget.route, {
        ...original!,
        'items': [...objects(original!['items']), ...extra],
        'next_cursor': page['next_cursor'],
        'has_more': page['next_cursor'] != null,
      });
    } on ApiError catch (e) {
      if (mounted) setState(() => pageError = e.message);
    } finally {
      if (mounted) setState(() => loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) => ref
      .watch(resourceProvider(widget.route))
      .when(
        data: (data) {
          if (!identical(original, data)) {
            original = data;
            current = data;
            extra.clear();
          }
          final combined = {
            ...data,
            if (data['items'] is List)
              'items': [...objects(data['items']), ...extra],
            'has_more': false,
            'next_cursor': null,
          };
          return Column(
            children: [
              if (data['_cached'] == true)
                const StatusStrip(
                  'Offline · Showing the last synchronized record',
                  icon: Icons.cloud_off_outlined,
                ),
              Expanded(child: widget.builder(combined)),
              if (pageError != null) StatusStrip(pageError!),
              if (current?['next_cursor'] != null)
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: OutlinedButton(
                    onPressed: loadingMore ? null : next,
                    child: Text(loadingMore ? 'Loading more…' : 'Load more'),
                  ),
                ),
            ],
          );
        },
        loading: () => const LoadingRows(),
        error: (error, stack) => EmptyMessage(
          title: error is ApiError && error.status == 404
              ? 'Record unavailable'
              : 'Could not load this view',
          message: error.toString(),
          action: FilledButton.tonal(
            onPressed: () => ref.invalidate(resourceProvider(widget.route)),
            child: const Text('Try again'),
          ),
        ),
      );
}

class LoadingRows extends StatelessWidget {
  const LoadingRows({super.key});
  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Loading records',
    child: ListView(
      padding: const EdgeInsets.all(24),
      children: List.generate(
        4,
        (i) => Padding(
          padding: const EdgeInsets.only(bottom: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                height: 16,
                width: 240,
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
              ),
              const SizedBox(height: 12),
              Container(
                height: 12,
                width: 360,
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class EmptyMessage extends StatelessWidget {
  const EmptyMessage({
    super.key,
    required this.title,
    required this.message,
    this.action,
    this.icon,
  });
  final String title, message;
  final Widget? action;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (icon != null) ...[
                Container(
                  width: 52,
                  height: 52,
                  decoration: BoxDecoration(
                    color: scheme.primaryContainer,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Icon(icon, color: scheme.onPrimaryContainer, size: 28),
                ),
                const SizedBox(height: 20),
              ],
              Text(title, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 12),
              Text(
                message,
                style: Theme.of(context).textTheme.bodyLarge
                    ?.copyWith(color: scheme.onSurfaceVariant),
              ),
              if (action != null) ...[const SizedBox(height: 24), action!],
            ],
          ),
        ),
      ),
    );
  }
}

/// Consistent page title block used by primary destinations.
class PageHeader extends StatelessWidget {
  const PageHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.trailing,
  });
  final String title;
  final String? subtitle;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: theme.textTheme.headlineSmall),
                if (subtitle != null) ...[
                  const SizedBox(height: 6),
                  Text(
                    subtitle!,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (trailing != null) ...[const SizedBox(width: 16), trailing!],
        ],
      ),
    );
  }
}

enum PillTone { neutral, positive, warning, accent }

/// Small rounded status label; never relies on color alone because it carries text.
class StatusPill extends StatelessWidget {
  const StatusPill(
    this.text, {
    super.key,
    this.tone = PillTone.neutral,
    this.icon,
  });
  final String text;
  final PillTone tone;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (Color background, Color foreground) = switch (tone) {
      PillTone.positive => (
        scheme.primary.withValues(alpha: 0.16),
        scheme.onPrimaryContainer,
      ),
      PillTone.warning => (
        scheme.tertiary.withValues(alpha: 0.18),
        scheme.tertiary,
      ),
      PillTone.accent => (scheme.primary, scheme.onPrimary),
      PillTone.neutral => (
        scheme.surfaceContainerHigh,
        scheme.onSurfaceVariant,
      ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 14, color: foreground),
            const SizedBox(width: 4),
          ],
          Text(
            text,
            style: Theme.of(context).textTheme.labelMedium
                ?.copyWith(color: foreground, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

class StatusStrip extends StatelessWidget {
  const StatusStrip(
    this.text, {
    super.key,
    this.icon = Icons.info_outline,
    this.action,
  });
  final String text;
  final IconData icon;
  final Widget? action;
  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.surfaceContainerLow,
      child: Container(
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: scheme.outlineVariant)),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
        child: Row(
          children: [
            Icon(icon, size: 20, color: scheme.primary),
            const SizedBox(width: 12),
            Expanded(child: Text(text)),
            ?action,
          ],
        ),
      ),
    );
  }
}

class DetailPage extends StatelessWidget {
  const DetailPage({
    super.key,
    required this.title,
    required this.child,
    this.actions = const [],
  });
  final String title;
  final Widget child;
  final List<Widget> actions;
  @override
  Widget build(BuildContext context) => Column(
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 20, 12),
        child: Row(
          children: [
            BackButton(
              onPressed: () {
                if (context.canPop()) {
                  context.pop();
                } else {
                  context.go('/home');
                }
              },
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(title, style: Theme.of(context).textTheme.titleLarge),
            ),
            ...actions,
          ],
        ),
      ),
      const Divider(height: 1),
      Expanded(child: child),
    ],
  );
}

class Field extends StatelessWidget {
  const Field(this.name, this.value, {super.key});
  final String name;
  final Object? value;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(name, style: Theme.of(context).textTheme.labelMedium),
        const SizedBox(height: 3),
        SelectableText(
          value is List
              ? (value as List).map((v) => label(v)).join(' · ')
              : label(value),
        ),
      ],
    ),
  );
}

Future<void> openExternal(BuildContext context, String? value) async {
  final uri = externalDestination(value);
  if (uri == null) {
    showMessage(context, 'No retained link is available.');
    return;
  }
  try {
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication) &&
        context.mounted) {
      showMessage(
        context,
        'Could not open this link. Check your default browser.',
      );
    }
  } on Object {
    if (context.mounted) showMessage(context, 'Could not open this link.');
  }
}

void showMessage(BuildContext context, String message, {VoidCallback? undo}) =>
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        duration: Duration(seconds: undo == null ? 5 : 10),
        action: undo == null
            ? null
            : SnackBarAction(label: 'Undo', onPressed: undo),
      ),
    );
String dateLabel(Object? input) {
  final date = DateTime.tryParse(input?.toString() ?? '');
  if (date == null) return 'Not stated';
  return '${date.toLocal().year}-${date.toLocal().month.toString().padLeft(2, '0')}-${date.toLocal().day.toString().padLeft(2, '0')} ${date.toLocal().hour.toString().padLeft(2, '0')}:${date.toLocal().minute.toString().padLeft(2, '0')} local';
}

String salaryLabel(Object? value) {
  final salary = object(value);
  if (salary.isEmpty) return label(value);
  final low = salary['minimum'], high = salary['maximum'];
  if (low == null && high == null) return 'Not stated';
  final range = low == high
      ? '$low'
      : low == null
      ? 'Up to $high'
      : high == null
      ? 'From $low'
      : '$low–$high';
  return '$range ${label(salary['currency'], 'currency not stated')} / ${friendly(salary['interval'])}';
}

String publicationLabel(Json job) {
  if (job['published_at'] != null) return dateLabel(job['published_at']);
  if (job['published_earliest'] != null && job['published_latest'] != null) {
    return 'Between ${dateLabel(job['published_earliest'])} and ${dateLabel(job['published_latest'])} (${friendly(job['publication_precision'])} precision)';
  }
  return 'Publication time not verified';
}
