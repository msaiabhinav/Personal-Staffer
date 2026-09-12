import 'dart:convert';

typedef Json = Map<String, dynamic>;
Json object(Object? value) =>
    value is Map ? Map<String, dynamic>.from(value) : {};
List<Json> objects(Object? value) =>
    value is List ? value.map(object).toList() : [];
String label(Object? value, [String fallback = 'Not stated']) =>
    value == null || value.toString().isEmpty ? fallback : value.toString();
String friendly(Object? value) =>
    label(value).replaceAll('_', ' ').toLowerCase();

class PendingOperation {
  const PendingOperation({
    required this.id,
    required this.account,
    required this.command,
    required this.target,
    required this.payload,
    required this.createdAt,
    this.state = 'pending',
    this.error,
  });
  final String id, account, command, target, state;
  final Json payload;
  final DateTime createdAt;
  final String? error;
  Json toJson() => {
    'operation_id': id,
    'account': account,
    'command': command,
    'target_id': target,
    'payload': payload,
    'created_at': createdAt.toUtc().toIso8601String(),
    'state': state,
    'error': error,
  };
  factory PendingOperation.fromJson(Json j) => PendingOperation(
    id: j['operation_id'],
    account: j['account'],
    command: j['command'],
    target: j['target_id'],
    payload: object(j['payload']),
    createdAt: DateTime.parse(j['created_at']),
    state: j['state'] ?? 'pending',
    error: j['error'],
  );
  Json forServer() => {
    'operation_id': id,
    'command': command,
    'target_id': target,
    'payload': payload,
  };
  PendingOperation failed(String message) => PendingOperation(
    id: id,
    account: account,
    command: command,
    target: target,
    payload: payload,
    createdAt: createdAt,
    state: 'conflict',
    error: message,
  );
  String encode() => jsonEncode(toJson());
}

/// Only known internal entity destinations are accepted. External schemes,
/// credentials, extra segments and arbitrary callback query data never execute.
String? internalDestination(String? value) {
  if (value == null) return null;
  final uri = Uri.tryParse(value);
  if (uri == null ||
      uri.hasQuery ||
      uri.hasFragment ||
      uri.userInfo.isNotEmpty) {
    return null;
  }
  final parts = uri.scheme == 'personalstaffer'
      ? [uri.host, ...uri.pathSegments]
      : uri.scheme.isEmpty && !uri.hasAuthority
      ? uri.pathSegments
      : <String>[];
  if (parts.length != 2 ||
      !{
        'jobs',
        'applications',
        'reviews',
        'reports',
        'search-runs',
        'notifications',
      }.contains(parts[0])) {
    return null;
  }
  if (!RegExp(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$').hasMatch(parts[1])) {
    return null;
  }
  return '/${parts.join('/')}';
}

Uri? externalDestination(String? value) {
  if (value == null) return null;
  final uri = Uri.tryParse(value);
  return uri != null &&
          {'https', 'http'}.contains(uri.scheme) &&
          uri.host.isNotEmpty &&
          uri.userInfo.isEmpty
      ? uri
      : null;
}
