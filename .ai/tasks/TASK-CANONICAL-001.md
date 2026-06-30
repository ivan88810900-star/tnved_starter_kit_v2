# TASK-CANONICAL-001

> **Status:** ready
> **Owner:** Backend Engineer (+ Architect review)
> **Created:** 2026-06-30
> **Depends on:** ADR-0001 — Canonical TNVED Model (`.ai/decisions/ADR-0001-canonical-tnved-model.md`)

## Title

Canonical TNVED Model — deterministic stable_id and recovery stage skeleton

## Goal

Подготовить первый технический шаг по реализации ADR-0001.
Цель — создать фундамент Canonical TNVED Model без изменения production-поведения.

## Background

ADR-0001 зафиксировал:
- Canonical TNVED Model — центральная source-of-truth модель Tariff;
- Recovery — стадия внутри `tree_engine`, а не отдельный top-level module;
- legacy `_build_tree()` остаётся production и oracle до parity;
- Semantic Navigation позже должен перейти на Canonical Model;
- stable_id обязателен до Search/RAG/AI-журнала.

Сейчас `tree_engine` использует недетерминированные `uuid4()` id. Это несовместимо с будущими RAG, Search, AI Classification и Knowledge Graph.

## Scope

Разрешённые изменения только в:
- `customs-clear/backend/app/services/tree_engine/`
- `customs-clear/backend/tests/test_tree_engine_v2.py`
- при необходимости: новый тестовый файл `customs-clear/backend/tests/test_canonical_tnved_model.py`

## Out of Scope

Запрещено:
- менять `tnved_catalog.py`;
- менять `_build_tree()`;
- менять production API;
- менять frontend;
- менять `semantic_navigation`;
- менять БД;
- подключать Canonical Model к runtime;
- удалять legacy build_tree;
- делать push.

## Required Work

1. Добавить deterministic `stable_id` для узлов `tree_engine`.
2. Убрать зависимость от случайного `uuid4()` в новой canonical path.
3. Добавить `snapshot_id` как часть модели или metadata.
4. Создать skeleton стадии:
   `customs-clear/backend/app/services/tree_engine/recovery.py`
   Внутри:
   - `StructureNormalizer`;
   - минимальный метод `normalize(...)`;
   - пока без переноса логики L6/L8/pad;
   - документировать, что фактический перенос recovery будет в TASK-CANONICAL-002.
5. Обновить `TreeBuilder` только настолько, чтобы он мог использовать deterministic IDs без изменения структуры.
6. Добавить тесты:
   - две сборки одного и того же дерева дают одинаковые IDs;
   - `stable_id` не пустой;
   - нет `uuid4`-подобной нестабильности;
   - структура дерева не изменилась;
   - сериализация legacy-compatible не изменилась;
   - `tests/test_tree_engine_v2.py` проходит.

## Acceptance Criteria

- [ ] `tree_engine` строит те же узлы, что и раньше;
- [ ] структура дерева не меняется;
- [ ] `stable_id` детерминирован;
- [ ] `snapshot_id` присутствует;
- [ ] `StructureNormalizer` существует как skeleton;
- [ ] production API не изменён;
- [ ] frontend не изменён;
- [ ] `_build_tree()` не изменён;
- [ ] `semantic_navigation` не изменён;
- [ ] все релевантные тесты проходят.

## QA Requirements

Выполнить:

```bash
cd customs-clear/backend

pytest tests/test_tree_engine_v2.py -v
pytest tests/test_tnved_catalog_api.py -k children -v

# Если создан новый тест:
pytest tests/test_canonical_tnved_model.py -v
```

Также показать:

```bash
git status
git diff --stat
git diff --name-status
```

## Risks

- Возможна несовместимость старого id и нового stable_id.
- Нельзя менять публичный API.
- Нельзя ломать legacy serializer.
- Нельзя смешивать эту задачу с переносом `_build_tree()`.

## Commit Rules

- Commit только после QA и review.
- Push запрещён без прямого разрешения Ivan.
