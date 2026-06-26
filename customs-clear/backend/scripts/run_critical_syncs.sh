#!/usr/bin/env bash
# =============================================================================
# run_critical_syncs.sh
# -----------------------------------------------------------------------------
# Последовательная массовая загрузка критичных данных в customs.db:
#   - ТРОИС (trois_registry, intellectual_properties)
#   - Санкции (OFAC, EU)
#   - Страновые правила (country_specific_rules)
#   - Геополитика / спецпошлины (geo_special_duties)
#   - Санкционные риски по ТН ВЭД (sanction_import_risks)
#
# Безопасность от IP-бана:
#   - порядок: сначала лёгкие XML-скачивания, потом тяжёлые скрейперы Alta.ru;
#   - паузы sleep между сетевыми этапами;
#   - для Alta.ru используется --playwright (обход антибота);
#   - логируется прогресс + код возврата каждого шага.
#
# Запуск:
#   cd customs-clear/backend
#   chmod +x scripts/run_critical_syncs.sh
#   ./scripts/run_critical_syncs.sh              # обычный прогон
#   ./scripts/run_critical_syncs.sh --proxy http://user:pass@host:port
#
# Опционально можно пропустить отдельные блоки через ENV:
#   SKIP_OFAC=1 SKIP_EU=1 ./scripts/run_critical_syncs.sh
#   SKIP_TROIS_ALTA=1 ./scripts/run_critical_syncs.sh
#
# Лог пишется в logs/critical_syncs.log (дозапись) + дублируется в stdout.
# =============================================================================

set -u
set -o pipefail

# ---------------------------------------------------------------------------
# Обязательно запускаем из каталога customs-clear/backend.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_ROOT}"

# ---------------------------------------------------------------------------
# Автоопределение интерпретатора: предпочитаем python3 (на macOS по умолчанию),
# fallback на python.
# ---------------------------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "[FATAL] Не найден ни python3, ни python в PATH." >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Опциональный глобальный прокси (пробрасываем дочерним процессам).
# ---------------------------------------------------------------------------
PROXY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --proxy)
      PROXY="${2:-}"
      shift 2
      ;;
    --proxy=*)
      PROXY="${1#--proxy=}"
      shift
      ;;
    *)
      echo "[WARN] Неизвестный аргумент: $1 (пропускаем)"
      shift
      ;;
  esac
done

if [[ -n "${PROXY}" ]]; then
  export HTTP_PROXY="${PROXY}"
  export HTTPS_PROXY="${PROXY}"
  export ALL_PROXY="${PROXY}"
fi

# ---------------------------------------------------------------------------
# Логирование.
# ---------------------------------------------------------------------------
LOG_DIR="${BACKEND_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/critical_syncs.log"

log() {
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "${ts} | $*" | tee -a "${LOG_FILE}"
}

mask_proxy() {
  local p="$1"
  if [[ "${p}" == *"@"* ]]; then
    # скрываем логин:пароль между ://  и @
    echo "${p}" | sed -E 's#(://)[^@]*@#\1***:***@#'
  else
    echo "${p}"
  fi
}

# ---------------------------------------------------------------------------
# Запуск одного шага с логами и учётом кода возврата.
# $1 — человекочитаемое имя шага
# остальные — аргументы для python (sys.executable)
# ---------------------------------------------------------------------------
run_step() {
  local label="$1"
  shift

  local start_ts end_ts elapsed rc
  start_ts="$(date +%s)"
  log "СТАРТ: ${label}"
  log "  CMD: ${PY} $*"

  set +e
  "${PY}" "$@" 2>&1 | tee -a "${LOG_FILE}"
  rc="${PIPESTATUS[0]}"
  set -e 2>/dev/null || true  # set -e не использовали; защищаемся на всякий

  end_ts="$(date +%s)"
  elapsed=$(( end_ts - start_ts ))

  if [[ "${rc}" -eq 0 ]]; then
    log "УСПЕХ: ${label} (≈${elapsed}s)"
  else
    log "ОШИБКА: ${label} — exit=${rc} (≈${elapsed}s)"
  fi
  echo "" | tee -a "${LOG_FILE}"
  return "${rc}"
}

# ---------------------------------------------------------------------------
# Заголовок прогона.
# ---------------------------------------------------------------------------
log "========== run_critical_syncs.sh: начало прогона =========="
log "BACKEND_ROOT=${BACKEND_ROOT}"
log "PY=${PY}"
if [[ -n "${PROXY}" ]]; then
  log "PROXY=$(mask_proxy "${PROXY}") (HTTP_PROXY/HTTPS_PROXY/ALL_PROXY экспортированы)"
else
  log "PROXY=OFF"
fi

# Аккумуляторы статусов.
declare -a STEP_RESULTS=()

record() {
  STEP_RESULTS+=("$1:$2")
}

# ===========================================================================
# БЛОК 1. Страновые правила (offline/seed — мгновенно, без HTTP).
# ===========================================================================
if [[ "${SKIP_COUNTRY_RULES:-0}" != "1" ]]; then
  run_step "country_rules (seed-default)" scripts/sync_country_rules.py --seed-default
  record "country_rules" "$?"
else
  log "ПРОПУСК: country_rules (SKIP_COUNTRY_RULES=1)"
fi

log "Пауза 5s перед внешними XML-источниками..."
sleep 5

