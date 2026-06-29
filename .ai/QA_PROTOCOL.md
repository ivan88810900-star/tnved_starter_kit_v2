# QA_PROTOCOL.md — Протокол проверки качества

> QA Engineer и любой исполнитель задачи обязаны следовать этому протоколу перед сдачей работы.

---

## 1. Главное правило

**Запрещено писать «тесты прошли» без фактического вывода команд.**

Каждый отчёт QA должен содержать:
- точную команду;
- полный или существенный фрагмент stdout/stderr;
- exit code (0 / non-zero).

Пример **плохого** отчёта:
> pytest прошёл успешно.

Пример **хорошего** отчёта:
```bash
cd customs-clear/backend && pytest tests/test_semantic_navigation_v1.py -v
# exit 0
# ===== 9 passed in 4.2s =====
```

---

## 2. Обязательные проверки по типу задачи

### 2.1 Backend (services, API)
```bash
cd customs-clear/backend
pytest tests/<relevant>.py -v
pytest tests/test_tnved_catalog_api.py -k children -v   # если трогали дерево
```

### 2.2 Semantic / Tree experimental layers
```bash
pytest tests/test_semantic_navigation_v1.py -v
pytest tests/test_tree_engine_v2.py -v
python scripts/diagnose_semantic_navigation.py
```

### 2.3 API smoke (если backend запущен на :8001)
```bash
curl -s http://127.0.0.1:8001/api/health/ready
curl -s http://127.0.0.1:8001/api/tnved/children/0302 | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('0302:', len(d.get('items',[])))"
# Ожидание: 0302: 45 (или актуальное эталонное значение из задачи)
```

### 2.4 Frontend
```bash
cd customs-clear/frontend
npm run build
npx tsc --noEmit
```

### 2.5 Git hygiene
```bash
git status
git diff --stat
git diff --name-status
```
Подтвердить: изменены только файлы из scope задачи.

---

## 3. Регрессионные эталоны дерева ТН ВЭД

При изменениях в `tnved_catalog.py`, `tnved_tree/`, `tree_engine/`:

| Endpoint | Ожидаемое кол-во children |
|----------|---------------------------|
| `/api/tnved/children/0302` | 45 |
| `/api/tnved/children/0304` | 48 |
| `/api/tnved/children/0805` | 7 |
| `/api/tnved/children/0101210000` | 0 |

Любое отклонение — **blocker**, если задача не меняла API намеренно.

---

## 4. Semantic Navigation — инварианты QA

Для задач в `semantic_navigation/`:

- [ ] Все реальные коды heading достижимы в дереве (0 missing)
- [ ] Нет fake-кодов (коды только из БД)
- [ ] Group-узлы не имеют поля `code`
- [ ] Validator: 0 critical issues
- [ ] `diagnose_semantic_navigation.py` — exit 0
- [ ] Production API не изменён

---

## 5. Формат QA-отчёта

```markdown
## QA Report: [TASK-ID]

### Commands run
1. `pytest tests/...` → **9 passed**, exit 0
2. `python scripts/diagnose_...` → exit 0, [краткое summary]
3. `git status` → только файлы из scope

### Regressions
- children 0302: 45 ✅
- children 8517: 9 ✅

### Blockers
- (none)

### Notes
- ...
```

---

## 6. Что считается blocker

- Любой failed test в scope регрессии
- Изменение API-контракта без задачи
- Потеря реальных кодов в semantic/tree слоях
- Critical validation issues
- Postоронние файлы в diff
- Push выполнен без разрешения

---

## 7. Что НЕ делает QA Engineer

- Не пишет production-код (только тесты и диагностику, если явно в scope)
- Не делает commit/push
- Не «закрывает глаза» на warnings, если они в scope задачи

---

*Создан: 2026-06-29. Часть AI Team Infrastructure — этап 1.*
