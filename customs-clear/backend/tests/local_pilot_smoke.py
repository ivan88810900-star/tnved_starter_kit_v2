"""Check the published reference pilot against its retained on-disk inputs."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


def check(port, config, root):
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{port}"
    def request(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        req = Request(base + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=8) as reply:
                return reply.status, json.load(reply)
        except HTTPError as error:
            return error.code, json.load(error)

    pins = json.loads((Path(__file__).resolve().parents[1] / "data/local_pilot_pins.json").read_text())
    assert request("/api/health/ready")[1]["status"] == "ready"
    codes = ["3304100000", "4012110000"]
    if "41" in config["partitioned_chapters"]:
        codes.extend(["4101201000", "4106910000", "4106920000", "4107111100"])
        for heading in ("4108", "4109", "4110", "4111"):
            status, data = request("/api/local-ett/" + heading + "000000")
            assert status == 200 and data["rate"] is None
    if "42" in config["partitioned_chapters"]:
        codes.extend(["4202125001", "4203210000"])
        status, data = request("/api/local-ett/4204000000")
        assert status == 200 and data["rate"] is None
    if "43" in config["partitioned_chapters"]:
        codes.extend(["4301300000", "4302197500", "4302307110"])
    if "44" in config["partitioned_chapters"]:
        codes.extend(["4401110001", "4401390000", "4408393002", "4421999000"])
    for code in codes:
        if code[:2] in pins["chapters"]:
            entry = pins["chapters"][code[:2]]
            db = root / config["catalog_and_rates"] / (code[:2] + ".sqlite")
        else:
            entry = next(p for p in pins["partitioned_chapters"][code[:2]]["parts"] if p["first"] <= code <= p["last"])
            db = root / config["partitioned_rates"] / entry["file"]
        with db.open("rb") as raw:
            assert hashlib.file_digest(raw, "sha256").hexdigest() == entry["sha256"]
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as local:
            rows = local.execute("""SELECT n.original_duty_text, n.original_supplementary_unit,
                n.page_number, n.line_number, s.sha256, n.legal_status FROM ett_normalization_results n
                JOIN source_objects s ON n.source_id=s.source_id WHERE n.hs_code=?""", (code,)).fetchall()
        status, data = request("/api/local-ett/" + code)
        assert status == 200 and len(rows) == 1
        fields = ("original_duty_text", "original_supplementary_unit", "page_number", "line_number", "pdf_sha256", "legal_status")
        assert tuple(data["rate"][key] for key in fields) == rows[0]
        assert rows[0][-1] == "UNVERIFIED"

    for manual, amount in ((None, None), (0, 0), (7.55, 7550)):
        item = {"hs_code": "3304100000", "customs_value": 100000, "invoice_currency": "RUB"}
        if manual is not None:
            item["duty_rate"] = manual
        status, quote = request("/api/payments/quote", item)
        assert status == 200 and quote["total_payable_rub"] is None
        assert next(row["amount_rub"] for row in quote["line_items"] if row["code"] == "duty") == amount
    # The anonymous reference profile deliberately exposes only the archived registry.
    assert request("/api/non_tariff/normative-block", {"items": []})[0] == 503
    print("Passed: source rows, provenance, three manual quotes and protected route")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18017)
    args = parser.parse_args()
    check(args.port, json.loads(args.config.read_text()), args.root)