# ===========================================================================
# БЛОК 2. Санкции OFAC (США): прямой XML с treasury.gov — лёгкий.
# ===========================================================================
if [[ "${SKIP_OFAC:-0}" != "1" ]]; then
  run_step "OFAC SDN" scripts/sync_ofac_sanctions.py --timeout 60 --retries 4
  record "ofac_sanctions" "$?"
else
  log "ПРОПУСК: OFAC (SKIP_OFAC=1)"
fi

log "Пауза 10s перед санкциями ЕС..."
sleep 10

# ===========================================================================
# БЛОК 3. Санкции ЕС: прямой XML/XLSX с webgate.ec.europa.eu.
# ===========================================================================
if [[ "${SKIP_EU:-0}" != "1" ]]; then
  run_step "EU sanctions" scripts/sync_eu_sanctions.py --timeout 60 --retries 4
  record "eu_sanctions" "$?"
else
  log "ПРОПУСК: EU (SKIP_EU=1)"
fi

log "Пауза 15s перед геополитическим скрейпером..."
sleep 15

# ===========================================================================
# БЛОК 4. Геополитика / спецпошлины по префиксам ТН ВЭД.
#   --all-chapters: обход по всем главам
#   --no-llm: без Gemini (быстрее, дешевле, нужны только геометаданные)
#   --sleep 0.5: троттлинг между HTTP-запросами (антибот)
# ===========================================================================
if [[ "${SKIP_GEO:-0}" != "1" ]]; then
  run_step "geo_regulations (all chapters, no LLM)" \
    scripts/sync_geo_regulations.py --all-chapters --no-llm --sleep 0.5
  record "geo_regulations" "$?"
else
  log "ПРОПУСК: geo_regulations (SKIP_GEO=1)"
fi

log "Пауза 10s перед слоем sanction_import_risks..."
sleep 10

# ===========================================================================
# БЛОК 5. sanction_import_risks: строится из geo_special_duties (без HTTP).
#   Должен идти ПОСЛЕ geo_regulations, чтобы подтянуть свежие данные.
# ===========================================================================
if [[ "${SKIP_SANCTION_RISKS:-0}" != "1" ]]; then
  run_step "sanction_import_risks (from-geo)" \
    scripts/sync_sanction_risks.py --from-geo
  record "sanction_risks" "$?"
else
  log "ПРОПУСК: sanction_import_risks (SKIP_SANCTION_RISKS=1)"
fi

log "Пауза 15s перед первым скрейпером ТРОИС (customs.gov.ru + alta.ru)..."
sleep 15

# ===========================================================================
# БЛОК 6. ТРОИС #1: sync_trois.py — пишет в intellectual_properties.
#   Источники: alta.ru/rois/all/ + customs.gov.ru/registers/...
#   Скрипт внутри уже делает retry и User-Agent rotation.
# ===========================================================================
if [[ "${SKIP_TROIS:-0}" != "1" ]]; then
  if [[ -n "${PROXY}" ]]; then
    run_step "TROIS sources (intellectual_properties)" \
      scripts/sync_trois.py --proxy "${PROXY}"
  else
    run_step "TROIS sources (intellectual_properties)" scripts/sync_trois.py
  fi
  record "trois_sources" "$?"
else
  log "ПРОПУСК: sync_trois.py (SKIP_TROIS=1)"
fi

log "Пауза 30s перед Playwright-прогоном Alta.ru (антибот cooldown)..."
sleep 30

# ===========================================================================
# БЛОК 7. ТРОИС #2: sync_trois_alta.py --playwright
#   Самый тяжёлый и чувствительный к бану источник (alta.ru/rois/all).
#   Именно поэтому он последний — даже при частичном бане предыдущие
#   разделы уже успеют записаться в БД.
#   --playwright: настоящий браузер (обход cf/antibot).
#   --max-pages 30: консервативная пагинация (по умолчанию 30).
#   --retries 4, --timeout 90: устойчивее к таймаутам.
# ===========================================================================
if [[ "${SKIP_TROIS_ALTA:-0}" != "1" ]]; then
  TROIS_ALTA_ARGS=(scripts/sync_trois_alta.py --playwright --max-pages 30 --timeout 90 --retries 4)
  if [[ -n "${PROXY}" ]]; then
    TROIS_ALTA_ARGS+=(--proxy "${PROXY}")
  fi
  run_step "TROIS alta.ru Playwright (trois_registry)" "${TROIS_ALTA_ARGS[@]}"
  record "trois_alta" "$?"
else
  log "ПРОПУСК: sync_trois_alta.py (SKIP_TROIS_ALTA=1)"
fi

# ===========================================================================
# Итоговая сводка.
# ===========================================================================
log "========== Сводка run_critical_syncs.sh =========="
OK_COUNT=0
FAIL_COUNT=0
for item in "${STEP_RESULTS[@]}"; do
  name="${item%%:*}"
  rc="${item##*:}"
  if [[ "${rc}" -eq 0 ]]; then
    log "  [OK]   ${name}"
    OK_COUNT=$(( OK_COUNT + 1 ))
  else
    log "  [FAIL] ${name} (exit=${rc})"
    FAIL_COUNT=$(( FAIL_COUNT + 1 ))
  fi
done
log "Итого: успешно=${OK_COUNT}, с ошибками=${FAIL_COUNT}"

log "Подсказка: проверь свежие цифры через ${PY} -m scripts.audit_compliance_db"
log "Лог прогона: ${LOG_FILE}"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
  exit 1
fi
exit 0
