# TASK-SEMANTIC-003: Semantic Navigation — hierarchical grouping quality

> **Status:** ready  
> **Owner:** Backend Engineer (+ Architect review)  
> **Created:** 2026-06-29  
> **Depends on:** Semantic Navigation v1 этапы 1–2 (модуль + strict extraction + flat grouping)

---

## Goal

Улучшить **качество иерархии semantic-групп**: восстановить осмысленную вложенность (parent → child groups) без поглощения соседних групп и без регрессии инвариантов v1/v2.

---

## Context

Этапы 1–2 дали рабочий read-only слой `semantic_navigation/`:
- strict rejection (10 ГГц, generic «прочие», numeric ranges)
- confidence high/medium/low
- flat sibling groups под heading — **намеренно**, чтобы убрать bug «тунец 75 кодов» на 0303

**Проблемы flat-модели (этап 2 debt):**
1. **5208** — заголовок «полотняного переплетения» повторяется под «неотбеленные», «отбеленные», «окрашенные» как отдельные siblings; UX не отражает иерархию ТКС.
2. **0302/0303** — подгруппы тунца (синий, тихоокеанский, малый пятнистый) — siblings, а не children группы «тунец»; продуктово приемлемо для debug, но не для UI.
3. Нет использования **структуры кодов** (prefix / node_level) для привязки subgroup к parent group.

Продуктовая цель: `.ai/VISION.md` — пользователь должен видеть «лососевые → форель», а не плоский список.

---

## Scope

### In scope
- `customs-clear/backend/app/services/semantic_navigation/`
  - `extractor.py` — metadata для hierarchy hints (source dash depth, parent title hints)
  - `builder.py` — **controlled nesting**: subgroup может быть child parent group, если:
    - тот же heading;
    - subgroup активируется **после** parent и **до** следующего sibling parent;
    - не увеличивает span parent group beyond N кодов (guard от 0303 tuna swallowing)
  - `validator.py` — проверки: max depth, no group span > threshold без split, invariance real codes
- `scripts/diagnose_semantic_navigation.py` — показать tree depth, duplicate titles under different parents
- `tests/test_semantic_navigation_v1.py` — новые assertions

### Out of scope
- Подключение к API / frontend
- Изменение `_build_tree()` / `tnved_catalog.py`
- Virtual L5 / fake codes
- Commit/push (unless Ivan asks)

---

## Files / areas to inspect

```
customs-clear/backend/app/services/semantic_navigation/
customs-clear/backend/scripts/diagnose_semantic_navigation.py
customs-clear/backend/tests/test_semantic_navigation_v1.py
.ai/VISION.md
```

Reference: flat grouping fix in builder.py (этап 2), `node_level()` from `tnved_tree/helpers.py`.

---

## Required behavior

1. **5208:** «полотняного переплетения» под «неотбеленные» / «отбеленные» / «окрашенные» — **nested** `classification_subgroup` under respective parent group, not duplicate top-level siblings only by title collision in report.

2. **0303:** группа «тунец» — **не более 20** прямых commodity codes на top level под этой group (subgroups вынесены в children). Subgroups «тунец синий», «тунец тихоокеанский голубой», «тунец малый пятнистый» — children of «тунец» where activation order supports it.

3. **8517:** rejected candidates «10 ГГц», «1610 нм» — **remain rejected** (no regression).

4. **Invariants (must hold):**
   - 0 ungrouped real codes (or document exceptions)
   - 0 critical validator issues
   - 0 fake codes
   - Removing all group nodes leaves same set of real codes

5. **Guard:** если nesting восстанавливает swallowing (>30 codes under single group without subgroups) — fallback to flat for that segment + log in diagnose.

---

## Do not do

- Не менять production API, frontend, `_build_tree()`
- Не группировать по 5-й цифре кода (virtual L5)
- Не создавать synthetic HS codes для groups
- Не commit/push без Ivan
- Не ослаблять rejection rules этапа 2

---

## Tests

```bash
cd customs-clear/backend

pytest tests/test_semantic_navigation_v1.py -v
# Ожидание: all passed (including new hierarchy tests)

pytest tests/test_tree_engine_v2.py -v
pytest tests/test_tnved_catalog_api.py -k children -v

python scripts/diagnose_semantic_navigation.py
# Ожидание: exit 0; 0303 tuna group < 20 direct codes; 8517 no 10 ГГц in accepted
```

---

## Acceptance criteria

- [ ] 0302: groups лососевые, камбалообразные, тунец present; all real codes reachable
- [ ] 0303: «тунец» group has **< 20** direct commodity children (subgroups nested)
- [ ] 8517: no accepted groups «10 ГГц» / «1610 нм»; rejected list contains them
- [ ] 5208: «полотняного переплетения» nested under color groups (not only flat duplicate report lines)
- [ ] Validator: 0 critical issues on 0302, 0303, 5208, 8517
- [ ] QA report with **actual command output** per QA_PROTOCOL
- [ ] git diff only `semantic_navigation/`, diagnose script, tests

---

## Report format

Engineering report + QA report + short hierarchy diff for 0302/5208 (text tree fragment).

---

## Risks / notes

- Over-nesting may recreate 0303 swallowing — **max span guard** обязателен
- Title collision («полотняного переплетения») — различать по `extracted_from` source_code + parent chain, not title alone
- Future UI may need stable group `id` — consider deterministic id from (heading, title, source_code) in metadata only

---

## Suggested approach (Architect hint)

1. Two-pass build: (a) flat accepted groups as now; (b) promote subgroup → child if `after_code` falls within parent's code span.
2. Parent span = codes from parent activation index until next sibling parent activation.
3. If promotion would leave parent with >MAX_DIRECT commodities, keep flat and flag in diagnose.
