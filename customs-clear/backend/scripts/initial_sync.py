#!/usr/bin/env python3
"""
Первичное последовательное наполнение БД:
нетарифка → ПКР/предварительные решения → ФСБ/РЭС → СГР → Law.TKS →
ТРОИС/IP → geo/спецпошлины → санкционные списки → IFCG по главам → экосбор.

Запуск только из ``customs-clear/backend``. Краулеры идут **строго по очереди** (один ``subprocess.run``
за раз), чтобы не перегружать SQLite параллельными писателями.

Лог: ``logs/initial_sync.log`` (перезаписывается при каждом запуске) + дублирование маркеров в stdout.

  PYTHONPATH=. python3 scripts/initial_sync.py
  PYTHONPATH=. python3 scripts/initial_sync.py --proxy "http://user:pass@host:port"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = BACKEND_ROOT / "logs"
LOG_FILE = LOG_DIR / "initial_sync.log"

# Глава 77 в ТН ВЭД зарезервирована и штатно пуста — исключаем из IFCG прогона.
IFCG_CHAPTERS = [f"{i:02d}" for i in range(1, 98) if i != 77]


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    return env


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(log_fp, msg: str, *, console: bool = True) -> None:
    line = f"{_ts()} | {msg}"
    log_fp.write(line + "\n")
    log_fp.flush()
    if console:
        print(line, flush=True)


def _mask_proxy(proxy: str) -> str:
    """Скрывает логин/пароль в URL прокси для безопасного логирования."""
    p = (proxy or "").strip()
    if "@" not in p:
        return p
    scheme_sep = p.find("://")
    creds_start = scheme_sep + 3 if scheme_sep != -1 else 0
    at = p.find("@", creds_start)
    if at == -1:
        return p
    return p[:creds_start] + "***:***" + p[at:]


def run_one(
    log_fp,
    label: str,
    argv: list[str],
    *,
    console: bool = True,
) -> int:
    """
    Один ``subprocess.run`` относительно ``BACKEND_ROOT``; вывод дочернего процесса пишется в лог и
    (опционально) в консоль после завершения шага.

    ``label`` — короткое имя шага для маркеров СТАРТ/УСПЕХ/ОШИБКА.
    """
    cmd = [sys.executable, *argv]
    _emit(log_fp, f"СТАРТ: {label}...", console=console)
    t0 = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(BACKEND_ROOT),
            env=_child_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=None,
        )
    except Exception as e:
        _emit(log_fp, f"ОШИБКА: {label} — исключение subprocess: {e}", console=True)
        return 1

    out = proc.stdout or ""
    if out:
        log_fp.write(out)
        if not out.endswith("\n"):
            log_fp.write("\n")
        log_fp.flush()
        if console:
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    if proc.returncode == 0:
        _emit(log_fp, f"УСПЕХ: {label} (≈{elapsed:.0f} с)", console=console)
    else:
        _emit(log_fp, f"ОШИБКА: {label} — код выхода {proc.returncode} (≈{elapsed:.0f} с)", console=True)
    return int(proc.returncode or 0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Первичный последовательный прогон краулеров")
    ap.add_argument(
        "--ifcg-max-codes",
        type=int,
        default=0,
        metavar="N",
        help="Лимит кодов на главу для sync_ifcg_examples.py (0 = все коды главы)",
    )
    ap.add_argument(
        "--skip-ifcg",
        action="store_true",
        help="Пропустить блок IFCG (долгий прогон)",
    )
    ap.add_argument(
        "--skip-eco",
        action="store_true",
        help="Пропустить sync_eco_fees.py",
    )
    ap.add_argument(
        "--skip-state-registries",
        action="store_true",
        help="Пропустить sync_state_registries.py (ФСБ + РЭС)",
    )
    ap.add_argument(
        "--skip-sgr",
        action="store_true",
        help="Пропустить sync_sgr_registry.py",
    )
    ap.add_argument(
        "--sgr-nsi-limit",
        type=int,
        default=20000,
        help="Лимит строк NSI для sync_sgr_registry.py (0 = все; по умолчанию 20000 для практичного прогона)",
    )
    ap.add_argument(
        "--skip-predecisions",
        action="store_true",
        help="Пропустить sync_tks_predecisions.py",
    )
    ap.add_argument(
        "--skip-nontariff",
        action="store_true",
        help="Пропустить sync_tks_nontariff.py",
    )
    ap.add_argument(
        "--skip-law",
        action="store_true",
        help="Пропустить sync_law_full.py",
    )
    ap.add_argument(
        "--skip-trois",
        action="store_true",
        help="Пропустить sync_trois.py и sync_trois_alta.py",
    )
    ap.add_argument(
        "--proxy",
        type=str,
        default="",
        help="Опциональный глобальный прокси для дочерних sync-скриптов (например, http://user:pass@host:port)",
    )
    ap.add_argument(
        "--skip-geo",
        action="store_true",
        help="Пропустить sync_geo_regulations.py",
    )
    ap.add_argument(
        "--skip-tamdoc",
        action="store_true",
        help="Пропустить sync_tamdoc.py --targeted --approve-pending",
    )
    ap.add_argument(
        "--skip-tws",
        action="store_true",
        help="Пропустить sync_tws_data.py (ставки/акцизы)",
    )
    ap.add_argument(
        "--skip-sanctions",
        action="store_true",
        help="Пропустить блок санкционных синков (OFAC/EU/country_rules/sanction_import_risks)",
    )
    ap.add_argument(
        "--ofac-url",
        type=str,
        default="",
        help="Опциональный URL для sync_ofac_sanctions.py",
    )
    ap.add_argument(
        "--eu-url",
        type=str,
        default="",
        help="Опциональный URL для sync_eu_sanctions.py",
    )
    ap.add_argument(
        "--country-rules-input",
        type=str,
        default="",
        help="Локальный CSV/JSON для sync_country_rules.py",
    )
    ap.add_argument(
        "--country-rules-url",
        type=str,
        default="",
        help="URL CSV/JSON для sync_country_rules.py",
    )
    ap.add_argument(
        "--sanction-risks-input",
        type=str,
        default="",
        help="Локальный CSV/JSON для sync_sanction_risks.py",
    )
    ap.add_argument(
        "--sanction-risks-url",
        type=str,
        default="",
        help="URL CSV/JSON для sync_sanction_risks.py",
    )
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    exit_codes: list[tuple[str, int]] = []

    with LOG_FILE.open("w", encoding="utf-8") as log_fp:
        _emit(log_fp, "========== initial_sync: начало полного прогона ==========")

        # 1. Нетарифка TKS
        proxy = (args.proxy or "").strip()
        if proxy:
            os.environ["HTTP_PROXY"] = proxy
            os.environ["HTTPS_PROXY"] = proxy
            os.environ["ALL_PROXY"] = proxy
            _emit(log_fp, f"Глобальный прокси для дочерних скриптов включен ({_mask_proxy(proxy)})")
        if not args.skip_nontariff:
            tks_argv = ["scripts/sync_tks_nontariff.py", "--all-chapters", "--workers", "4"]
            if proxy:
                tks_argv.extend(["--proxy", proxy])
                _emit(log_fp, f"TKS: прокси включен ({_mask_proxy(proxy)})")
            rc = run_one(
                log_fp,
                "сбор нетарифки (TKS, все главы)",
                tks_argv,
            )
            exit_codes.append(("nontariff", rc))
        else:
            _emit(log_fp, "ПРОПУСК: нетарифка TKS (--skip-nontariff)")

        # 2. ПКР / предварительные решения ФТС (Alta)
        if not args.skip_predecisions:
            predecisions_argv = ["scripts/sync_tks_predecisions.py", "--max-pages", "0", "--skip-entity-ai"]
            if proxy:
                predecisions_argv.extend(["--proxy", proxy])
            rc = run_one(
                log_fp,
                "сбор ПКР/предварительных решений (Alta, все главы)",
                predecisions_argv,
            )
            exit_codes.append(("predecisions_alta", rc))
        else:
            _emit(log_fp, "ПРОПУСК: предварительные решения (--skip-predecisions)")

        # 3. Реестры ФСБ/РЭС
        if not args.skip_state_registries:
            state_argv = ["scripts/sync_state_registries.py"]
            if proxy:
                state_argv.extend(["--proxy", proxy])
            rc = run_one(
                log_fp,
                "сбор реестров ФСБ/РЭС (state registries)",
                state_argv,
            )
            exit_codes.append(("state_registries", rc))
        else:
            _emit(log_fp, "ПРОПУСК: state registries (--skip-state-registries)")

        # 4. СГР (полная загрузка)
        if not args.skip_sgr:
            sgr_argv = ["scripts/sync_sgr_registry.py", "--full-load", "--nsi-limit", str(max(0, int(args.sgr_nsi_limit)))]
            if proxy:
                sgr_argv.extend(["--proxy", proxy])
            rc = run_one(
                log_fp,
                "сбор реестра СГР (полная загрузка)",
                sgr_argv,
            )
            if rc == 2:
                _emit(log_fp, "СГР: источник не настроен, шаг пропущен без фатальной ошибки")
                exit_codes.append(("sgr_registry", 0))
            else:
                exit_codes.append(("sgr_registry", rc))
        else:
            _emit(log_fp, "ПРОПУСК: СГР (--skip-sgr)")

        # 5. Law.TKS — топики 1–20, ИИ по умолчанию включён
        if not args.skip_law:
            rc = run_one(
                log_fp,
                "сбор нормативки Law.TKS (топики + ИИ)",
                ["scripts/sync_law_full.py", "--portal-topics"],
            )
            exit_codes.append(("law_full", rc))
        else:
            _emit(log_fp, "ПРОПУСК: нормативка Law.TKS (--skip-law)")

        # 6. ТРОИС/IP registry (alta + customs + плоский реестр alta)
        if not args.skip_trois:
            trois_argv = ["scripts/sync_trois.py"]
            trois_alta_argv = ["scripts/sync_trois_alta.py"]
            if proxy:
                trois_argv.extend(["--proxy", proxy])
                trois_alta_argv.extend(["--proxy", proxy])
                _emit(log_fp, f"TROIS: прокси включен ({_mask_proxy(proxy)})")
            rc = run_one(
                log_fp,
                "сбор ТРОИС/IP (intellectual_properties)",
                trois_argv,
            )
            exit_codes.append(("trois_sync", rc))
            rc = run_one(
                log_fp,
                "сбор ТРОИС/IP (trois_registry, alta)",
                trois_alta_argv,
            )
            exit_codes.append(("trois_alta", rc))
        else:
            _emit(log_fp, "ПРОПУСК: ТРОИС/IP (--skip-trois)")

        # 7. Geopolitical duties (anti-dumping / embargo / increased_duty)
        if not args.skip_geo:
            rc = run_one(
                log_fp,
                "сбор geo_special_duties (полный обход глав)",
                ["scripts/sync_geo_regulations.py"],
            )
            exit_codes.append(("geo_regulations", rc))
        else:
            _emit(log_fp, "ПРОПУСК: geo_special_duties (--skip-geo)")

        # 8. Tamdoc targeted (спецпошлины/льготы/нормативка)
        if not args.skip_tamdoc:
            rc = run_one(
                log_fp,
                "сбор tamdoc targeted + auto-approve pending",
                [
                    "scripts/sync_tamdoc.py",
                    "--targeted",
                    "--approve-pending",
                    "--approve-limit",
                    "0",
                ],
            )
            exit_codes.append(("tamdoc", rc))
        else:
            _emit(log_fp, "ПРОПУСК: tamdoc (--skip-tamdoc)")

        # 9. Ставки + акцизы (TWS)
        if not args.skip_tws:
            rc = run_one(
                log_fp,
                "сбор ставок/акцизов (TWS)",
                ["scripts/sync_tws_data.py"],
            )
            exit_codes.append(("tws_rates", rc))
        else:
            _emit(log_fp, "ПРОПУСК: tws rates (--skip-tws)")

        # 10. Санкционный комплаенс (OFAC / EU / country rules / sanction risks)
        if not args.skip_sanctions:
            ofac_argv = ["scripts/sync_ofac_sanctions.py"]
            eu_argv = ["scripts/sync_eu_sanctions.py"]
            country_rules_argv = ["scripts/sync_country_rules.py"]
            sanction_risks_argv = ["scripts/sync_sanction_risks.py", "--from-geo"]

            ofac_url = (args.ofac_url or "").strip()
            eu_url = (args.eu_url or "").strip()
            country_rules_input = (args.country_rules_input or "").strip()
            country_rules_url = (args.country_rules_url or "").strip()
            sanction_risks_input = (args.sanction_risks_input or "").strip()
            sanction_risks_url = (args.sanction_risks_url or "").strip()

            if ofac_url:
                ofac_argv.extend(["--url", ofac_url])
            if eu_url:
                eu_argv.extend(["--url", eu_url])

            if country_rules_input:
                country_rules_argv.extend(["--input", country_rules_input])
            elif country_rules_url:
                country_rules_argv.extend(["--url", country_rules_url])
            else:
                country_rules_argv.append("--seed-default")

            if sanction_risks_input:
                sanction_risks_argv.extend(["--input", sanction_risks_input])
            elif sanction_risks_url:
                sanction_risks_argv.extend(["--url", sanction_risks_url])

            rc = run_one(log_fp, "сбор санкций OFAC (ofac_sdn_list)", ofac_argv)
            exit_codes.append(("ofac_sdn_list", rc))
            rc = run_one(log_fp, "сбор санкций ЕС (eu_sanctions_list)", eu_argv)
            exit_codes.append(("eu_sanctions_list", rc))
            rc = run_one(log_fp, "сбор страновых правил (country_specific_rules)", country_rules_argv)
            exit_codes.append(("country_specific_rules", rc))
            rc = run_one(log_fp, "сбор санкционных рисков (sanction_import_risks)", sanction_risks_argv)
            exit_codes.append(("sanction_import_risks", rc))
        else:
            _emit(log_fp, "ПРОПУСК: санкционные синки (--skip-sanctions)")

        # 11. IFCG — по главам 01–97, кроме резервной 77
        if not args.skip_ifcg:
            _emit(
                log_fp,
                f"СТАРТ: сбор примеров и ПКР (IFCG) по главам 01–97 (без 77), до {args.ifcg_max_codes} кодов на главу...",
            )
            ifcg_fail = 0
            for ch in IFCG_CHAPTERS:
                rc = run_one(
                    log_fp,
                    f"IFCG глава {ch}",
                    ["scripts/sync_ifcg_examples.py", "--chapter", ch, "--max-codes", str(args.ifcg_max_codes)],
                    console=False,
                )
                if rc != 0:
                    ifcg_fail += 1
            if ifcg_fail == 0:
                _emit(log_fp, "УСПЕХ: примеры и ПКР (IFCG) по всем главам")
            else:
                _emit(log_fp, f"ОШИБКА: IFCG — ошибок в {ifcg_fail} из {len(IFCG_CHAPTERS)} глав (см. маркеры по главам выше)")
            exit_codes.append(("ifcg", 0 if ifcg_fail == 0 else 1))
        else:
            _emit(log_fp, "ПРОПУСК: IFCG (--skip-ifcg)")

        # 12. Экосбор РОП
        eco_script = BACKEND_ROOT / "scripts" / "sync_eco_fees.py"
        if not args.skip_eco and eco_script.is_file():
            rc = run_one(log_fp, "сбор тарифов экосбора (sync_eco_fees)", ["scripts/sync_eco_fees.py"])
            exit_codes.append(("eco_fees", rc))
        elif args.skip_eco:
            _emit(log_fp, "ПРОПУСК: экосбор (--skip-eco)")
        else:
            _emit(log_fp, "ПРОПУСК: sync_eco_fees.py не найден")

        _emit(log_fp, "========== initial_sync: конец прогона ==========")
        summary = ", ".join(f"{n}={c}" for n, c in exit_codes)
        _emit(log_fp, f"Сводка кодов выхода: {summary or '(нет шагов)'}")

    print(f"\nЛог записан: {LOG_FILE}", flush=True)
    return 0 if all(c == 0 for _, c in exit_codes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
