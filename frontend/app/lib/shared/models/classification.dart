import 'package:json_annotation/json_annotation.dart';

part 'classification.g.dart';

@JsonSerializable()
class ClassificationRequest {
  final String? text;
  final String? imageB64;
  final List<String>? hints;

  const ClassificationRequest({
    this.text,
    this.imageB64,
    this.hints,
  });

  factory ClassificationRequest.fromJson(Map<String, dynamic> json) => _$ClassificationRequestFromJson(json);
  Map<String, dynamic> toJson() => _$ClassificationRequestToJson(this);
}

@JsonSerializable()
class ClassificationResult {
  final String hsCode;
  final double confidence;
  final List<String> rationale;
  final List<Alternative> alternatives;
  final bool? validated;
  final String? titleRu;
  final String? titleEn;
  final List<String>? clarificationQuestions;
  final bool? offlineMode;

  const ClassificationResult({
    required this.hsCode,
    required this.confidence,
    required this.rationale,
    required this.alternatives,
    this.validated,
    this.titleRu,
    this.titleEn,
    this.clarificationQuestions,
    this.offlineMode,
  });

  factory ClassificationResult.fromJson(Map<String, dynamic> json) => _$ClassificationResultFromJson(json);
  Map<String, dynamic> toJson() => _$ClassificationResultToJson(this);
}

@JsonSerializable()
class Alternative {
  final String code;
  final String titleRu;
  final double confidence;

  const Alternative({
    required this.code,
    required this.titleRu,
    required this.confidence,
  });

  factory Alternative.fromJson(Map<String, dynamic> json) => _$AlternativeFromJson(json);
  Map<String, dynamic> toJson() => _$AlternativeToJson(this);
}

@JsonSerializable()
class AuditLog {
  final int id;
  final String hsCode;
  final String description;
  final double confidence;
  final List<String> rationale;
  final DateTime createdAt;

  const AuditLog({
    required this.id,
    required this.hsCode,
    required this.description,
    required this.confidence,
    required this.rationale,
    required this.createdAt,
  });

  factory AuditLog.fromJson(Map<String, dynamic> json) => _$AuditLogFromJson(json);
  Map<String, dynamic> toJson() => _$AuditLogToJson(this);
}


