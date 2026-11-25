"""Invoice suggestions from the read-only recovered tree and private, disposable drafts."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
import unicodedata
from contextlib import closing
from pathlib import Path

from fastapi import HTTPException

from .tnved_recovery_store import TnvedRecoveryStore


def _description_notice(description: str) -> str | None:
    # A simple word match cannot assign scope to a negation (material, use, etc.).
    if re.search(r"\b(без|не|нет|кроме|исключая|without|not|except|excluding)\b", description, re.I):
        return "В описании есть исключение. Укажите материал или назначение в положительной форме, чтобы подобрать кандидатов."
    return None


def _search_text(text: str) -> str:
    # The pinned PDF vocabulary uses е for ё. Keep document and source labels intact.
    return unicodedata.normalize("NFC", text).casefold().replace("ё", "е")


def _terms(description: str) -> list[str]:
    words = re.findall(r"[а-яa-z]{3,}", _search_text(description))
    terms = []
    for word in words:
        if word in {"для", "или", "как", "при", "без", "with", "and", "the", "from"}:
            continue
        # Search word endings the same way as the catalog's Russian text search.
        stem = word.rstrip("аеёиоуыэюяйьъ")
        term = stem if len(stem) >= 3 else word
        if term not in terms:
            terms.append(term)
    return terms


PRODUCT_KIND_QUESTION = "Какой это вид изделия и для чего оно предназначено? Укажите общее название товара."


def find_candidates(store: TnvedRecoveryStore, description: str, clarification: str = "") -> tuple[list[dict], bool, str | None]:
    notice = _description_notice(description) or _description_notice(clarification)
    if notice:
        return [], False, notice
    category = _terms(clarification)
    description_terms = _terms(description)
    terms = list(dict.fromkeys([*category, *description_terms]))
    if not terms or len(category or terms) > 8 or (clarification and not category):
        return [], False, PRODUCT_KIND_QUESTION
    # A word missing from the tree may be the product itself, anywhere in the
    # description. Matching only known modifiers cannot establish its category.
    required = set(category)
    pages = []
    for term in terms[:8]:
        page = store.search_page(term, limit=200)
        if not page["total"] and (not category or term in required):
            return [], False, PRODUCT_KIND_QUESTION
        pages.append((term, page))
    active_terms = [term for term, page in pages if page["total"]]
    scored = {}
    best = 0
    for _, page in pages:
        for item in page["results"]:
            code = item.get("code") or ""
            if item["kind"] != "coded" or not re.fullmatch(r"[0-9]{10}", code) or code in scored:
                continue
            words = re.findall(r"[а-яa-z]+", _search_text(" ".join(item["path"])))
            matched = {term for term in active_terms if any(word.startswith(term) for word in words)}
            if not required.issubset(matched) or store.has_children(code):
                continue
            score = len(matched)
            scored[code] = (score, {"code": code, "label": item["label"], "path": item["path"]})
            best = max(best, score)
    matches = [item for score, item in scored.values() if score == best]
    matches.sort(key=lambda row: row["code"])
    # Every candidate satisfies every explicit category term. One complete
    # category page covers the whole intersection, even if a modifier is common.
    complete = {term for term, page in pages if page["total"] and not page["has_more"]}
    omitted_pages = any(page["has_more"] for _, page in pages)
    all_best_covered = bool(complete & required) or (bool(complete) and best == len(active_terms))
    partial = omitted_pages and not all_best_covered
    limited = partial or len(matches) > 40 or len(terms) > 8
    return matches[:40], limited, None if matches else PRODUCT_KIND_QUESTION


def _groups(candidates: list[dict]) -> dict[str, list[dict]]:
    if len(candidates) < 2:
        return {}
    for depth in range(max(len(c["path"]) for c in candidates)):
        groups = {}
        for candidate in candidates:
            path = candidate["path"]
            label = path[depth] if depth < len(path) else path[-1]
            groups.setdefault(label, []).append(candidate)
        if len(groups) > 1:
            return groups
    return {}


def _option(label: str, codes: list[dict]) -> str:
    # Include the branch membership so an answer from a different question fails.
    signature = json.dumps([label, [c["code"] for c in codes]], ensure_ascii=False)
    return hashlib.sha256(signature.encode()).hexdigest()[:24]


def narrow_candidates(candidates: list[dict], answers: list[str]) -> tuple[list[dict], dict | None]:
    groups = _groups(candidates)
    for answer in answers:
        chosen = next((group for label, group in groups.items() if _option(label, group) == answer), None)
        if chosen is None:
            raise HTTPException(422, "Ответ не соответствует текущей развилке справочника.")
        candidates = chosen
        groups = _groups(candidates)
    question = None
    if groups:
        question = {
            "text": "Какое описание в справочнике подходит вашему товару?",
            "options": [{"value": _option(label, codes), "label": label} for label, codes in groups.items()],
        }
    return candidates, question


class PilotDrafts:
    """One DB per pilot process, inside its TemporaryDirectory. No global product DB."""

    def __init__(self, scratch: Path):
        self.path = scratch / "invoice-drafts.sqlite"
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE draft_lines (
                owner TEXT NOT NULL, draft_id TEXT NOT NULL, line INTEGER NOT NULL,
                description TEXT NOT NULL, quantity REAL, unit TEXT NOT NULL,
                selected_code TEXT, clarification TEXT NOT NULL DEFAULT '', PRIMARY KEY (owner,draft_id,line))""")
            db.commit()

    def create(self, owner: str, rows: list[dict]) -> dict:
        if not rows:
            raise HTTPException(422, "В инвойсе не найдены строки с описанием товара.")
        if len(rows) > 200:
            raise HTTPException(422, "Локальный инвойс поддерживает до 200 товарных строк.")
        draft_id = uuid.uuid4().hex
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany("INSERT INTO draft_lines(owner,draft_id,line,description,quantity,unit) VALUES (?,?,?,?,?,?)", (
                (owner, draft_id, r["line"], r["description"], r["quantity"], r["unit"]) for r in rows
            ))
        return self.read(owner, draft_id)

    def read(self, owner: str, draft_id: str) -> dict:
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            lines = db.execute("""SELECT line,description,quantity,unit,selected_code,clarification FROM draft_lines
                                  WHERE owner=? AND draft_id=? ORDER BY line""", (owner, draft_id)).fetchall()
        if not lines:
            raise HTTPException(404, "Черновик не найден в этом локальном запуске.")
        return {"draft_id": draft_id, "lines": [dict(row) for row in lines]}

    def line(self, owner: str, draft_id: str, number: int) -> dict:
        for row in self.read(owner, draft_id)["lines"]:
            if row["line"] == number:
                return row
        raise HTTPException(404, "Строка инвойса не найдена.")

    def choose(self, owner: str, draft_id: str, number: int, code: str, clarification: str) -> dict:
        with closing(sqlite3.connect(self.path)) as db, db:
            changed = db.execute("""UPDATE draft_lines SET selected_code=?,clarification=?
                                    WHERE owner=? AND draft_id=? AND line=?""", (code, clarification, owner, draft_id, number))
            if not changed.rowcount:
                raise HTTPException(404, "Строка инвойса не найдена.")
        return self.read(owner, draft_id)
