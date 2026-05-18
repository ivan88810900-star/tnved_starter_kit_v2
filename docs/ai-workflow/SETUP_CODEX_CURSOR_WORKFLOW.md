# Настройка workflow для Ivan (product owner)

Пошаговая инструкция без предположения, что вы разработчик. Репозиторий уже на GitHub (private).

## 1. Codex GitHub Review

1. Откройте [ChatGPT](https://chatgpt.com) → **Codex** (или раздел с доступом к репозиториям).
2. Подключите GitHub-аккаунт, если ещё не подключён: **Settings → Connectors → GitHub**.
3. Дайте Codex доступ к репозиторию **tnved_starter_kit_v2** (только этот repo, private).
4. В чате с Codex можно попросить: «Review PR #N в tnved_starter_kit_v2 по AGENTS.md и CODEX_REVIEW_CHECKLIST.md».

## 2. Automatic reviews (ревью PR)

В настройках Codex / GitHub integration (названия могут отличаться в UI):

- Включите **review pull requests** для `tnved_starter_kit_v2`, если доступно.
- Укажите, что репозиторий **private** — доступ уже выдан на шаге 1.

Если автоматического ревью нет в UI — достаточно **Codex Automation** (шаг 3) или ручного запроса после каждого PR.

## 3. Codex Automation

Создайте automation (расписание или после merge), вставьте промпт из [CODEX_AUTOMATION_PROMPT.md](./CODEX_AUTOMATION_PROMPT.md).

**Рекомендуемый триггер:** после merge PR в `main` или 1 раз в день.

**Что должна делать automation:**

1. Проверить последний PR Cursor (или последний merged).
2. Если всё ок — создать issue **Cursor Task** с label `cursor-task`.
3. Если нужен выбор — создать issue **Decision Memo** с label `needs-ivan-decision`.
4. Если баг — issue **Cursor Task** / `cursor-fix` с описанием исправления.

**Права:** создание issues в репозитории (не merge без вас).

## 4. Cursor Cloud Agents / Automations

1. Откройте **Cursor** → **Settings** → **Integrations** → **GitHub**.
2. Подключите тот же аккаунт и выберите **tnved_starter_kit_v2**.
3. **Cloud Agents** (или Automations): создайте правило.
4. Вставьте промпт из [CURSOR_AUTOMATION_PROMPT.md](./CURSOR_AUTOMATION_PROMPT.md).
5. Триггер: новый или обновлённый issue с label `cursor-task`, без `blocked`.

**Что делает Cursor:**

- Берёт старейший открытый `cursor-task`.
- Делает ветку + PR по шаблону.
- В PR пишет полный отчёт и ссылается на issue.

## 5. Ваш цикл (Ivan)

| Шаг | Действие |
|-----|----------|
| Утро / после automation | Посмотреть новые issues: `cursor-task` или `needs-ivan-decision` |
| Decision Memo | Скопировать в Strategic ChatGPT → получить решение → комментарий в issue |
| После PR Cursor | Дождаться Codex review или запустить вручную |
| Merge | Только когда PR с `ready-for-ivan-review` или вы согласны с отчётом |

## 6. Что остаётся только вручную

- Первое подключение GitHub к Codex и Cursor (один раз).
- Включение Automations в UI продуктов (если нет API).
- **Merge** в `main` — только вы.
- Утверждение стратегических решений из Decision Memo.
- Создание labels в GitHub по [GITHUB_LABELS.md](./GITHUB_LABELS.md) (5 минут, один раз).

## 7. Проверка, что всё работает

1. Создайте тестовый issue **Cursor Task** (шаблон в GitHub → New issue → Cursor Task).
2. Запустите Cursor Automation или попросите Cursor в чате выполнить issue.
3. Убедитесь, что открылся PR с заполненным template.
4. Попросите Codex сделать review по чеклисту.

Поддержка: [WORKFLOW.md](./WORKFLOW.md), [README.md](./README.md).
