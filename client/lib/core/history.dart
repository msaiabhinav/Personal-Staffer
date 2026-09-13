import 'package:flutter/foundation.dart';
import 'package:go_router/go_router.dart';

/// Browser-style navigation history for the shell: every visited location is
/// recorded; Back and Forward move through the list without losing the rest.
///
/// go_router's own stack is replaced by `context.go`, so this keeps an
/// independent linear history the way a browser does.
class NavigationHistory extends ChangeNotifier {
  NavigationHistory(this.router) {
    router.routerDelegate.addListener(_onRouteChanged);
    _record(_currentLocation());
  }
  final GoRouter router;
  final List<String> entries = [];
  int index = -1;
  bool _traversing = false;

  bool get canGoBack => index > 0;
  bool get canGoForward => index >= 0 && index < entries.length - 1;
  String? get current => index >= 0 ? entries[index] : null;

  String _currentLocation() {
    final config = router.routerDelegate.currentConfiguration;
    // A pushed (imperative) page is the one on screen; the configuration's own uri
    // still names the declarative page underneath it.
    final top = config.matches.isEmpty ? null : config.last;
    if (top is ImperativeRouteMatch) return top.matches.uri.toString();
    return config.uri.toString();
  }

  void _onRouteChanged() {
    if (_traversing) return;
    _record(_currentLocation());
  }

  void _record(String location) {
    if (location.isEmpty) return;
    // Login redirects are transient; do not let them occupy history.
    if (location.startsWith('/login')) return;
    if (index >= 0 && entries[index] == location) return;
    entries.removeRange(index + 1, entries.length);
    entries.add(location);
    if (entries.length > 200) entries.removeAt(0);
    index = entries.length - 1;
    notifyListeners();
  }

  Future<void> back() => _travel(-1);
  Future<void> forward() => _travel(1);

  Future<void> _travel(int delta) async {
    final target = index + delta;
    if (target < 0 || target >= entries.length) return;
    _traversing = true;
    index = target;
    try {
      router.go(entries[index]);
      // Let the delegate notify before recording resumes.
      await Future<void>.delayed(Duration.zero);
    } finally {
      _traversing = false;
    }
    notifyListeners();
  }

  @override
  void dispose() {
    router.routerDelegate.removeListener(_onRouteChanged);
    super.dispose();
  }
}
