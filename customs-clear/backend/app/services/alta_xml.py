"""Parse Alta-Soft XML responses (Error, TikList, result)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List


def parse_alta_error(root: ET.Element) -> Dict[str, str] | None:
    if root.tag != "Error":
        return None
    code = (root.findtext("ErrorCode") or "").strip()
    descr = (root.findtext("ErrorDescr") or "").strip()
    return {"error_code": code, "error_descr": descr}


def parse_tik_list(xml_text: str) -> Dict[str, Any]:
    root = ET.fromstring(xml_text)
    err = parse_alta_error(root)
    if err:
        return {"status": "ERROR", **err, "items": []}
    if root.tag != "TikList":
        return {"status": "ERROR", "error_descr": f"Unexpected XML root: {root.tag}", "items": []}

    items: List[Dict[str, Any]] = []
    for info in root.findall("TikInfo"):
        code = (info.findtext("Code") or "").strip()
        count_raw = (info.findtext("Count") or "").strip()
        try:
            count = int(count_raw) if count_raw else 0
        except ValueError:
            count = 0
        notes: List[Dict[str, str]] = []
        notes_el = info.find("Notes")
        if notes_el is not None:
            for note in notes_el.findall("Note"):
                name = (note.findtext("Name") or "").strip()
                if name:
                    notes.append({"name": name})
        if code or notes:
            items.append({"code": code, "count": count, "notes": notes})
    return {"status": "OK", "items": items}


def parse_apu_suggest(xml_text: str) -> Dict[str, Any]:
    root = ET.fromstring(xml_text)
    err = parse_alta_error(root)
    if err:
        return {"status": "ERROR", **err, "lines": []}
    if root.tag != "result":
        return {"status": "ERROR", "error_descr": f"Unexpected XML root: {root.tag}", "lines": []}

    lines: List[Dict[str, Any]] = []
    for line in root.findall("line"):
        lines.append(
            {
                "term": (line.findtext("term") or "").strip(),
                "tngroup": (line.findtext("tngroup") or "").strip(),
                "payload": (line.findtext("payload") or "").strip(),
                "weight": (line.findtext("weight") or "").strip(),
            }
        )
    return {"status": "OK", "lines": lines}


def parse_apu_codes(xml_text: str) -> Dict[str, Any]:
    root = ET.fromstring(xml_text)
    err = parse_alta_error(root)
    if err:
        return {"status": "ERROR", **err, "lines": []}
    if root.tag != "result":
        return {"status": "ERROR", "error_descr": f"Unexpected XML root: {root.tag}", "lines": []}

    lines: List[Dict[str, Any]] = []
    for line in root.findall("line"):
        w = (line.findtext("weight") or "").strip()
        try:
            weight = int(w) if w else None
        except ValueError:
            weight = None
        lines.append(
            {
                "tnved": (line.findtext("tnved") or "").strip(),
                "weight": weight,
                "descr": (line.findtext("descr") or "").strip(),
                "descr_sh": (line.findtext("descr_sh") or "").strip(),
                "tncode": (line.findtext("tncode") or "").strip(),
            }
        )
    return {"status": "OK", "lines": lines}
