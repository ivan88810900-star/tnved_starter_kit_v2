"""Build a new, explicitly pinned local candidate; never overwrite a snapshot."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.tnved_fidelity import NAVIGATION_SCHEMA, SOURCE_TEXT_SCHEMA, printed_code


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build(source_root: Path, rows_root: Path, output: Path, manifest_pin: str, accepted_catalog: Path, accepted_pin: str):
    artifacts = (output, output.with_suffix(".manifest.json"), output.with_suffix(".source-catalog.json"), output.with_name("." + output.name + ".projection"))
    if any(path.exists() or path.is_symlink() for path in artifacts):
        raise ValueError("Refusing to overwrite an existing candidate artifact")
    manifest_path = source_root / "manifest.json"
    if sha(manifest_path.read_bytes()) != manifest_pin:
        raise ValueError("Explicit official collection manifest pin mismatch")
    if sha(accepted_catalog.read_bytes()) != accepted_pin:
        raise ValueError("Accepted catalog pin mismatch")
    accepted = json.loads(accepted_catalog.read_text())
    old_nodes = {node["code"]: node for node in accepted["nodes"]}
    old_sources = {source["id"]: source for source in accepted["sources"]}
    old_index_id = "accepted-index-" + old_sources["eec-ett-index"]["sha256"][:16]
    retained_sources = [{**source, "id": old_index_id if source["id"] == "eec-ett-index" else source["id"]} for source in accepted["sources"]]
    retained_notes = [{**note, "sourceId": old_index_id if note["sourceId"] == "eec-ett-index" else note["sourceId"]} for note in accepted["notes"]]
    manifest = json.loads(manifest_path.read_text())
    entries = manifest["chapters"]
    chapters = tuple(f"{n:02}" for n in range(1, 98) if n != 77)
    if tuple(e["chapter"] for e in entries) != chapters:
        raise ValueError("Incomplete official collection")
    index = source_root / "index.html"
    if sha(index.read_bytes()) != manifest["index_sha256"]:
        raise ValueError("Official index pin mismatch")
    spec = importlib.util.spec_from_file_location("existing_recovery_builder", Path(__file__).with_name("build_tnved_recovery.py"))
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    sections = builder.parse_sections(index.read_bytes())
    corpus_sha = sha(json.dumps([(e["chapter"], e["sha256"]) for e in entries], separators=(",", ":")).encode())
    catalog = {"schemaVersion": 1, "id": "official-tree-" + corpus_sha[:20], "generatedAt": None,
               "importCoverage": {"acceptedChapters": list(chapters), "failedChapters": []},
               "sources": retained_sources + [{"id": "eec-ett-index", "url": manifest["index_url"], "title": "Официальный указатель ЕЭК", "sha256": manifest["index_sha256"], "mediaType": "text/html", "rawPath": "index.html"}],
               "editions": [], "nodes": [], "notes": retained_notes}
    navigation, aliases, unresolved, source_text = [], [], [], []
    chapter_sections = {}
    for order, section in enumerate(sections):
        code = section["roman"]
        navigation.append((code, None, section["title"], None, None, order, "eec-ett-index", None, "index-section-" + code, "section", json.dumps([section["title"]], ensure_ascii=False), code, ""))
        source_text.append((code, section["title"], "[]", None))
        for number, chapter in enumerate(section["chapters"]):
            chapter_sections[chapter] = (code, number)
    for entry in entries:
        ch = entry["chapter"]
        pdf = source_root / ("chapter-" + ch + ".pdf")
        if entry.get("status") != "collected" or sha(pdf.read_bytes()) != entry["sha256"]:
            raise ValueError("Official PDF pin mismatch: " + ch)
        result = json.loads((rows_root / ("current-" + ch + ".json")).read_text())
        if result["source_sha256"] != entry["sha256"] or result["issues"] or result.get("text_projection_version") != 2:
            raise ValueError("Unresolved source extraction: " + ch)
        rows = result["rows"]
        if any(line["trailing_space"] is None for row in rows for line in row["raw_lines"]):
            raise ValueError("Unverified source character boundary: " + ch)
        prior_source = old_sources[old_nodes[ch]["sourceId"]]
        source_id = prior_source["id"] if prior_source["sha256"] == entry["sha256"] else "eec-ch" + ch + "-" + entry["sha256"][:12]
        edition_id = "edition-" + ch + "-" + entry["sha256"][:16]
        title = entry["title"].replace("\u200b", "").strip()
        if source_id not in old_sources:
            catalog["sources"].append({"id": source_id, "url": entry["url"], "title": title, "sha256": entry["sha256"], "mediaType": "application/pdf", "rawPath": "chapter-" + ch + ".pdf"})
        historical = next(e for e in accepted["editions"] if e["id"] == old_nodes[ch]["editionId"])
        historical_ids = [old_index_id if identifier == "eec-ett-index" else identifier for identifier in historical["sourceIds"]]
        catalog["editions"].append({"id": edition_id, "sourceIds": sorted(set(historical_ids + [source_id, "eec-ett-index"])), "validFrom": None, "validTo": None, "chainStatus": "unverified", "complete": False, "chapters": [ch], "limitations": ["Published structural snapshot; legal applicability and rates unverified.", "Accepted historical notes/source provenance are preserved, not admitted as current legal material."]})
        catalog["nodes"].append({"code": ch, "label": title, "parentCode": None, "editionId": edition_id, "sourceId": source_id, "page": old_nodes[ch]["page"], "path": [title], "noteRefs": old_nodes[ch]["noteRefs"]})
        section, chapter_order = chapter_sections[ch]
        navigation.append((ch, ch, title, section, ch, chapter_order, "eec-ett-index", None, "index-chapter-" + ch, "chapter", json.dumps([title], ensure_ascii=False), ch, ""))
        source_text.append((ch, title, "[]", None))
        real_codes = {r["code"] for r in rows if r["code"]}
        grouped = {}
        for row in rows:
            path = [title] + row["path"]
            if row["code"]:
                catalog["nodes"].append({"code": row["code"], "label": row["label"], "parentCode": row["code_parent"], "editionId": edition_id, "sourceId": source_id, "page": row["page"], "path": path, "noteRefs": old_nodes.get(row["code"], old_nodes[ch])["noteRefs"], "changeSymbol": row["change_symbol"]})
                # A heading alias is justified only by an actual depth-zero
                # combined printed row. It is not a new normative code/node.
                if row["depth"] == 0 and len(row["code"]) > 4 and row["code"][:4] not in real_codes:
                    grouped.setdefault(row["code"][:4], []).append(row["id"])
            navigation.append((row["id"], row["code"], row["label"], row["parent_id"], ch, row["source_order"], source_id, row["page"], row["source_row_id"], row["kind"], json.dumps(path, ensure_ascii=False), printed_code(row["code"]) if row["code"] else "", row["change_symbol"]))
            source_text.append((row["id"], row["raw_label"], json.dumps(row["raw_lines"], ensure_ascii=False), row["depth"]))
        for heading, ids in grouped.items():
            if len(ids) == 1:
                aliases.append((heading, ids[0]))
            else:
                unresolved.append({"heading": heading, "source_rows": ids, "reason": "ambiguous_combined_heading"})
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog_path = output.with_suffix(".source-catalog.json")
    if catalog_path.exists():
        raise ValueError("Refusing to overwrite a source catalog")
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    counts = {key: len(catalog[key]) for key in ("sources", "editions", "nodes", "notes")}
    counts["ten_digit"] = sum(len(n["code"]) == 10 for n in catalog["nodes"])
    temporary = output.with_name("." + output.name + ".projection")
    # Reuse existing schema, deterministic build, provenance/FK/cycle validator.
    # The old operational build() retains its immutable accepted input pins.
    builder._build_with_pins(catalog_path, index, temporary, None, catalog_sha256=sha(catalog_path.read_bytes()), index_sha256=manifest["index_sha256"], expected_counts=counts, expected_chapters=chapters, expected_section_count=21)
    with closing(sqlite3.connect(temporary)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(NAVIGATION_SCHEMA + SOURCE_TEXT_SCHEMA)
        with db:
            db.executemany("INSERT INTO recovery_navigation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", navigation)
            db.executemany("INSERT INTO recovery_heading_aliases VALUES (?,?)", aliases)
            db.executemany("INSERT INTO recovery_source_text VALUES (?,?,?,?)", source_text)
            db.executemany("INSERT INTO recovery_metadata VALUES (?,?)", [("navigation_schema", "1"), ("source_corpus_sha256", corpus_sha), ("collection_manifest_sha256", manifest_pin)])
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Navigation foreign key violation")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Candidate integrity check failed")
        db.execute("VACUUM")
    temporary.replace(output)
    output.chmod(0o444)
    report = {"sqlite_sha256": sha(output.read_bytes()), "source_corpus_sha256": corpus_sha, "collection_manifest_sha256": manifest_pin, "accepted_catalog_sha256": accepted_pin, "counts": counts, "navigation_nodes": len(navigation), "codeless_nodes": sum(row[9] in ("codeless", "caption") for row in navigation), "heading_aliases": len(aliases), "unresolved_aliases": unresolved, "legal_status": "unverified", "rates_present": False, "preserved_historical_notes": len(retained_notes), "notes_admitted": False, "text_projection_version": 2, "source_text_records": len(source_text)}
    output.with_suffix(".manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for arg in ("source-root", "rows-root", "output"):
        p.add_argument("--" + arg, required=True, type=Path)
    p.add_argument("--manifest-sha256", required=True)
    p.add_argument("--accepted-catalog", required=True, type=Path)
    p.add_argument("--accepted-catalog-sha256", required=True)
    a = p.parse_args()
    print(json.dumps(build(a.source_root, a.rows_root, a.output, a.manifest_sha256, a.accepted_catalog, a.accepted_catalog_sha256), ensure_ascii=False))
