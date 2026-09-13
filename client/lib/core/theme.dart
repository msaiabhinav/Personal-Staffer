import 'package:flutter/material.dart';
import 'package:flutter_riverpod/legacy.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Light palette follows the specification's visual defaults; dark keeps the same
/// hierarchy with a lifted teal so contrast stays accessible on dark surfaces.
class StafferPalette {
  const StafferPalette({
    required this.background,
    required this.surface,
    required this.surfaceLow,
    required this.surfaceHigh,
    required this.text,
    required this.muted,
    required this.accent,
    required this.onAccent,
    required this.border,
    required this.warning,
    required this.danger,
  });
  final Color background,
      surface,
      surfaceLow,
      surfaceHigh,
      text,
      muted,
      accent,
      onAccent,
      border,
      warning,
      danger;

  /// "Parchment": the logo's cream canvas, warm white cards, espresso ink, gold accent.
  static const light = StafferPalette(
    background: Color(0xfff8f5ee),
    surface: Color(0xfffffdf9),
    surfaceLow: Color(0xfff1ece2),
    surfaceHigh: Color(0xffe8e0d2),
    text: Color(0xff2b211b),
    muted: Color(0xff6f6157),
    accent: Color(0xffb8861f),
    onAccent: Color(0xff2b211b),
    border: Color(0xffe2d9c9),
    warning: Color(0xffa85d00),
    danger: Color(0xffb3261e),
  );

  /// "Espresso": the logo's dark roast canvas, layered warm-brown surfaces, gold accent.
  static const dark = StafferPalette(
    background: Color(0xff1a1411),
    surface: Color(0xff241c18),
    surfaceLow: Color(0xff2e2521),
    surfaceHigh: Color(0xff3a2f2a),
    text: Color(0xfff5efe5),
    muted: Color(0xffb5a696),
    accent: Color(0xffd6a548),
    onAccent: Color(0xff2b211b),
    border: Color(0xff453830),
    warning: Color(0xfff2b95a),
    danger: Color(0xffff8a80),
  );
}

/// Semantic hues used for color coding. Each kind of information keeps one hue in
/// both modes: location = blue, arrangement = violet, compensation = green,
/// experience = amber, alerts/priority = coral, reports = blue, applications = green.
@immutable
class StafferColors extends ThemeExtension<StafferColors> {
  const StafferColors({
    required this.blue,
    required this.violet,
    required this.green,
    required this.amber,
    required this.coral,
    required this.sidebar,
    required this.sidebarLow,
    required this.onSidebar,
    required this.onSidebarMuted,
    required this.shadow,
  });
  final Color blue, violet, green, amber, coral;
  final Color sidebar, sidebarLow, onSidebar, onSidebarMuted, shadow;

  // Semantic hues are kept distinct from the gold accent so status colour coding still
  // reads at a glance; they are warmed slightly to sit with the espresso/gold brand.
  static const light = StafferColors(
    blue: Color(0xff2f5fc4),
    violet: Color(0xff7048c8),
    green: Color(0xff2e7d32),
    amber: Color(0xffb45309),
    coral: Color(0xffc62828),
    // The logo badge colour: espresso sidebar with cream text and a gold selection bar.
    sidebar: Color(0xff2b211b),
    sidebarLow: Color(0xff382c25),
    onSidebar: Color(0xfff5efe5),
    onSidebarMuted: Color(0xffbfae9c),
    shadow: Color(0x142b211b),
  );
  static const dark = StafferColors(
    blue: Color(0xff8fb1ff),
    violet: Color(0xffbea6ff),
    green: Color(0xff6fd39a),
    amber: Color(0xfff2b95a),
    coral: Color(0xffff8a80),
    // A shade darker than the cards so the navigation reads as the logo badge.
    sidebar: Color(0xff130e0c),
    sidebarLow: Color(0xff1f1815),
    onSidebar: Color(0xfff5efe5),
    onSidebarMuted: Color(0xffb5a696),
    shadow: Color(0x00000000),
  );

