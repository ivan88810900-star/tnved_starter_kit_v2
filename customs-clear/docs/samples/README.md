# Примеры данных

## `user_decisions.jsonl.example`

Демонстрационные строки журнала подтверждённых ТН ВЭД (описание → код). Используются для обучения подсказок и тестов UI.

### Загрузить в рабочий журнал

Из каталога `customs-clear/backend`:

```bash
PYTHONPATH=. python3 scripts/seed_demo_journal.py --append
```

Повторный запуск **дублирует** строки; для чистого файла удалите `data/user_decisions.jsonl` или используйте другой `DECISIONS_LOG_PATH`.

После загрузки включите RAG (опционально):

```bash
export RAG_DOCS_DIR=../docs/rag_sources
```
