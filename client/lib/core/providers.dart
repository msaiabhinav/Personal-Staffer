import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart';

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