  /// Tinted background for a semantic hue (works on both light and dark surfaces).
  Color tint(Color hue, Brightness brightness) =>
      hue.withValues(alpha: brightness == Brightness.dark ? 0.20 : 0.12);

  @override
  StafferColors copyWith() => this;
  @override
  StafferColors lerp(ThemeExtension<StafferColors>? other, double t) {
    if (other is! StafferColors) return this;
    Color mix(Color a, Color b) => Color.lerp(a, b, t) ?? a;
    return StafferColors(
      blue: mix(blue, other.blue),
      violet: mix(violet, other.violet),
      green: mix(green, other.green),
      amber: mix(amber, other.amber),
      coral: mix(coral, other.coral),
      sidebar: mix(sidebar, other.sidebar),
      sidebarLow: mix(sidebarLow, other.sidebarLow),
      onSidebar: mix(onSidebar, other.onSidebar),
      onSidebarMuted: mix(onSidebarMuted, other.onSidebarMuted),
      shadow: mix(shadow, other.shadow),
    );
  }
}

extension StafferColorsX on BuildContext {
  StafferColors get colors =>
      Theme.of(this).extension<StafferColors>() ?? StafferColors.light;
}

ThemeData stafferThemeFor(Brightness brightness) {
  final p = brightness == Brightness.dark
      ? StafferPalette.dark
      : StafferPalette.light;
  final scheme =
      ColorScheme.fromSeed(
        seedColor: p.accent,
        brightness: brightness,
      ).copyWith(
        primary: p.accent,
        onPrimary: p.onAccent,
        secondary: p.accent,
        onSecondary: p.onAccent,
        surface: p.surface,
        onSurface: p.text,
        onSurfaceVariant: p.muted,
        surfaceContainerLowest: p.surface,
        surfaceContainerLow: p.surfaceLow,
        surfaceContainer: p.surfaceLow,
        surfaceContainerHigh: p.surfaceHigh,
        surfaceContainerHighest: p.surfaceHigh,
        outline: p.border,
        outlineVariant: p.border,
        error: p.danger,
        primaryContainer: p.accent.withValues(alpha: 0.14),
        onPrimaryContainer: brightness == Brightness.dark
            ? p.accent
            : const Color(0xff7a5410),
        secondaryContainer: p.accent.withValues(alpha: 0.14),
        onSecondaryContainer: brightness == Brightness.dark
            ? p.accent
            : const Color(0xff7a5410),
        tertiary: p.warning,
      );
  final base = ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
  );
  final text = base.textTheme.apply(bodyColor: p.text, displayColor: p.text);
  const radius = 14.0;
  final semantic = brightness == Brightness.dark
      ? StafferColors.dark
      : StafferColors.light;
  return base.copyWith(
    extensions: [semantic],
    scaffoldBackgroundColor: p.background,
    canvasColor: p.background,
    dividerColor: p.border,
    textTheme: text.copyWith(
      headlineSmall: text.headlineSmall?.copyWith(
        fontWeight: FontWeight.w700,
        letterSpacing: -0.4,
      ),
      headlineMedium: text.headlineMedium?.copyWith(
        fontWeight: FontWeight.w700,
        letterSpacing: -0.5,
      ),
      titleLarge: text.titleLarge?.copyWith(fontWeight: FontWeight.w600),
      titleMedium: text.titleMedium?.copyWith(fontWeight: FontWeight.w600),
      labelMedium: text.labelMedium?.copyWith(
        color: p.muted,
        letterSpacing: 0.4,
      ),
      bodyMedium: text.bodyMedium?.copyWith(height: 1.4),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: p.surface,
      foregroundColor: p.text,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: text.titleLarge?.copyWith(
        fontWeight: FontWeight.w700,
        color: p.text,
      ),
    ),
    cardTheme: CardThemeData(
      color: p.surface,
      surfaceTintColor: Colors.transparent,
      shadowColor: semantic.shadow,
      elevation: brightness == Brightness.dark ? 0 : 1.5,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(radius),
        side: BorderSide(color: p.border),
      ),
    ),
    dividerTheme: DividerThemeData(color: p.border, space: 1, thickness: 1),
    navigationRailTheme: NavigationRailThemeData(
      backgroundColor: p.surface,
      indicatorColor: p.accent.withValues(alpha: 0.16),
      selectedIconTheme: IconThemeData(color: p.accent),
      unselectedIconTheme: IconThemeData(color: p.muted),
      selectedLabelTextStyle: text.titleSmall?.copyWith(
        color: p.text,
        fontWeight: FontWeight.w600,
      ),
      unselectedLabelTextStyle: text.titleSmall?.copyWith(color: p.muted),
      useIndicator: true,
      minExtendedWidth: 232,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: p.surface,
      indicatorColor: p.accent.withValues(alpha: 0.16),
      surfaceTintColor: Colors.transparent,
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          color: states.contains(WidgetState.selected) ? p.accent : p.muted,
        ),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => text.labelSmall?.copyWith(
          color: states.contains(WidgetState.selected) ? p.text : p.muted,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w600
              : FontWeight.normal,
        ),
      ),
    ),
    tabBarTheme: TabBarThemeData(
      labelColor: p.accent,
      unselectedLabelColor: p.muted,
      indicatorColor: p.accent,
      indicatorSize: TabBarIndicatorSize.label,
      dividerColor: p.border,
      labelStyle: text.titleSmall?.copyWith(fontWeight: FontWeight.w600),
      unselectedLabelStyle: text.titleSmall,
    ),
    dropdownMenuTheme: DropdownMenuThemeData(
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: p.surface,
        isDense: true,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 14,
          vertical: 12,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: p.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: p.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: p.accent, width: 1.6),
        ),
      ),
      menuStyle: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(p.surface),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: p.border),
          ),
        ),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: p.surfaceLow,
      selectedColor: p.accent.withValues(alpha: 0.18),
      side: BorderSide(color: p.border),
      labelStyle: text.labelMedium?.copyWith(color: p.text),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: p.muted,
      textColor: p.text,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.surface,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: p.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: p.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: p.accent, width: 1.6),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(48, 48),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 48),
        side: BorderSide(color: p.border),
        foregroundColor: p.text,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(48, 48),
        foregroundColor: p.accent,
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        selectedBackgroundColor: p.accent.withValues(alpha: 0.18),
        selectedForegroundColor: p.text,
        side: BorderSide(color: p.border),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: brightness == Brightness.dark ? p.surfaceHigh : p.text,
      contentTextStyle: text.bodyMedium?.copyWith(
        color: brightness == Brightness.dark ? p.text : p.surface,
      ),
      actionTextColor: p.accent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    ),
    badgeTheme: BadgeThemeData(
      backgroundColor: p.accent,
      textColor: p.onAccent,
    ),
    visualDensity: VisualDensity.standard,
  );
}

/// Persisted appearance preference (system / light / dark). It is device-local and
/// intentionally not part of the synchronized account state.
class ThemeController extends ChangeNotifier {
  ThemeController(this.storage);
  final FlutterSecureStorage storage;
  static const key = 'ui.theme_mode';
  ThemeMode mode = ThemeMode.system;

  Future<void> restore() async {
    try {
      final stored = await storage.read(key: key);
      mode = ThemeMode.values.firstWhere(
        (m) => m.name == stored,
        orElse: () => ThemeMode.system,
      );
    } on Object {
      mode = ThemeMode.system;
    }
    notifyListeners();
  }

  Future<void> set(ThemeMode value) async {
    if (mode == value) return;
    mode = value;
    notifyListeners();
    try {
      await storage.write(key: key, value: value.name);
    } on Object {
      // A preference that fails to persist still applies for this session.
    }
  }
}

final themeControllerProvider = ChangeNotifierProvider<ThemeController>(
  (ref) => ThemeController(const FlutterSecureStorage()),
);
