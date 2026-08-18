# DM-0010 — Правовые контуры NTM и fail-closed полнота каталога

> **Status:** Accepted implementation boundary — full gate passed
> **Date:** 2026-08-15
> **Owner:** Ivan
> **Decision basis:** approved advisory-only rollout; enforcement is not approved

## Context

Структурная полнота NTM-кода и полнота проверки товарного каталога — разные
утверждения.

Реализованный контур содержит девять семейств и индекс 30 базовых разделов
Решения Коллегии ЕЭК №30. В нём также есть актуальные advisory-кандидаты СГР по
Решению КТС №299, ветеринарного контроля по Решению КТС №317,
фитосанитарного контроля высокого/низкого риска по Решениям №318/157,
РЭС/ВЧУ, криптографии, технических регламентов, национальных мер РФ и
экспортного контроля. Это доказывает наличие структурного маршрута проверки, но
не применимость документа ко всем товарам.

После исправления parser baseline все 96 tracked official PDFs по группам были
повторно собраны во временный audit-only SQLite artifact. Full audit открыл этот
artifact read-only; production/application DB не заменялась и не изменялась.
Текущий код NTM прошёл полный gate:

- 21 раздел и 96 групп;
- 17 809 строк и 17 809 уникальных commodity-кодов;
- 0 дубликатов и 0 невалидных кодов;
- 17 774 непустых описания;
- 35 пустых десятизначных catalog codes, каждый из которых отсутствует в
  pinned active ETT rate snapshot; из этого отсутствия не делается вывод о
  причине или юридическом статусе кода;
- все 13 290 кодов active ETT revision `ett:2026-06-18` присутствуют и имеют
  описание.

Pinned baseline `ntm-full-catalog-reference-20260815` фиксирует exact source и
output digests:

| Boundary | SHA-256 |
|----------|---------|
| Manifest 96 tracked PDFs | `05d953c993f5ae10557d385ece0ef201dcce3f76d387e622d98d8da223daed41` |
| Parser `scripts/tnved_pdf_parser.py` | `a74f1150806ab12c52dd73dfade1f44b928888f877e67500dd42b58e23d1307f` |
| Active ETT `ett:2026-06-18` code set | `2f901b2ed745994d248ddd96899f0d0a286e8bb30d9735688c6ac2a0c2187891` |
| Rebuilt catalog code set | `717df6eeb874f9fd1a8def26aa13bb3d720c1335216d5b040c560bae7d80d945` |
| Rebuilt catalog code + description | `649b3ab0d1c7042baaad1ac37d0f07dab4627b0486f8cc2c16db87f1660c0f63` |

Gate подтвердил `pdf_source_manifest_match=true`,
`catalog_parser_match=true`, `active_ett_snapshot_match=true` и exact baseline
совпадение section set, chapter set, code set и code+description output.

Основное aggregate-only evidence текущего прогона —
[required full gate](../../docs/ai-workflow/evidence/ntm-full-gate-20260815.json):
`ok=true`, `structural_ok=true`, `audit_scope=full_commodity_catalog`,
`catalog_complete=true`, 9/9 семейств, 30/30 базовых разделов и 0 enforcement
leaks.

Два ранних отчёта сохраняются как supplementary diagnostics, а не как итоговая
полнота:

- [ETT code-only scope](../../docs/ai-workflow/evidence/ntm-code-scope-20260815.json) —
  13 290 позиций, `code_catalog_complete=true`, `catalog_complete=false`;
- [partial described backup](../../docs/ai-workflow/evidence/ntm-partial-catalog-20260815.json) —
  13 979 уникальных описанных позиций, только явный partial success.

Исторический MVP-отчёт от 2026-07-21 остаётся отдельным доказательством другой
поставленной пользовательской БД. Новый отчёт выше является самостоятельным
прогоном текущей версии NTM по rebuilt official-PDF каталогу.

## Decision

Принят **fail-closed** контракт полноты:

