# Codex Review Checklist

Использовать при ревью каждого PR от Cursor. Обязательные пункты — отмечать явно в комментарии к PR.

## Architecture

- [ ] Изменения в `customs-clear/backend/`, не в legacy `backend/` без явной задачи
- [ ] Бизнес-логика в `app/services/`, не в роутерах
- [ ] NTM v2: `source_kind` изолирован; official vs legacy не смешаны в broker
- [ ] Только `definite` влияет на `required_permit_types` / `missing_permit_types` / ERROR
- [ ] `possible` / `needs_clarification` только в advisory
- [ ] Feature flags по умолчанию OFF, если в задаче не сказано иное

## Security

- [ ] Нет секретов, `.env`, API keys в diff
- [ ] Нет client-side AI keys
- [ ] Нет небезопасных default credentials

## Data & migrations

- [ ] Схема БД только через Alembic (`customs-clear/backend/alembic/versions/`)
- [ ] Импортеры идемпотентны
- [ ] Нет удаления строк из `non_tariff_measures` (только `quality='noise'`)

## NTM v2 rules

- [ ] Applicability соблюдён
- [ ] Нет грубого «любой HS → СГР/СС» без нормативного основания
- [ ] Official contour не включён в broker без явного enforcement PR

## Tests

- [ ] Указанные в issue тесты добавлены/прогнаны
- [ ] Регрессия по затронутому контуру (pytest или curl smoke)

## PR report completeness

- [ ] Summary, before/after, tests run, risks, follow-up
- [ ] Нет unrelated refactor
- [ ] Scope соответствует issue

## Verdict

- [ ] **Approve** — можно `ready-for-ivan-review`
- [ ] **Request changes** — создать corrective Cursor Task
- [ ] **Decision Memo needed** — не мержить до стратегического решения
