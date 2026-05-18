from __future__ import annotations

import argparse
import logging
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure

LOGGER = logging.getLogger("parser_eaeu")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class ParsedMeasure:
    hs_code: str
    description: str
    document_required: str


class EAEUParser:
    parser_name = "base"

    def __init__(
        self,
        source: str,
        measure_type: str,
        document_required: str,
        regulatory_act: str,
        downloads_dir: Path,
    ) -> None:
        self.source = source
        self.measure_type = measure_type
        self.default_document_required = document_required
        self.regulatory_act = regulatory_act
        self.downloads_dir = downloads_dir
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        LOGGER.info("[%s] Start. source=%s", self.parser_name, self.source)
        source_path = self.resolve_source_path(self.source)
        records = list(self.parse_records(source_path))
        LOGGER.info("[%s] Parsed raw records: %s", self.parser_name, len(records))
        self.save_records(records)

    def resolve_source_path(self, source: str) -> Path:
        if source.startswith("http://") or source.startswith("https://"):
            return self.download_with_cache(source)

        local = Path(source)
        if not local.is_absolute():
            local = (ROOT / source).resolve()
        if local.exists():
            LOGGER.info("[%s] Use local source: %s", self.parser_name, local)
            return local

        fallback = (self.downloads_dir / Path(source).name).resolve()
        if fallback.exists():
            LOGGER.warning(
                "[%s] Source not found by explicit path, fallback to downloads cache: %s",
                self.parser_name,
                fallback,
            )
            return fallback
        raise FileNotFoundError(f"Source file not found: {source}")

    def download_with_cache(self, url: str) -> Path:
        parsed = urlparse(url)
        filename = Path(parsed.path).name or f"{self.parser_name}.bin"
        target = (self.downloads_dir / filename).resolve()
        if target.exists():
            LOGGER.info("[%s] Use cached download: %s", self.parser_name, target)
            return target

        headers = {"User-Agent": USER_AGENT}
        try:
            LOGGER.info("[%s] Downloading: %s", self.parser_name, url)
            with requests.get(url, headers=headers, timeout=40, stream=True) as resp:
                resp.raise_for_status()
                with target.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)
            LOGGER.info("[%s] Downloaded to: %s", self.parser_name, target)
            return target
        except Exception as exc:
            if target.exists():
                LOGGER.warning(
                    "[%s] Download failed (%s), fallback to existing cached file: %s",
                    self.parser_name,
                    exc,
                    target,
                )
                return target
            raise

    @staticmethod
    def clean_hs_code(raw: str) -> str:
        code = re.sub(r"\D", "", raw or "")
        if len(code) in (4, 6, 10):
            return code
        return ""

    @staticmethod
    def _norm_cell(cell: object) -> str:
        return re.sub(r"\s+", " ", str(cell or "")).strip()

    def read_tables(self, path: Path) -> list[list[list[str]]]:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._read_pdf_tables(path)
        if suffix in (".htm", ".html", ".xml"):
            return self._read_html_tables(path)
        if suffix == ".docx":
            return self._read_docx_as_rows(path)
        raise ValueError(f"Unsupported source format: {path.suffix}")

    def _read_pdf_tables(self, path: Path) -> list[list[list[str]]]:
        all_tables: list[list[list[str]]] = []
        with pdfplumber.open(str(path)) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                page_tables = page.extract_tables() or []
                for table in page_tables:
                    clean_table = [[self._norm_cell(c) for c in (row or [])] for row in table]
                    if clean_table:
                        all_tables.append(clean_table)
                if not page_tables:
                    txt = page.extract_text() or ""
                    rows = self._text_to_rows(txt)
                    if rows:
                        all_tables.append(rows)
                LOGGER.debug("[%s] page=%s tables=%s", self.parser_name, page_idx, len(page_tables))
        return all_tables

    def _read_html_tables(self, path: Path) -> list[list[list[str]]]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(text, "lxml")
        tables: list[list[list[str]]] = []
        for t in soup.find_all("table"):
            rows: list[list[str]] = []
            for tr in t.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                row = [self._norm_cell(c.get_text(" ", strip=True)) for c in cells]
                if row:
                    rows.append(row)
            if rows:
                tables.append(rows)
        return tables

    def _read_docx_as_rows(self, path: Path) -> list[list[list[str]]]:
        rows: list[list[str]] = []
        with zipfile.ZipFile(path) as zf:
            data = zf.read("word/document.xml")
        root = etree.fromstring(data)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        for p in root.xpath(".//w:p", namespaces=ns):
            text_parts = p.xpath(".//w:t/text()", namespaces=ns)
            line = self._norm_cell(" ".join(text_parts))
            if not line:
                continue
            # Для docx без явной таблицы: одна строка = один pseudo-row.
            rows.append([line])
        return [rows] if rows else []

    @staticmethod
    def _text_to_rows(text: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for line in text.splitlines():
            clean = re.sub(r"\s+", " ", line).strip()
            if clean:
                rows.append([clean])
        return rows

    def parse_records(self, path: Path) -> Iterable[ParsedMeasure]:
        raise NotImplementedError

    def save_records(self, records: list[ParsedMeasure]) -> None:
        created_batch: list[NonTariffMeasure] = []
        invalid_codes = 0
        expanded = 0
        duplicates = 0
        no_targets = 0

        with SessionLocal() as db:
            all_codes = {c[0] for c in db.query(Commodity.code).all()}
            leaf_codes = [c for c in all_codes if len(c) == 10]
            existing_keys = {
                (
                    m.commodity_code,
                    (m.measure_type or "").strip().lower(),
                    (m.regulatory_act or "").strip(),
                )
                for m in db.query(NonTariffMeasure).all()
            }
            staged_keys: set[tuple[str, str, str]] = set()

            for rec in records:
                code = self.clean_hs_code(rec.hs_code)
                if not code:
                    invalid_codes += 1
                    LOGGER.debug("[%s] skip invalid code: %r", self.parser_name, rec.hs_code)
                    continue

                targets = self._expand_targets(code, all_codes, leaf_codes)
                if not targets:
                    no_targets += 1
                    LOGGER.debug("[%s] no targets for code=%s", self.parser_name, code)
                    continue

                if code not in all_codes and len(code) in (4, 6):
                    expanded += 1

                for target in targets:
                    key = (
                        target,
                        self.measure_type,
                        self.regulatory_act.strip(),
                    )
                    if key in existing_keys or key in staged_keys:
                        duplicates += 1
                        continue
                    staged_keys.add(key)
                    created_batch.append(
                        NonTariffMeasure(
                            commodity_code=target,
                            measure_type=self.measure_type,
                            description=rec.description.strip(),
                            document_required=rec.document_required.strip(),
                            regulatory_act=self.regulatory_act.strip(),
                        )
                    )

            if created_batch:
                db.bulk_save_objects(created_batch)
                db.commit()

        LOGGER.info(
            "[%s] save done: inserted=%s invalid_codes=%s no_targets=%s expanded=%s duplicates=%s",
            self.parser_name,
            len(created_batch),
            invalid_codes,
            no_targets,
            expanded,
            duplicates,
        )

    @staticmethod
    def _expand_targets(code: str, all_codes: set[str], leaf_codes: list[str]) -> list[str]:
        if code in all_codes:
            return [code]
        if len(code) in (4, 6):
            return [c for c in leaf_codes if c.startswith(code)]
        return []


class VetControlParser(EAEUParser):
    parser_name = "VetControlParser_317"

    def __init__(self, source: str, downloads_dir: Path) -> None:
        super().__init__(
            source=source,
            measure_type="vet_control",
            document_required="Ветеринарный сертификат",
            regulatory_act="Решение КТС № 317",
            downloads_dir=downloads_dir,
        )

    def parse_records(self, path: Path) -> Iterable[ParsedMeasure]:
        tables = self.read_tables(path)
        parsed = 0
        for table in tables:
            code_idx, name_idx = self._detect_indices(table, ("код", "тн вэд"), ("наименование", "товар"))
            for row in table:
                if not row:
                    continue
                code_cell = row[code_idx] if code_idx < len(row) else row[0]
                hs_code = self.clean_hs_code(code_cell)
                if not hs_code:
                    continue
                description = row[name_idx] if name_idx < len(row) else ""
                parsed += 1
                yield ParsedMeasure(
                    hs_code=hs_code,
                    description=description or "Подлежит ветеринарному контролю",
                    document_required=self.default_document_required,
                )
        LOGGER.info("[%s] extracted records=%s", self.parser_name, parsed)

    @staticmethod
    def _detect_indices(table: list[list[str]], code_hints: tuple[str, ...], name_hints: tuple[str, ...]) -> tuple[int, int]:
        for row in table[:3]:
            low = [c.lower() for c in row]
            code_idx = next((i for i, c in enumerate(low) if all(h in c for h in code_hints)), 0)
            name_idx = next((i for i, c in enumerate(low) if any(h in c for h in name_hints)), min(1, len(row) - 1))
            if code_idx is not None:
                return code_idx, name_idx
        return 0, 1


class PhytoControlParser(EAEUParser):
    parser_name = "PhytoControlParser_318"

    def __init__(self, source: str, downloads_dir: Path) -> None:
        super().__init__(
            source=source,
            measure_type="phyto_control",
            document_required="Фитосанитарный сертификат",
            regulatory_act="Решение КТС № 318",
            downloads_dir=downloads_dir,
        )

    def parse_records(self, path: Path) -> Iterable[ParsedMeasure]:
        tables = self.read_tables(path)
        parsed = 0
        for table in tables:
            for row in table:
                if not row:
                    continue
                # Для 318 часто код может быть не в первой колонке.
                joined = " | ".join(row)
                code_match = re.search(r"(\d[\d\.\s]{3,16}\d)", joined)
                if not code_match:
                    continue
                hs_code = self.clean_hs_code(code_match.group(1))
                if not hs_code:
                    continue
                description = row[1] if len(row) > 1 else "Подкарантинная продукция"
                parsed += 1
                yield ParsedMeasure(
                    hs_code=hs_code,
                    description=description,
                    document_required=self.default_document_required,
                )
        LOGGER.info("[%s] extracted records=%s", self.parser_name, parsed)


class CertificateParser(EAEUParser):
    parser_name = "CertificateParser_30"

    def __init__(self, source: str, downloads_dir: Path) -> None:
        super().__init__(
            source=source,
            measure_type="certificate",
            document_required="Документ о подтверждении соответствия",
            regulatory_act="Решение Коллегии ЕЭК № 30",
            downloads_dir=downloads_dir,
        )

    def parse_records(self, path: Path) -> Iterable[ParsedMeasure]:
        tables = self.read_tables(path)
        parsed = 0
        for table in tables:
            headers = [c.lower() for c in table[0]] if table else []
            code_idx = self._find_idx(headers, ("код", "тн вэд"), default=0)
            doc_idx = self._find_idx(headers, ("сертификат",), default=-1)
            if doc_idx == -1:
                doc_idx = self._find_idx(headers, ("декларац",), default=-1)
            if doc_idx == -1:
                doc_idx = self._find_idx(headers, ("форма", "подтверждения"), default=-1)
            name_idx = self._find_idx(headers, ("наименование",), default=min(1, max(len(headers) - 1, 0)))

            for row in table[1:] if len(table) > 1 else table:
                if not row:
                    continue
                code_cell = row[code_idx] if code_idx < len(row) else row[0]
                hs_code = self.clean_hs_code(code_cell)
                if not hs_code:
                    continue
                doc_text = row[doc_idx] if 0 <= doc_idx < len(row) else ""
                document_required = self._resolve_document(doc_text)
                description = row[name_idx] if name_idx < len(row) else "Подтверждение соответствия"
                parsed += 1
                yield ParsedMeasure(
                    hs_code=hs_code,
                    description=description,
                    document_required=document_required,
                )
        LOGGER.info("[%s] extracted records=%s", self.parser_name, parsed)

    @staticmethod
    def _find_idx(headers: list[str], hints: tuple[str, ...], default: int) -> int:
        for idx, h in enumerate(headers):
            if all(part in h for part in hints):
                return idx
        return default

    def _resolve_document(self, text: str) -> str:
        low = (text or "").lower()
        if "декларац" in low:
            return "Декларация о соответствии"
        if "сертификат" in low:
            return "Сертификат соответствия"
        return self.default_document_required


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Парсер нетарифных мер ЕАЭС (Решения 317, 318, 30).")
    p.add_argument(
        "--source-317",
        default="downloads/decision_317.pdf",
        help="URL или локальный путь к документу по Решению 317",
    )
    p.add_argument(
        "--source-318",
        default="downloads/decision_318.pdf",
        help="URL или локальный путь к документу по Решению 318",
    )
    p.add_argument(
        "--source-30",
        default="downloads/decision_30.pdf",
        help="URL или локальный путь к документу по Решению 30",
    )
    p.add_argument(
        "--downloads-dir",
        default="downloads",
        help="Папка для кэша скачанных документов",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Уровень логирования",
    )
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    downloads_dir = (ROOT / args.downloads_dir).resolve()
    parsers: list[EAEUParser] = [
        VetControlParser(args.source_317, downloads_dir),
        PhytoControlParser(args.source_318, downloads_dir),
        CertificateParser(args.source_30, downloads_dir),
    ]

    for parser in parsers:
        try:
            parser.run()
        except Exception as exc:
            LOGGER.exception("[%s] failed: %s", parser.parser_name, exc)

    LOGGER.info("parser_eaeu finished")


if __name__ == "__main__":
    main()

