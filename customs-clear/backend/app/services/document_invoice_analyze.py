"""ИИ-разбор инвойса/спецификации: PDF (текст), Excel/CSV (таблица → текст), изображение (vision) → JSON."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import tempfile
import shutil
from typing import Any

from loguru import logger

from .gemini_genai_configure import configure_google_generativeai, resolved_gemini_model_name

MAX_TEXT_CHARS = 120_000
MAX_FILE_BYTES = 15 * 1024 * 1024


def _invoice_gemini_key_from_env() -> str:
    """Ключ Gemini для разбора инвойсов только из окружения сервера."""
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


PARSER_SYSTEM = (
    "Ты — таможенный парсер. Извлеки из инвойса или спецификации список товарных позиций. "
    "Для каждого товара определи:\n"
    "1. name — наименование (как в документе, кратко если длинное);\n"
    "2. suggested_hs_code — предлагаемый код ТН ВЭД ЕАЭС, ровно 10 цифр (только цифры);\n"
    "3. price — цена строки / сумма в валюте документа (число);\n"
    "4. net_weight_kg — вес нетто в килограммах, если в документе есть, иначе null;\n"
    "5. currency — трёхбуквенный код валюты строки (USD, EUR, CNY, RUB и т.д.), по умолчанию RUB если неочевидно.\n\n"
    "Верни ответ СТРОГО одним валидным JSON-объектом без пояснений и без markdown-обёртки, формата:\n"
    '{"items":[{"name":"string","suggested_hs_code":"8517130000","price":0.0,"net_weight_kg":null,"currency":"USD"}]}\n'
    "Если товаров нет, верни {\"items\":[]}."
)


def _norm_hs_10(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if not d:
        return ""
    if len(d) >= 10:
        return d[:10]
    if len(d) >= 4:
        return (d + "0" * 10)[:10]
    return ""


def _extract_pdf_text(data: bytes) -> str:
    text = ""
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                text += (page.get_text() or "") + "\n"
    except Exception as e:
        logger.warning(f"PyMuPDF extract: {e}")
    text = text.strip()
    if len(text) >= 40:
        return text[:MAX_TEXT_CHARS]
    try:
        import pdfplumber

        buf = io.BytesIO(data)
        with pdfplumber.open(buf) as pdf:
            parts: list[str] = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t)
        alt = "\n".join(parts).strip()
        if len(alt) > len(text):
            text = alt
    except Exception as e:
        logger.warning(f"pdfplumber extract: {e}")
    return text[:MAX_TEXT_CHARS]


def _compact_df(df: Any) -> Any:
    """Удалить полностью пустые строки и столбцы, NaN → пустая строка для текста."""
    import pandas as pd

    if df is None or df.empty:
        return pd.DataFrame()
    out = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if out.empty:
        return out
    out = out.fillna("")
    # столбцы, где все значения — пустые строки
    def _col_nonempty(series: Any) -> bool:
        for v in series:
            s = str(v).strip()
            if s and s.lower() not in ("nan", "none"):
                return True
        return False

    keep = [c for c in out.columns if _col_nonempty(out[c])]
    if keep:
        out = out[keep]

    def _row_nonempty(row: Any) -> bool:
        return any(str(x).strip() for x in row)

    out = out.loc[out.apply(_row_nonempty, axis=1)]
    return out


def _df_to_csv_chunk(df: Any) -> str:
    import pandas as pd

    if df is None or df.empty:
        return ""
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=";", encoding="utf-8")
    return buf.getvalue().strip()


def _extract_excel_as_text(data: bytes, ext: str) -> str:
    """Все листы .xlsx / .xls → сжатый текст (CSV по листам)."""
    import pandas as pd

    bio = io.BytesIO(data)
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    try:
        sheets = pd.read_excel(bio, sheet_name=None, engine=engine)
    except Exception as e:
        logger.warning(f"read_excel engine={engine}: {e}")
        raise

    if not isinstance(sheets, dict):
        sheets = {"": sheets}

    parts: list[str] = []
    for sheet_name, df in sheets.items():
        compact = _compact_df(df)
        chunk = _df_to_csv_chunk(compact)
        if chunk:
            label = str(sheet_name).strip() or "Sheet"
            parts.append(f"=== Лист: {label} ===\n{chunk}")
    return "\n\n".join(parts).strip()[:MAX_TEXT_CHARS]


def extract_xlsx_images_by_row(xlsx_bytes: bytes) -> tuple[dict[int, list[str]], str | None]:
    """
    Извлекает embedded images из XLSX (openpyxl) и сохраняет во временную папку.
    Возвращает:
    - map row_number(1-based) -> [absolute image paths]
    - path to tmp dir (для последующего cleanup)
    """
    row_map: dict[int, list[str]] = {}
    tmp_dir = tempfile.mkdtemp(prefix="xlsx_row_images_")
    try:
        from openpyxl import load_workbook
        from openpyxl.drawing.image import Image as OpenPyxlImage  # noqa: F401
        from PIL import Image

        wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
        for ws in wb.worksheets:
            for idx, img in enumerate(getattr(ws, "_images", []) or [], start=1):
                try:
                    anchor = getattr(img, "anchor", None)
                    excel_row = int(anchor._from.row) + 1 if anchor is not None else 1
                    raw = img._data() if callable(getattr(img, "_data", None)) else None
                    if not raw:
                        continue
                    pil = Image.open(io.BytesIO(raw))
                    if pil.mode not in ("RGB", "L"):
                        pil = pil.convert("RGB")
                    out = os.path.join(tmp_dir, f"{ws.title}_r{excel_row}_{idx}.jpg")
                    pil.save(out, format="JPEG", quality=92)
                    row_map.setdefault(excel_row, []).append(out)
                except Exception as e:
                    logger.debug("extract_xlsx_images_by_row: skip one image: {}", e)
        return row_map, tmp_dir
    except Exception as e:
        logger.warning("extract_xlsx_images_by_row failed: {}", e)
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        return {}, None


def _extract_csv_as_text(data: bytes) -> str:
    import pandas as pd

    last_err: Exception | None = None
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        for sep in (",", ";", "\t"):
            try:
                df = pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep)
                compact = _compact_df(df)
                chunk = _df_to_csv_chunk(compact)
                if chunk.strip():
                    return chunk[:MAX_TEXT_CHARS]
            except Exception as e:
                last_err = e
    try:
        df = pd.read_csv(io.BytesIO(data), encoding_errors="replace", sep=",")
        compact = _compact_df(df)
        return _df_to_csv_chunk(compact)[:MAX_TEXT_CHARS]
    except Exception as e:
        logger.warning(f"read_csv fallback: {last_err!r} / {e!r}")
        if last_err:
            raise last_err
        raise


def _parse_llm_json(raw: str) -> dict[str, Any]:
    t = (raw or "").strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return json.loads(t)


def _normalize_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()[:512]
        hs = _norm_hs_10(str(it.get("suggested_hs_code") or ""))
        try:
            price = float(it.get("price"))
        except (TypeError, ValueError):
            price = 0.0
        nw = it.get("net_weight_kg")
        net_weight: float | None
        if nw is None or nw == "":
            net_weight = None
        else:
            try:
                net_weight = float(nw)
            except (TypeError, ValueError):
                net_weight = None
        cur = str(it.get("currency") or "RUB").upper().strip()[:3] or "RUB"
        if len(hs) < 4 or not name:
            continue
        out.append(
            {
                "name": name,
                "suggested_hs_code": hs,
                "price": round(price, 2),
                "net_weight_kg": round(net_weight, 4) if net_weight is not None else None,
                "currency": cur if len(cur) == 3 else "RUB",
            }
        )
    return out


def _build_multimodal_technical_description(
    *,
    model: Any,
    text: str,
    image_path: str,
) -> str:
    """
    Короткое техническое описание товара для таможни по тексту + фото.
    """
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return ""
    try:
        if not image_path or not os.path.isfile(image_path):
            return ""
        img = Image.open(image_path)
        if getattr(img, "mode", None) and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        prompt = (
            f"Проанализируй текстовое описание товара '{text}' и приложенные изображения. "
            "Если изображение уточняет или опровергает текст, приоритезируй визуальные данные для подбора кода ТН ВЭД. "
            "Опиши товар техническим языком для таможни. "
            "Ответь одной краткой строкой без markdown."
        )
        resp = model.generate_content(
            [prompt, img],
            generation_config={"temperature": 0.1, "max_output_tokens": 512},
        )
        return str(getattr(resp, "text", "") or "").strip()[:1200]
    except Exception as e:
        logger.debug("multimodal technical description failed: {}", e)
        return ""


async def analyze_invoice_file(
    *,
    data: bytes,
    filename: str,
    content_type: str | None,
) -> dict[str, Any]:
    if len(data) > MAX_FILE_BYTES:
        return {"status": "ERROR", "error": "Файл слишком большой (максимум 15 МБ).", "items": []}

    key = _invoice_gemini_key_from_env()
    if not key:
        return {
            "status": "ERROR",
            "error_code": "llm_not_configured",
            "error": "ИИ для разбора инвойсов не настроен на сервере: задайте GEMINI_API_KEY или GOOGLE_API_KEY.",
            "items": [],
        }

    ext = (os.path.splitext(filename or "")[1] or "").lower()
    allowed = (".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".xls", ".csv")
    if ext not in allowed:
        return {
            "status": "ERROR",
            "error": f"Недопустимое расширение. Допустимы: {', '.join(allowed)}",
            "items": [],
        }

    try:
        import google.generativeai as genai
    except ModuleNotFoundError:
        return {"status": "ERROR", "error": "Модуль google.generativeai не установлен.", "items": []}

    model_name = resolved_gemini_model_name()
    configure_google_generativeai(genai, api_key=key)
    model = genai.GenerativeModel(model_name, system_instruction=PARSER_SYSTEM)

    user_parts: list[Any]
    source: str
    xlsx_images_by_row: dict[int, list[str]] = {}
    tmp_dir_to_cleanup: str | None = None

    try:
        if ext == ".pdf":
            source = "pdf_text"
            extracted = _extract_pdf_text(data)
            if not extracted.strip():
                return {
                    "status": "ERROR",
                    "error": "Не удалось извлечь текст из PDF (возможно, скан без OCR). Попробуйте изображение или Excel.",
                    "items": [],
                    "source": source,
                }
            user_parts = [
                "Ниже текст, извлечённый из PDF инвойса/спецификации. Верни только JSON по схеме из системной инструкции.\n\n"
                + extracted
            ]
        elif ext in (".xlsx", ".xls"):
            source = "excel_text"
            try:
                extracted = _extract_excel_as_text(data, ext)
                if ext == ".xlsx":
                    xlsx_images_by_row, tmp_dir_to_cleanup = extract_xlsx_images_by_row(data)
            except Exception as e:
                logger.warning(f"Excel parse: {e}")
                return {
                    "status": "ERROR",
                    "error": f"Не удалось прочитать Excel: {e}",
                    "items": [],
                    "source": source,
                }
            if not extracted.strip():
                return {
                    "status": "ERROR",
                    "error": "В Excel не найдено данных (пустые листы или неподдерживаемый формат .xls — нужен xlrd).",
                    "items": [],
                    "source": source,
                }
            user_parts = [
                "Ниже табличные данные из Excel (все листы, разделитель «;» в CSV). "
                "Верни только JSON по схеме из системной инструкции.\n\n"
                + extracted
            ]
        elif ext == ".csv":
            source = "csv_text"
            try:
                extracted = _extract_csv_as_text(data)
            except Exception as e:
                logger.warning(f"CSV parse: {e}")
                return {
                    "status": "ERROR",
                    "error": f"Не удалось прочитать CSV: {e}",
                    "items": [],
                    "source": source,
                }
            if not extracted.strip():
                return {
                    "status": "ERROR",
                    "error": "CSV не содержит данных после очистки пустых строк/колонок.",
                    "items": [],
                    "source": source,
                }
            user_parts = [
                "Ниже табличные данные из CSV (разделитель «;» при выводе). "
                "Верни только JSON по схеме из системной инструкции.\n\n"
                + extracted
            ]
        else:
            source = "image_vision"
            try:
                from PIL import Image
            except ModuleNotFoundError:
                return {"status": "ERROR", "error": "Pillow не установлен.", "items": []}
            img = Image.open(io.BytesIO(data))
            if getattr(img, "mode", None) and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            user_parts = [
                "Проанализируй изображение инвойса или спецификации. Верни только JSON по схеме из системной инструкции.",
                img,
            ]

        def _call() -> str:
            resp = model.generate_content(
                user_parts,
                generation_config={"temperature": 0.1, "max_output_tokens": 8192},
            )
            return (getattr(resp, "text", "") or "").strip()

        try:
            raw = await asyncio.to_thread(_call)
        except Exception as e:
            logger.exception(f"Gemini invoice parse: {e}")
            msg = str(e).lower()
            if "429" in msg or "quota" in msg or "resource exhausted" in msg:
                return {"status": "ERROR", "error": "Превышена квота запросов к Gemini.", "items": [], "source": source}
            return {
                "status": "ERROR",
                "error": "Ошибка вызова модели ИИ.",
                "items": [],
                "source": source,
            }

        if not raw:
            return {"status": "ERROR", "error": "Пустой ответ модели.", "items": [], "source": source}

        try:
            parsed = _parse_llm_json(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"invoice JSON parse: {e}; snippet={raw[:400]!r}")
            return {
                "status": "ERROR",
                "error": "Модель вернула невалидный JSON. Попробуйте другой файл или повторите запрос.",
                "items": [],
                "source": source,
                "raw_preview": raw[:800],
            }

        items = _normalize_items(parsed)
        if source == "excel_text":
            # Для XLSX всегда отдаем поля vision, даже если картинок нет.
            for it in items:
                it.setdefault("image_paths", [])
                it.setdefault("technical_description", "")
                it.setdefault("ai_visual_description", "")
            if xlsx_images_by_row:
                # Привязка картинок к item_data: по порядку строк с изображениями.
                ordered_rows = sorted(xlsx_images_by_row.keys())
                for idx, it in enumerate(items):
                    row = ordered_rows[idx] if idx < len(ordered_rows) else None
                    paths = list(xlsx_images_by_row.get(row, [])) if row is not None else []
                    it["image_paths"] = paths
                    if paths:
                        tech = await asyncio.to_thread(
                            _build_multimodal_technical_description,
                            model=model,
                            text=str(it.get("name") or ""),
                            image_path=paths[0],
                        )
                        if tech:
                            it["technical_description"] = tech
                            it["ai_visual_description"] = tech

        return {
            "status": "OK",
            "items": items,
            "source": source,
            "model": model_name,
            "items_count": len(items),
        }
    finally:
        if tmp_dir_to_cleanup and os.path.isdir(tmp_dir_to_cleanup):
            try:
                shutil.rmtree(tmp_dir_to_cleanup, ignore_errors=True)
            except Exception as e:
                logger.debug("tmp cleanup failed: {}", e)
