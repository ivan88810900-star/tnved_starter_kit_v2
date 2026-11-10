"""Compare every official chapter's actual rows, not preset catalog counts."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.tnved_fidelity import compact, extract_pdf_rows


def digest(value):
    return hashlib.sha256(value).hexdigest()


def proof(row):
    return {"page": row["page"], "depth": row["depth"],
            "labelSha256": digest(compact(row.get("raw_label", row["label"])).encode()),
            "pathSha256": digest(json.dumps([compact(v) for v in row.get("raw_path", row["path"])], ensure_ascii=False, separators=(",", ":")).encode())}


def layout_codes(pdf, chapter, executable):
    """Second code-cell method: whitespace layout, no candidate/SQLite input."""
    text = subprocess.check_output([executable, "-layout", "-enc", "UTF-8", str(pdf), "-"], stderr=subprocess.PIPE).decode()
    result = []
    for page, contents in enumerate(text.split("\f"), 1):
        if "Наименование позиции" not in contents:
            continue
        lines = contents.splitlines()
        begin = next(i for i, line in enumerate(lines) if "долларах США)" in line)
        for line in lines[begin + 1:]:
            match = re.match(r"^ {0,5}(\+?) *(\d{4}(?: \d{2}(?: \d{2,3}(?: \d)?)?)?) {2,}\S", line)
            if match:
                code = match[2].replace(" ", "")
                if code.startswith(chapter) and len(code) in (4, 6, 8, 9, 10):
                    result.append({"code": code, "page": page, "symbol": match[1]})
    return result


def run(accepted_root, current_root, baseline, output, executable):
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "source-rows"
    cache.mkdir(exist_ok=True)
    original = json.loads((accepted_root / "data/tnved/source-collection-manifest.json").read_text())
    inventory_raw = (accepted_root / "data/tnved/independent-snapshot-inventory.json").read_bytes()
    if digest(inventory_raw) != "96140d3986ed9cf33177f5a22ff5f0c8ebf950e1fc7327a0b28c3faedba11ba6":
        raise ValueError("retained independent inventory pin mismatch")
    inventory = json.loads(inventory_raw)
    current = json.loads((current_root / "manifest.json").read_text())
    old_meta = {r["chapter"]: r for r in original["chapters"]}
    expected_chapters = [f"{n:02}" for n in range(1, 98) if n != 77]
    if [r["chapter"] for r in current["chapters"]] != expected_chapters:
        raise ValueError("official chapter coverage differs")
    uri = baseline.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        baseline_rows = [dict(row) for row in db.execute("SELECT * FROM recovery_nodes ORDER BY code")]
    def one(meta):
        chapter = meta["chapter"]
        old_path = accepted_root / "data/tnved/raw/chapters" / ("chapter-" + chapter + ".pdf")
        if not old_path.exists() and chapter == "95":
            old_path = accepted_root / "data/tnved/raw/ru.95_2022.pdf"
        new_path = current_root / ("chapter-" + chapter + ".pdf")
        if digest(old_path.read_bytes()) != old_meta[chapter]["sha256"] or digest(new_path.read_bytes()) != meta["sha256"]:
            raise ValueError("source bytes mismatch: " + chapter)
        old = extract_pdf_rows(old_path, chapter, executable)
        new = old if old["source_sha256"] == meta["sha256"] else extract_pdf_rows(new_path, chapter, executable)
        for label, result in (("accepted", old), ("current", new)):
            (cache / f"{label}-{chapter}.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        old_rows = [r for r in old["rows"] if r["code"]]
        new_rows = [r for r in new["rows"] if r["code"]]
        own = [r for r in baseline_rows if r["code"].startswith(chapter) and len(r["code"]) > 2]
        actual = {r["code"]: r for r in own}
        old_by_code = {r["code"]: r for r in old_rows}
        new_by_code = {r["code"]: r for r in new_rows}
        current_layout = layout_codes(new_path, chapter, executable)
        independent_codes = [{"code": r["code"], "page": r["page"], "symbol": r["change_symbol"]} for r in new_rows]
        independent_proof = [{"code": r["code"], "symbol": r["change_symbol"], **proof(r)} for r in old_rows]
        retained = inventory["chapters"][chapter]
        discrepancies = []
        def difference(kind, code, expected, actual, page=None, layer="model"):
            discrepancies.append({"kind": kind, "code": code, "page": page, "expected": expected, "actual": actual, "layer": layer})
        for code in sorted(set(old_by_code) - set(actual)):
            difference("missing_coded_row", code, old_by_code[code]["label"], None, old_by_code[code]["page"], "extraction")
        for code in sorted(set(actual) - set(old_by_code)):
            difference("extra_coded_row", code, None, actual[code]["label"], actual[code]["page"], "extraction")
        for code in sorted(set(actual) & set(old_by_code)):
            a, e = actual[code], old_by_code[code]
            if compact(a["label"]) != compact(e["raw_label"]):
                difference("changed_label", code, e["raw_label"], a["label"], e["page"], "extraction")
            if a["parent_code"] != e["code_parent"]:
                difference("coded_parent", code, e["code_parent"], a["parent_code"], e["page"])
            source_path = [compact(v) for v in e["raw_path"]]
            if [compact(v) for v in json.loads(a["path_json"])[1:]] != source_path:
                difference("source_path", code, e["path"], json.loads(a["path_json"])[1:], e["page"], "extraction")
        title_row = next(r for r in baseline_rows if r["code"] == chapter)
        if compact(re.sub(r"^ГРУППА\s+" + chapter + r"\s*", "", title_row["label"], flags=re.I)).casefold() != compact(meta["title"]).casefold():
            difference("chapter_title", chapter, meta["title"], title_row["label"], title_row["page"], "extraction")
        for parent in sorted({r["code_parent"] for r in old_rows}):
            expected = [r["code"] for r in old_rows if r["code_parent"] == parent]
            observed = sorted([r["code"] for r in own if r["parent_code"] == parent], key=lambda code: (len(code), code))
            if observed != expected:
                difference("child_order_or_membership", parent, expected, observed, layer="API")
        edition_delta = {"missing": sorted(set(old_by_code) - set(new_by_code)), "extra": sorted(set(new_by_code) - set(old_by_code)), "changed": []}
        for code in sorted(set(old_by_code) & set(new_by_code)):
            a, b = old_by_code[code], new_by_code[code]
            fields = [key for key in ("label", "path", "depth", "page", "change_symbol") if a[key] != b[key]]
            if fields:
                edition_delta["changed"].append({"code": code, "fields": fields, "accepted": {key: a[key] for key in fields}, "current": {key: b[key] for key in fields}})
        # Compare uncoded occurrences separately: a set of labels would merge
        # repeated "прочие" rows and miss a changed hierarchy or page.
        uncoded_fields = ("page", "depth", "label", "path", "change_symbol", "kind", "source_order")
        uncoded_before = [{k: r[k] for k in uncoded_fields} for r in old["rows"] if not r["code"]]
        uncoded_current = [{k: r[k] for k in uncoded_fields} for r in new["rows"] if not r["code"]]
        edition_delta["codeless_changed"] = [] if uncoded_before == uncoded_current else [{"accepted": uncoded_before, "current": uncoded_current}]
        edition_delta["reserved_changed"] = [] if old["reserved"] == new["reserved"] else [{"accepted": old["reserved"], "current": new["reserved"]}]
        uncoded_proof = [proof(r) for r in old["rows"] if not r["code"]]
        summary = {
            "chapter": chapter, "title": meta["title"], "source_url": meta["url"], "source_sha256": meta["sha256"],
            "accepted_source_sha256": old["source_sha256"], "source_bytes_changed": old["source_sha256"] != meta["sha256"],
            "legal_status": "unverified", "valid_from": None,
            "printed_coded_rows": len(new_rows), "unique_ten_digit_codes": len({r["code"] for r in new_rows if len(r["code"]) == 10}),
            "intermediate_coded_rows": sum(len(r["code"]) < 10 for r in new_rows), "codeless_rows": sum(not r["code"] for r in new["rows"]),
            "reserved_rows": len(new["reserved"]), "candidate_before_coded_rows": len(own),
            "duplicate_codes": [code for code, count in Counter(r["code"] for r in new_rows).items() if count > 1],
            "layout_vs_bbox_codes_match": current_layout == independent_codes,
            "retained_independent_coded_proof_match": independent_proof == retained["codedRows"],
            "retained_independent_codeless_proof_match": uncoded_proof == retained["uncodedRows"],
            "retained_independent_reserved_match": old["reserved"] == retained["reserved"],
            "parse_issues": new["issues"], "before_discrepancies": len(discrepancies),
            "text_projection_version": new["text_projection_version"],
            "labels_with_source_join_correction": sum(r["label"] != r["raw_label"] for r in new["rows"]),
            "unknown_line_separator_evidence": sum(line["trailing_space"] is None for r in new["rows"] for line in r["raw_lines"]),
            "edition_delta_counts": {k: len(v) for k, v in edition_delta.items()},
        }
        print(chapter, summary["printed_coded_rows"], summary["codeless_rows"], "proof", summary["retained_independent_coded_proof_match"], "layout", summary["layout_vs_bbox_codes_match"], flush=True)
        return {"summary": summary, "before_discrepancies": discrepancies, "edition_delta": edition_delta}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, current["chapters"]))
    report = {"task": "TARIFF-TREE-OFFICIAL-FIDELITY-20261106", "method": "header-gated PDF word-coordinate rows + independent layout code occurrences + immutable retained physical-cell row proofs", "current_index_sha256": current["index_sha256"], "chapters": [r["summary"] for r in results]}
    report["status"] = "PASS" if all(
        not r["parse_issues"] and not r["duplicate_codes"] and
        all(r[k] for k in ("layout_vs_bbox_codes_match", "retained_independent_coded_proof_match", "retained_independent_codeless_proof_match", "retained_independent_reserved_match"))
        for r in report["chapters"]
    ) else "DIFFERENCES"
    (output / "official-96-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (output / "official-96-discrepancies.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    return report


def audit_candidate(candidate, current_root, rows_root, url, output):
    import httpx
    manifest = json.loads((current_root / "manifest.json").read_text())
    pin = digest(candidate.read_bytes())
    def check(chapter_meta):
        chapter = chapter_meta["chapter"]
        source = json.loads((rows_root / ("current-" + chapter + ".json")).read_text())
        expected = {r["id"]: r for r in source["rows"]}
        title = chapter_meta["title"].replace("\u200b", "").strip()
        expected[chapter] = {"id": chapter, "code": chapter, "label": title, "path": [], "page": None}
        child_sets = {}
        for row in source["rows"]:
            child_sets.setdefault(row["parent_id"], []).append(row["id"])
        differences, seen, requests = [], set(), 0
        with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
            def get(path, params=None):
                nonlocal requests
                requests += 1
                response = client.get(path, params=params)
                if response.status_code != 200:
                    differences.append({"kind": "HTTP_status", "path": path, "actual": response.status_code})
                    return None
                body = response.json()
                if body.get("snapshot_sha256") != pin:
                    differences.append({"kind": "wrong_snapshot", "path": path})
                return body
            queue = [chapter]
            while queue:
                parent = queue.pop()
                if parent in seen:
                    differences.append({"kind": "cycle_or_duplicate", "node": parent})
                    continue
                seen.add(parent)
                body = get("/api/tnved/children/" + parent)
                if body is None:
                    continue
                actual_ids = [row["node_id"] for row in body["items"]]
                if actual_ids != child_sets.get(parent, []):
                    differences.append({"kind": "children_membership_or_order", "node": parent, "expected": child_sets.get(parent, []), "actual": actual_ids})
                queue.extend(reversed(actual_ids))
                detail = get("/api/v1/tnved/" + parent)
                row = expected.get(parent)
                if detail is None or row is None:
                    continue
                expected_path = [title] + row["path"] if parent != chapter else [title]
                for key, value in (("code", row["code"] or ""), ("name", row["label"]), ("path", expected_path), ("rates", None), ("legal_status", "unverified"), ("valid_from", None), ("complete", False)):
                    if detail.get(key) != value:
                        differences.append({"kind": "detail_content", "node": parent, "page": row["page"], "field": key, "expected": value, "actual": detail.get(key)})
                if parent != chapter:
                    for field, value in (("raw_name", row["raw_label"]), ("dash_depth", row["depth"]), ("kind", row["kind"])):
                        if detail.get(field) != value:
                            differences.append({"kind": "source_text_projection", "node": parent, "field": field, "expected": value, "actual": detail.get(field)})
                    for field, value in (("source_sha256", chapter_meta["sha256"]), ("source_url", chapter_meta["url"]), ("page", row["page"])):
                        if detail.get(field) != value:
                            differences.append({"kind": "wrong_source_reference", "node": parent, "field": field, "expected": value, "actual": detail.get(field)})
                breadcrumb = detail.get("breadcrumb", [])
                chain, ancestor = [parent], row
                while ancestor.get("parent_id"):
                    chain.insert(0, ancestor["parent_id"])
                    ancestor = expected[ancestor["parent_id"]]
                if [r["node_id"] for r in breadcrumb[1:]] != chain or [r["title"] for r in breadcrumb[1:]] != [expected[k]["label"] for k in chain]:
                    differences.append({"kind": "breadcrumb_chain", "node": parent, "expected": chain})
            if seen != set(expected):
                differences.append({"kind": "reachability", "missing": sorted(set(expected) - seen), "extra": sorted(seen - set(expected))})
            search_ids, cursor, reported = [], None, None
            while True:
                body = get("/api/v1/tnved/search", {"q": chapter, **({"cursor": cursor} if cursor else {})})
                if body is None:
                    break
                reported = body["total"]
                search_ids.extend(row["code"] for row in body["results"])
                cursor = body["next_cursor"]
                if not cursor:
                    break
            expected_codes = [chapter] + [r["code"] for r in source["rows"] if r["code"]]
            if search_ids != expected_codes or reported != len(expected_codes):
                differences.append({"kind": "search_full_sequence", "expected_count": len(expected_codes), "reported": reported, "missing": sorted(set(expected_codes) - set(search_ids)), "extra": sorted(set(search_ids) - set(expected_codes)), "duplicate_count": len(search_ids) - len(set(search_ids))})
            prefixes = {}
            for row in source["rows"]:
                if row["code"] and row["depth"] == 0 and len(row["code"]) > 4 and row["code"][:4] not in expected:
                    prefixes.setdefault(row["code"][:4], []).append(row["code"])
            for prefix, codes in prefixes.items():
                if len(codes) == 1:
                    body = get("/api/v1/tnved/" + prefix)
                    if body is None or body.get("code") != codes[0] or (body.get("navigation_alias") or {}).get("heading_code") != prefix:
                        differences.append({"kind": "combined_heading_alias", "prefix": prefix, "expected_printed_code": codes[0]})
        print("API", chapter, len(seen), "nodes", requests, "requests", len(differences), "differences", flush=True)
        return {"chapter": chapter, "source_sha256": chapter_meta["sha256"], "coded_rows": len(expected_codes) - 1, "ten_digit_codes": sum(len(c) == 10 for c in expected_codes), "codeless_nodes": sum(not r["code"] for r in source["rows"]), "reachable_nodes": len(seen), "search_results_checked": len(search_ids), "HTTP_requests": requests, "differences": differences}
    with ThreadPoolExecutor(max_workers=4) as pool:
        chapters = list(pool.map(check, manifest["chapters"]))
    section_differences = []
    with httpx.Client(base_url=url, trust_env=False) as client:
        sections = client.get("/api/tnved/children").json()["items"]
        if [compact(r["name"]) for r in sections] != [compact(r["title"]) for r in manifest["sections"]]:
            section_differences.append({"kind": "section_titles"})
        for section in sections:
            items = client.get("/api/tnved/children/" + section["code"]).json()["items"]
            for row in items:
                e = next(m for m in manifest["chapters"] if m["chapter"] == row["code"])
                if row["name"] != e["title"].strip():
                    section_differences.append({"kind": "chapter_title", "chapter": row["code"]})
    result = {"snapshot_sha256": pin, "chapters": chapters, "section_differences": section_differences, "status": "PASS" if not section_differences and all(not ch["differences"] for ch in chapters) else "DIFFERENCES", "legal_status": "unverified", "scope": "all source rows/edges/names/order/HTTP reachability and all numeric search pages; no legal/rate admission"}
    (output / "candidate-96-http.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("accepted-root", "current-root", "baseline", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--pdftotext", default="pdftotext")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--url")
    args = parser.parse_args()
    source_result = run(args.accepted_root, args.current_root, args.baseline, args.output, args.pdftotext)
    if source_result["status"] != "PASS":
        raise SystemExit(1)
    if args.candidate:
        result = audit_candidate(args.candidate, args.current_root, args.output / "source-rows", args.url, args.output)
        if result["status"] != "PASS":
            raise SystemExit(1)
