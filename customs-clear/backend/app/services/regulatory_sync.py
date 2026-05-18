"""
Синхронизация ставок ТН ВЭД из публичного Excel tws.by в таблицу hs_rates.

Используется скриптом scripts/sync_tws_data.py и может быть вызвана из планировщика.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd
from loguru import logger

TWS_DOWNLOAD_PAGE = "https://www.tws.by/tws/tnved/download"
TWS_EXCEL_FALLBACK_URL = "https://www.tws.by/tws/tnved/download/excel"
SOURCE_LABEL = "tws.by"

# Если в выгрузке tws.by нет колонки НДС — в hs_rates подставляем эту ставку (проектный дефолт).
DEFAULT_VAT_IMPORT_RATE: int = 22

# Локальное сохранение скачанного файла (относительно корня backend).
_DEFAULT_TMP_DIR = Path(__file__).resolve().parents[2] / "data" / "tmp"


def resolve_tws_excel_url(*, timeout: float = 45.0) -> str:
    """
    Ищет на странице загрузки прямую ссылку на Excel; при неудаче — известный URL /download/excel.
    """
    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise RuntimeError("Нужны пакеты httpx и beautifulsoup4") from e

    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        r = c.get(TWS_DOWNLOAD_PAGE)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            low = href.lower()
            if "excel" in low or low.endswith(".xlsx") or low.endswith(".xls"):
                return urljoin(TWS_DOWNLOAD_PAGE, href)
    return TWS_EXCEL_FALLBACK_URL


def download_tws_tariff_excel(
    *,
    url: str | None = None,
    dest_dir: Path | None = None,
    timeout: float = 120.0,
) -> tuple[Path, bytes]:
    """
    Скачивает Excel с tws.by в data/tmp/ (имя с датой UTC).
    Возвращает (путь_к_файлу, сырые_байты).
    """
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("Нужен пакет httpx") from e

    final_url = url or resolve_tws_excel_url(timeout=min(timeout, 60.0))
    out_dir = dest_dir or _DEFAULT_TMP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"tws_tnved_tariff_{stamp}.xlsx"

    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        r = c.get(final_url)
        r.raise_for_status()
        data = r.content
    if len(data) < 2000 or (data[:2] != b"PK" and not data.lstrip().startswith(b"<?xml")):
        logger.warning("tws: ответ не похож на xlsx (размер {}), URL={}", len(data), final_url)
    path.write_bytes(data)
    return path, data


def _norm_col(s: Any) -> str:
    t = str(s).strip().lower().replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t)
    return t


def _is_junk_code_header(nk: str) -> bool:
    """Заголовки первой вкладки-инструкции и прочий мусор — не колонка кода ТН ВЭД."""
    if "вкладк" in nk or "список кодов" in nk:
        return True
    if nk.startswith("unnamed") and "http" in nk:
        return True
    return False


def sniff_tws_columns(df: pd.DataFrame) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Определяет колонки: код ТН ВЭД, ставка ввозной пошлины (текст), НДС.
    """
    cols = list(df.columns)
    norm_map = {_norm_col(c): str(c) for c in cols}

    code_col: str | None = None
    duty_col: str | None = None
    vat_col: str | None = None
    excise_col: str | None = None

    # «код» без контекста ТН ВЭД даёт ложные срабатывания (напр. «Список кодов на второй вкладке»).
    code_hints = (
        "код тн вэд",
        "код тнвэд",
        "тн вэд",
        "тнвэд",
        "код тнвэд еаэс",
        "hs",
    )
    duty_hints = (
        "ставка таможенной пошлины",
        "таможенн",
        "пошлин",
        "тариф",
        "ставка ввоз",
        "импортн",
        "customs duty",
        "duty",
    )
    vat_hints = ("ндс", "vat", "налог на добавленную")
    excise_hints = ("акциз", "excise")

    for nk, orig in norm_map.items():
        if _is_junk_code_header(nk):
            continue
        if code_col is None and any(h in nk for h in code_hints) and "ндс" not in nk:
            code_col = orig
        if duty_col is None and any(h in nk for h in duty_hints):
            duty_col = orig
        if vat_col is None and any(h in nk for h in vat_hints):
            vat_col = orig
        if excise_col is None and any(h in nk for h in excise_hints):
            excise_col = orig

    # «Код» только вместе с ТН/ВЭД/HS в названии
    if code_col is None:
        for nk, orig in norm_map.items():
            if _is_junk_code_header(nk) or "ндс" in nk:
                continue
            if "код" in nk and ("тн" in nk or "вэд" in nk or "hs" in nk):
                code_col = orig
                break

    # Фолбэк: первая колонка с похожими на код значениями
    if code_col is None and cols:
        for c in cols:
            nk = _norm_col(c)
            if _is_junk_code_header(nk):
                continue
            sample = df[c].dropna().astype(str).head(20)
            if sample.map(lambda x: len(re.sub(r"\D", "", x)) >= 8).any():
                code_col = str(c)
                break

    if duty_col is None and len(cols) >= 2 and code_col:
        idx = cols.index(code_col) if code_col in cols else -1
        for j in range(idx + 1, min(idx + 5, len(cols))):
            c = cols[j]
            if c == vat_col:
                continue
            sample = df[c].dropna().astype(str).head(10)
            if sample.map(lambda x: "%" in x or "пошлин" in x.lower() or re.search(r"\d", x)).any():
                duty_col = str(c)
                break

    return code_col, duty_col, vat_col, excise_col