1. Термин `full catalog` допустим только при одновременном выполнении текущего
   gate: exact baseline sets из 21 раздела, 96 групп и 17 809 уникальных
   commodities; 17 774 непустых описания; 0 дубликатов и 0 невалидных кодов;
   pinned manifest/parser/ETT/catalog digests; нелимитированное read-only чтение
   audit artifact. Все 13 290 кодов active ETT reference должны присутствовать и
   иметь описание.
2. ETT code-only scope из 13 290 кодов может подтверждать только кодовую и
   структурную диагностику. Он не подтверждает description-conditioned меры.
3. Partial backup нельзя автоматически объединять с ETT и выдавать результат за
   единый полный snapshot.
4. `--allow-partial` является только явным диагностическим режимом. Его успех не
   повышается до `catalog_complete=true`.
5. При отсутствии полного DB-каталога или при пропуске/пустом описании active ETT
   кода обычный full-audit завершается fail-closed (`ok=false`, отдельный
   non-zero exit для отсутствующей полноты) и перечисляет причины gate failure.
6. `not_detected` означает лишь отсутствие совпадения в подключённых контурах, а
   не юридическое отсутствие меры.

## Legal applicability boundary

- Любой prefix, строка «из» или marker из свободного описания остаётся
  `needs_clarification`.
- Решение №299 требует совместной проверки кода, наименования, назначения и
  исключений; issuer фиксируется как Комиссия Таможенного союза.
- Ветеринарный контроль не означает автоматически один универсальный документ
  `ВС`.
- Для фитосанитарных мер различаются высокий риск (advisory-кандидат ФСС) и
  низкий риск (без ФСС по одному факту включения в перечень).
- В экспортном контроле отдельно показываются 1 087 raw и 1 085 effective
  кандидатов; два retired exact-кода не участвуют в runtime.
- Ни один из этих контуров не участвует в enforcement без нового решения Ivan.

## Accepted option — fail closed

Показывать фактический scope каждого прогона (`full_commodity_catalog`,
`partial_commodity_catalog`, `code_only_catalog` или limited sample) и запрещать
ложное повышение частичного результата до полного.

### Benefits

- невозможно заявить проверку всех товаров без полного описанного snapshot;
- кодовая диагностика ETT остаётся полезной и честно маркированной;
- legal-условия и data-coverage не смешиваются;
- отсутствие данных не превращается в ложный чистый результат.

### Cost

Каждая новая редакция PDF/ETT или parser требует повторной rebuild-проверки.
Code-only и partial отчёты не могут заменить full gate, даже если их
структурная диагностика зелёная.

## Rejected alternatives

### Promote 13 290 ETT codes to full coverage

Отклонено: bundle не содержит 17 809 товарных описаний и не может проверить
условия по назначению, составу и виду товара.

### Merge the partial backup and ETT implicitly

Отклонено: источники имеют разные scope/revision и не образуют доказанный единый
snapshot; такое объединение скрывает пропуски и дубликаты.

## Completion evidence

Критерий выполнен 2026-08-15 на временном audit-only SQLite artifact, rebuilt из
96 tracked official PDFs и открытом audit-процессом read-only. Production DB не
изменялась. Отчёт содержит `catalog_complete=true`, `full_catalog_verified=true`,
`active_ett_description_complete=true`, 17 809/17 809 уникальных позиций,
17 774 непустых описания, 35 disclosed blank catalog codes absent from the pinned
active ETT rate snapshot, нулевые duplicate/invalid rows и нулевые enforcement
leaks. Manifest/parser/ETT/code/code+description digests совпали с pinned
baseline.

Этот результат относится к зафиксированным source revisions и текущему коду.
Он не отменяет обязательный повторный gate при обновлении PDF, active ETT
reference или parser.

## Decision record

Этот fail-closed boundary является обязательным условием принятого Ivan
advisory-only rollout от 2026-08-15. Full gate текущей версии прошёл на rebuilt
official-PDF каталоге; решение по-прежнему не разрешает enforcement.
