import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart';

import 'history.dart';
import 'repository.dart';
import 'models.dart';

final repositoryProvider = ChangeNotifierProvider<StafferRepository>(
  (ref) => throw StateError('Bootstrap must provide repository'),
);
final resourceProvider = FutureProvider.autoDispose.family<Json, String>((
  ref,
  route,
) {
  ref.watch(repositoryProvider.select((r) => r.revision));
  return ref.read(repositoryProvider).get(route);
});

/// Browser-style history for the shell's Back/Forward controls. Bootstrap
/// overrides this with the live router's history; tests may leave it null.
final navigationHistoryProvider = ChangeNotifierProvider<NavigationHistory?>(
  (ref) => null,
);