def load_tws_tariff_dataframe(
    blob: bytes,
) -> tuple[pd.DataFrame, tuple[str | None, str | None, str | None, str | None], str]:
    """
    Читает книгу tws.by: первая вкладка часто служебная — перебираем листы,
    пока не найдём пару колонок код+пошлина.
    """
    bio = io.BytesIO(blob)
    xl = pd.ExcelFile(bio)
    last_sniff: tuple[str | None, str | None, str | None, str | None] = (None, None, None, None)
    last_name = xl.sheet_names[0] if xl.sheet_names else ""
    for name in xl.sheet_names:
        df = pd.read_excel(xl, sheet_name=name, dtype=str).fillna("")
        sniff = sniff_tws_columns(df)
        last_sniff = sniff
        last_name = name
        if sniff[0] and sniff[1]:
            logger.info("tws: данные на листе {!r}, колонки: {}", name, sniff)
            return df, sniff, name
    return (
        pd.read_excel(io.BytesIO(blob), sheet_name=0, dtype=str).fillna(""),
        last_sniff,
        last_name,
    )


def parse_vat_cell(raw: Any, *, default: float | None = None) -> float:
    if default is None:
        default = DEFAULT_VAT_IMPORT_RATE
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return float(default)
    s = str(raw).strip().replace(",", ".")
    s = re.sub(r"\s+", "", s)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?", s)
    if m:
        return float(m.group(1))
    m2 = re.search(r"(\d+(?:\.\d+)?)", s)
    if m2:
        v = float(m2.group(1))
        if 0 <= v <= 30:
            return v
    return float(default)


def parse_excise_cell(raw: Any) -> tuple[str, float, str]:
    """
    Возвращает (excise_type, excise_value, excise_basis) из сырой ячейки Excel.
    Поддерживает:
    - проценты (percent);
    - фиксированные ставки (fixed), если есть валюта/единица измерения;
    - none, если данных нет.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "none", 0.0, ""
    txt = str(raw).strip()
    if not txt or txt in {"—", "-", "…"}:
        return "none", 0.0, ""
    low = txt.lower()
    if "не облага" in low or re.fullmatch(r"0+(?:[.,]0+)?%?", low):
        return "none", 0.0, txt[:4000]
    m_pct = re.search(r"(\d+(?:[.,]\d+)?)\s*%", txt)
    if m_pct:
        try:
            val = float(m_pct.group(1).replace(",", "."))
            return "percent", val, txt[:4000]
        except ValueError:
            pass
    m_num = re.search(r"(\d+(?:[.,]\d+)?)", txt)
    if m_num and any(u in low for u in ("руб", "eur", "usd", "/л", "/кг", "/шт", "за литр", "за кг", "за шт")):
        try:
            val = float(m_num.group(1).replace(",", "."))
            return "fixed", val, txt[:4000]
        except ValueError:
            pass
    return "none", 0.0, txt[:4000]


def parse_duty_text_to_hs_fields(duty_raw: Any) -> dict[str, Any]:
    """
    Преобразует текст ставки (в т.ч. «5%, но не менее 0.1 EUR/кг») в поля hs_rates.

    - duty_rate: **полная строка** формулировки (до 2048 символов), без жёсткого float.
    - vat_rule_basis: краткая выдержка из исходной строки (условия, валюта).
    - antidumping_condition: полный исходный текст при наличии «не менее»/специфики.
    """
    if duty_raw is None or (isinstance(duty_raw, float) and pd.isna(duty_raw)):
        return {"duty_rate": "0", "vat_rule_basis": "", "antidumping_condition": ""}

    text = str(duty_raw).strip()
    if not text or text in ("—", "-", "…"):
        return {"duty_rate": "0", "vat_rule_basis": "", "antidumping_condition": ""}

    low = text.lower()
    if "беспошлин" in low or "освобожден от пошлины" in low or re.match(r"^0\s*%?\s*$", low) or low == "free":
        return {"duty_rate": "0", "vat_rule_basis": text[:500], "antidumping_condition": ""}

    percents: list[float] = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", text):
        try:
            percents.append(float(m.group(1).replace(",", ".")))
        except ValueError:
            continue

    extra = ""
    if len(percents) > 1:
        extra = f" (доп. % из текста: {percents[1:]})"

    cond = ""
    basis = (text[:480] + ("…" if len(text) > 480 else "")) + extra
    if "не менее" in low or "не более" in low or re.search(r"\b(eur|usd|rub|кг|л)\b", low):
        cond = text[:4000]

    duty_stored = text[:2048] if len(text) <= 2048 else text[:2045] + "…"
    return {
        "duty_rate": duty_stored,
        "vat_rule_basis": basis[:2000],
        "antidumping_condition": cond[:4000],
    }


def dataframe_to_hs_rate_rows(
    df: pd.DataFrame,
    *,
    revision: str | None = None,
    columns: tuple[str | None, str | None, str | None, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Строки для upsert_hs_rate."""
    code_c, duty_c, vat_c, excise_c = columns if columns is not None else sniff_tws_columns(df)
    if not code_c or not duty_c:
        raise ValueError(f"Не удалось определить колонки кода/пошлины. Заголовки: {list(df.columns)}")

    rev = revision or f"{SOURCE_LABEL}:{date.today().isoformat()}"
    rows: list[dict[str, Any]] = []

    for _, r in df.iterrows():
        raw_code = r.get(code_c)
        if raw_code is None or (isinstance(raw_code, float) and pd.isna(raw_code)):
            continue
        digits = re.sub(r"\D", "", str(raw_code))
        if len(digits) < 10:
            continue
        hs_code = digits[:10]

        duty_part = parse_duty_text_to_hs_fields(r.get(duty_c))
        vat = parse_vat_cell(r.get(vat_c) if vat_c else None, default=DEFAULT_VAT_IMPORT_RATE)
        ex_type, ex_val, ex_basis = parse_excise_cell(r.get(excise_c) if excise_c else None)

        rows.append(
            {
                "hs_code": hs_code,
                "hs_prefix": hs_code[:4],
                "duty_rate": duty_part["duty_rate"],
                "vat_import_rate": vat,
                "vat_rule": "none",
                "vat_rule_basis": duty_part.get("vat_rule_basis") or "",
                "excise_type": ex_type,
                "excise_value": ex_val,
                "excise_basis": ex_basis,
                "antidumping_condition": duty_part.get("antidumping_condition") or "",
                "source_url": TWS_EXCEL_FALLBACK_URL,
                "source_revision": rev,
            }
        )
    return rows


