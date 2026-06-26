import 'package:json_annotation/json_annotation.dart';

part 'hs_code.g.dart';

@JsonSerializable()
class HSCode {
  final String code;
  final String titleRu;
  final String? titleEn;
  final String? chapter;
  final String? heading;
  final String? subheading;

  const HSCode({
    required this.code,
    required this.titleRu,
    this.titleEn,
    this.chapter,
    this.heading,
    this.subheading,
  });

  factory HSCode.fromJson(Map<String, dynamic> json) => _$HSCodeFromJson(json);
  Map<String, dynamic> toJson() => _$HSCodeToJson(this);
}

@JsonSerializable()
class HSCodeDetail {
  final HSCode hsCode;
  final List<TariffRate> tariffRates;
  final List<NTMMeasure> ntmMeasures;
  final List<Note> notes;

  const HSCodeDetail({
    required this.hsCode,
    required this.tariffRates,
    required this.ntmMeasures,
    required this.notes,
  });

  factory HSCodeDetail.fromJson(Map<String, dynamic> json) => _$HSCodeDetailFromJson(json);
  Map<String, dynamic> toJson() => _$HSCodeDetailToJson(this);
}

@JsonSerializable()
class TariffRate {
  final String duty;
  final String vat;
  final String? add;
  final String sourceVersion;

  const TariffRate({
    required this.duty,
    required this.vat,
    this.add,
    required this.sourceVersion,
  });

  factory TariffRate.fromJson(Map<String, dynamic> json) => _$TariffRateFromJson(json);
  Map<String, dynamic> toJson() => _$TariffRateToJson(this);
}

@JsonSerializable()
class NTMMeasure {
  final String title;
  final String basis;
  final String? country;
  final String? notes;

  const NTMMeasure({
    required this.title,
    required this.basis,
    this.country,
    this.notes,
  });

  factory NTMMeasure.fromJson(Map<String, dynamic> json) => _$NTMMeasureFromJson(json);
  Map<String, dynamic> toJson() => _$NTMMeasureToJson(this);
}

@JsonSerializable()
class Note {
  final String level;
  final String refId;
  final String text;

  const Note({
    required this.level,
    required this.refId,
    required this.text,
  });

  factory Note.fromJson(Map<String, dynamic> json) => _$NoteFromJson(json);
  Map<String, dynamic> toJson() => _$NoteToJson(this);
}


