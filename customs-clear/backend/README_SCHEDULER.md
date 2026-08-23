# Автоматические обновления нормативных источников

Основной production-контур запускается вместе с FastAPI через
`app.services.scheduler` при `REGULATORY_SYNC_SCHEDULER_ENABLED=true`:

| Задача | Когда (по `REGULATORY_SYNC_TZ`) | Источники |
|---|---|---|
| `regulatory_sources_daily` | ежедневно 03:00 | ЦБ, СГР, нотификации ФСБ, РЭС/ВЧУ, OFAC, санкции ЕС |
| `regulatory_sources_weekly` | воскресенье 04:00 | ФСА, ТРОИС, справочники/маски документов ФТС |

Все адаптеры выполняются последовательно под process-lock, поэтому два worker-а
не пишут снимок одновременно. Проверить полное покрытие реестра без мутации:

```bash
python scripts/run_regulatory_source_updates.py --plan --strict
python scripts/run_regulatory_source_updates.py --cadence all --check-only --strict
```

Ручной guarded-запуск безопасных structured-sync:

```bash
python scripts/run_regulatory_source_updates.py --cadence daily --apply-safe --strict
```

Нормативные PDF, перечни Решения №30, №299, ветеринарные/фитосанитарные акты,
ПП №2425 и экспортный контроль не превращаются в правила автоматически.
Ежедневный GitHub workflow сохраняет ETag/SHA-256, обнаруживает изменение и
создаёт/обновляет review issue. Коммерческие зеркала по умолчанию отключены.

## Legacy-планировщик `scripts/auto_updater.py`

Планировщик держит в памяти только расписание; каждый краулер запускается **отдельным процессом** Python (см. `scripts/auto_updater.py`). Логи: `logs/updater.log` (ротация ~10 МБ × 5 файлов).

Перед запуском:

1. Каталог работы — **`customs-clear/backend`** (как у остальных скриптов).
2. В окружении должны быть доступны переменные из `.env` (БД, `GEMINI_API_KEY` для `sync_law_full.py` и т.д.). Планировщик копирует `os.environ` в дочерние процессы и выставляет `PYTHONPATH` на корень backend.
3. Часовой пояс расписания по умолчанию: **`Europe/Moscow`**. Иначе: `export TZ=UTC` (или нужная зона) перед стартом.

## Быстрая проверка одной задачи

```bash
cd customs-clear/backend
set -a && [ -f .env ] && source .env && set +a
python3 scripts/auto_updater.py --run-once rates
python3 scripts/auto_updater.py --run-once ifcg-one --ifcg-chapter 64
```

## Запуск планировщика в фоне

### Вариант A: `nohup`

```bash
cd customs-clear/backend
set -a && [ -f .env ] && source .env && set +a
nohup python3 scripts/auto_updater.py >> logs/updater.nohup.out 2>&1 &
echo $! > logs/updater.pid
```

Остановка: `kill $(cat logs/updater.pid)`.

### Вариант B: `tmux`

```bash
tmux new -s tnved-updater
cd customs-clear/backend
set -a && [ -f .env ] && source .env && set +a
python3 scripts/auto_updater.py
# Ctrl+B, D — отсоединиться; tmux attach -t tnved-updater — вернуться
```

### Вариант C: `pm2` (нужен Node.js)

```bash
cd customs-clear/backend
pm2 start /usr/bin/python3 --name tnved-updater --interpreter none \
  --cwd "$(pwd)" -- scripts/auto_updater.py
pm2 save
```

Переменные: `pm2 start ... --update-env` или ecosystem-файл с `env` / `env_file`.

### Вариант D: macOS `launchd`

Создайте `~/Library/LaunchAgents/com.example.tnved-updater.plist` (замените пути и пользователя):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.tnved-updater</string>
  <key>WorkingDirectory</key><string>/ABS/PATH/customs-clear/backend</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>scripts/auto_updater.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/ABS/PATH/customs-clear/backend/logs/launchd-updater.out</string>
  <key>StandardErrorPath</key><string>/ABS/PATH/customs-clear/backend/logs/launchd-updater.err</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>/ABS/PATH/customs-clear/backend</string>
    <key>GEMINI_API_KEY</key><string>YOUR_KEY</string>
  </dict>
</dict>
</plist>
```

Загрузка: `launchctl load ~/Library/LaunchAgents/com.example.tnved-updater.plist`  
Выгрузка: `launchctl unload ...`

Секреты лучше не вписывать в plist: используйте `EnvironmentVariables` с путём к файлу только если `launchd` у вас это поддерживает, либо обёртку-shell, которая делает `source .env` и вызывает `python3`.

## Legacy-расписание `auto_updater.py`

| Задача | Когда | Скрипт |
|--------|--------|--------|
| Законы TKS | каждый день 02:00 | `sync_law_full.py` |
| Нетарифка | воскресенье 03:00 | `sync_tks_nontariff.py --all-chapters --workers 4` |
| Примеры IFCG | 1-го числа 04:00 | `sync_ifcg_examples.py` по главам 01–97 |
| Курсы ЦБ | каждый день 09:00 | `update_rates.py` |

Ежемесячный прогон IFCG может занять много часов; при необходимости сузьте список глав в `auto_updater.py` (`IFCG_MONTHLY_CHAPTERS`).