def run_tws_tariff_sync(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    dest_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Полный цикл: скачать Excel tws.by → разобрать → upsert_hs_rate для каждой строки.

    Возвращает словарь со статистикой.
    """
    from .normative_store import append_sync_log, init_db, upsert_hs_rate

    init_db()
    path, blob = download_tws_tariff_excel(dest_dir=dest_dir)
    df, sniff, sheet_used = load_tws_tariff_dataframe(blob)
    if sniff[0] is None or sniff[1] is None:
        sheets_info: list[str] = []
        try:
            xl2 = pd.ExcelFile(io.BytesIO(blob))
            for nm in xl2.sheet_names:
                d = pd.read_excel(xl2, sheet_name=nm, dtype=str).fillna("")
                s = sniff_tws_columns(d)
                sheets_info.append(f"{nm!r}: {s} | cols={list(d.columns)[:12]}")
        except Exception as e:
            sheets_info = [f"(не удалось перечислить листы: {e})"]
        raise ValueError(
            f"Не удалось сопоставить колонки Excel tws.by (код/пошлина): {sniff}, "
            f"лист={sheet_used!r}. По листам:\n"
            + "\n".join(sheets_info)
        )
    rev = f"{SOURCE_LABEL}:{path.stem}"
    rate_rows = dataframe_to_hs_rate_rows(df, revision=rev, columns=sniff)
    if limit is not None:
        rate_rows = rate_rows[: max(0, int(limit))]

    n = 0
    err_note = ""
    if not dry_run:
        for row in rate_rows:
            try:
                upsert_hs_rate(row)
                n += 1
            except Exception as e:
                logger.warning("tws upsert skip {}: {}", row.get("hs_code"), e)
                err_note = str(e)[:200]

        try:
            append_sync_log(
                source_code="TWS_BY_TNVED",
                status="OK",
                revision=rev[:128],
                rows_affected=n,
                note=f"Файл: {path.name}, импортировано: {n}/{len(rate_rows)} {err_note}",
            )
        except Exception as e:
            logger.warning("tws append_sync_log: {}", e)
    else:
        n = len(rate_rows)

    return {
        "status": "OK" if not dry_run else "DRY_RUN",
        "downloaded_path": str(path),
        "sheet": sheet_used,
        "rows_parsed": len(rate_rows),
        "rows_upserted": n if not dry_run else 0,
        "columns": {"code": sniff[0], "duty": sniff[1], "vat": sniff[2], "excise": sniff[3]},
    }
