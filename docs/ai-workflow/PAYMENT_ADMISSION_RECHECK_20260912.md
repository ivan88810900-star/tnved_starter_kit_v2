# Payment admission recheck — 12 September 2026

Task: TARIFF-ADMISSION-RECHECK-001. Author: A1, native session `/root/smoke_rates`.
Current reviewed PR #187 source: `a9d15c74699c8cd7842404580ff6fd7bd957e9eb`.
Report branch: `agent/rates-tariff-admission-recheck-001-9231ffbdb5`.
Worktree: `/workspace/scratch/cd6734a40504/tariff-agent-worktrees/tariff-admission-recheck-001-9231ffbdb5`.
Starting report-branch merge: `2e5da9ecfb74ef386b6695eba24abd62ae993776`.

## Current conclusions and superseded evidence

A0 finding `A0-UPSTREAM-DRIFT-001` invalidated the previous report's claims about
**current** open admission paths. Its observations at
`22a7df5590a7442d943d89af285feb1228e80938` remain historical only:
import-duty apply, Tamdoc approval and marker-based readiness then lacked the
current guards. They are **fixed upstream at the current source SHA**; do not
repeat those completed fixes. The old A5 run was interrupted and gives no pass
for this revision.

| Question | Current classification | Evidence |
|---|---|---|
| Unapplied/unreviewed computable remedy enters raw total and VAT base | **CONFIRMED / INTENTIONAL** | The resolver keeps `applied=False`, `legal_review_verified=False`, `status=provisional`; raw results remain `REVIEW_REQUIRED`. Current decisions preserve this distinction. |
| Preliminary money escapes as a final quote or proven savings | **UNCONFIRMED; safeguards reproduced** | Four current-source cases produce null final quote, null remedy/dependent VAT amounts and VAT basis, null comparison deltas, warnings and conservative history metadata. |
| Pending counters disagree | **UNCONFIRMED as a counter defect** | No shared exported pending counter was found in quote/schema or the inspected payment coverage summaries. The related A6 finding about evaluating `pending` before appending `legal_review_unverified` is explicitly **intentional**: calculability and legal approval are separate axes. |
| Previously open dedicated apply/Tamdoc/readiness paths | **FIXED UPSTREAM / RECHECKED** | All six apply success-parser branches reject admission; parser errors remain errors. Tamdoc writers reject, approval preserves pending candidates, and readiness cannot grant admission from parsing/SourceStatus. |
| Full legally approved rate/source coverage is complete | **Not established** | The completed block is technical admission safety. Formal temporal applicability, dependent acts, specific-duty units, retention and human authorization remain separate gates. |

Read current `AGENTS.md`, `.ai/DECISIONS.md`, the
[latest focus](CURRENT_PROJECT_FOCUS.md), [completed admission task](TASK-RATE-ADMISSION-RECOVERY.md)
and [A6 reconciliation](A6_PAYMENT_AUDIT_RECONCILIATION.md). The September 12
implementation clarification supersedes historical next-step paragraphs and the
old upward-coefficient exception in the preference document. It records three
upstream corrections: nonneutral/invalid coefficients, cross-store antidumping
overlap and displayed-cent reconciliation. None establishes a new legal rounding
policy or manifest approval. DM-0014 remains a future authorization gate.

## Exact current anchors

Service paths below are relative to `customs-clear/backend/app/services/`;
anchors refer to `a9d15c74699c8cd7842404580ff6fd7bd957e9eb`.

| Function / starting line | Current boundary |
|---|---|
| `official_payment_admission.py:payment_admission_blocker` (23), `blocked_payment_import` (29) | Shared rejection contract has no positive grant or payload override. |
| `import_duty_ingestion.py:run_import_duty_apply` (578); `vat_ingestion.py:run_vat_apply` (686); `excise_ingestion.py:run_excise_apply` (716) | Valid legacy parsing ends in a blocked response before planning/rate/provenance writes; invalid parsing retains its error classification. |
| `anti_dumping_ingestion.py:run_anti_dumping_apply` (735); `special_safeguard_ingestion.py:run_special_safeguard_apply` (727); `countervailing_ingestion.py:run_countervailing_apply` (726) | Same public rejection boundary; all six named functions and their real blocked-response helpers were replayed. |
| `tamdoc_sync.py:_upsert_vat_preferences` (528), `_upsert_special_duties` (533), `approve_tamdoc_candidate` (693), `approve_tamdoc_candidates_batch` (732) | Writers raise before opening a session; candidate approval returns review-required without changing status; batch reports blocked separately from approved. |
| `payment_source_ingestion.py:_provenance_kind` (83), `_candidate_readiness` (369) | Plausible revision becomes ambiguous; even a supplied official label with parsed/present state returns manual review. |
| `payment_engine.py:_resolve_special_duties` (210), `compute_payments` (580), `compare_payment_scenarios` (1051) | Provisional arithmetic remains visible with review reasons; definitive comparisons remain unavailable. `_sum_displayed_amounts` (57) now uses Decimal to sum rounded display components. |
| `payment_quote_service.py:_resolve_special_duty_line` (167), `build_payment_quote` (384); `payment_profile_builder.py:_map_raw_to_profile` (17), `build_compare_payment_profiles` (88) | Quote finality and dependent VAT guards remain; profile status/reasons and incomplete-comparison flags are retained. |

Current repository tests read, **not locally executed**:
`test_official_payment_admission.py` (six-domain admission and cache boundary),
`test_tamdoc_payment_admission.py` (approval preservation, blocked writers/batch),
`test_payment_admission_redteam.py` (independent storage/HTTP boundaries),
`test_payment_a6_reconciliation.py`, `test_payment_reconciliation_redteam.py`
and the existing payment-special-duty/consumer/history/quote regressions.
The current A6 document identifies exact confirmed and intentional cases.

## Executed local verification and its limits

Initial branch/status checks matched the assigned branch and merge SHA; the
worktree was clean and only this report differed from current upstream.

The old replay with only its source SHA changed failed with `NameError: Decimal`
in the new `_sum_displayed_amounts` helper. This was an isolated-harness missing
dependency, not a product failure. The replay below supplies standard-library
`Decimal` to the namespace; the source functions are unchanged.

**Current complete replay: exit 0.** It checks:
four provisional money/quote/compare/metadata cases; six public apply functions
with both successful-parse and parser-failure stubs; two rejecting Tamdoc writers;
pending-candidate/batch preservation; and the conservative readiness branch.

| Synthetic case | Raw special duty | VAT base | Raw total | Final quote | Partial quote |
|---|---:|---:|---:|---|---:|
| Computable 5% candidate | 5,000 | 115,000 | 41,300 | null | 11,000 |
| Unresolved producer condition | 0 | 110,000 | 35,200 | null | 11,000 |
| Unresolved + computable 3% distinct family | 3,000 | 113,000 | 38,860 | null | 11,000 |
| Explicit zero candidate | 0 | 110,000 | 35,200 | null | 11,000 |

These are synthetic inputs, not a rate claim. The replay compiles real function
ASTs/constants from pinned Git objects. Database/lookup/parser/provenance/DTO
dependencies are synthetic; real marker helpers and blocked-response functions
remain. It does not exercise actual parsers, SQL filtering, Pydantic validation,
HTTP, cache persistence, complete A6 regression coverage or all consumers.
No product module, database, provider or external source was opened.
Git object reads support the sparse checkout.

Dependency probe: `pytest=False, sqlalchemy=False, fastapi=False`.
No local repository pytest, HTTP smoke or CI was run.

**A0 remote observation, not this author's local verification:** A0 queried
GitHub and reported success at exact `a9d15c74699c8cd7842404580ff6fd7bd957e9eb`
for CI [34718655503](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34718655503),
[34718653080](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34718653080),
[34718400910](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34718400910)
and Admission agent QA [34718400932](https://github.com/ivan88810900-star/tnved_starter_kit_v2/actions/runs/34718400932).
These upstream observations do **not** satisfy the new report candidate's own
CI/A5 gate. This report's independent QA and CI remain pending.

## Next bounded task

After independent A5 review and CI of this report candidate, follow the latest
focus: prepare a **non-activating formal review candidate for Decision 12 → 4 → 121**.
Reuse retained originals and the existing Decision 4/12 review evidence; bind
literal product, producer, code and date clauses to exact source identities.
Make incomplete amendment coverage, nomenclature/interval dependencies and
unresolved interpretations explicit. A3 records facts, A2 owns formal applicability,
and A5 independently checks the packet. No source reading or AI review grants
human legal approval, writes rates or activates enforcement.

Do not reacquire completed evidence or restart the admission fixes. Broader ETT
notes and VAT/excise/remedy/preference/origin temporal coverage follow the current
sequence; preserve the existing four-code, one-day 111C candidate.

## Reproduce

Run this Python from the repository with `python3`. The source SHA is pinned,
independent of report-branch HEAD. No private fixture or hidden state is needed.

```python
import ast, builtins, importlib.util, re, subprocess, __future__
from collections import Counter
from datetime import date
from decimal import Decimal
from math import isfinite
from types import SimpleNamespace as NS
from urllib.parse import urlparse

SHA = "a9d15c74699c8cd7842404580ff6fd7bd957e9eb"
ROOT = "customs-clear/backend/app/services/"
def blocked_import(name, *args, **kwargs):
    if name == "rate_display":
        return NS(resolve_excise_for_hs=lambda hs: ("none", 0, ""))
    if name == "official_payment_admission": return NS(**admission)
    raise AssertionError("Unexpected application import: " + name)
def load(name, only=None):
    source = subprocess.check_output(["git", "show", SHA + ":" + ROOT + name + ".py"], text=True)
    tree = ast.parse(source)
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and (only is None or n.name in only))
             or (only is None and isinstance(n, (ast.Assign, ast.AnnAssign)))]
    scope = dict(re=re, Counter=Counter, date=date, isfinite=isfinite, urlparse=urlparse, Decimal=Decimal,
                 __name__=name, __builtins__=dict(vars(builtins), __import__=blocked_import))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), name,
                 "exec", flags=__future__.annotations.compiler_flag), scope)
    return scope

markers = load("payment_revision_utils")
engine = load("payment_engine")
quote = load("payment_quote_service")
metadata = load("payment_result_status")
engine.update({k: v for k, v in markers.items() if not k.startswith("__")})
class Field:
    def in_(self, values): return True
class Session:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def query(self, *args): return self
    def filter(self, *args): return self
    def all(self): return rows
rate = NS(duty_rate="10%", vat_rule="none", vat_rule_basis="", vat_import_rate=22,
          excise_type="none", excise_value=0, excise_basis="", antidumping_type="none",
          antidumping_value=0, antidumping_condition="", antidumping_countries="",
          source_revision="synthetic-test-only")
def no_result(*args, **kwargs): return None
engine.update(
    SessionLocal=Session, SpecialDuty=NS(hs_code_prefix=Field()),
    find_rate_for_hs=lambda hs: (rate, 10),
    _parse_duty_rate=lambda value: {"ad_valorem": float(value.rstrip("%"))},
    _find_duty_rule_for_hs=lambda hs: (None, 0),
    _find_vat_preference=lambda hs: (None, 0),
    get_country_risk_by_iso=no_result, find_geo_embargo_match=no_result,
    find_geo_duty_override_row=no_result, get_tariff_preference=no_result,
    get_recycling_fee=lambda *a, **kw: [], calculate_customs_fee=lambda value: 1000,
    get_integrated_data_stats=lambda: {"hs_rates_count": 1},
    get_tnved_context_for_hs=lambda hs: {})
real_resolve = engine["_resolve_special_duties"]
engine["_resolve_special_duties"] = lambda **kw: real_resolve(**kw, as_of="2026-09-08")
quote.update(compute_payments=engine["compute_payments"],
             get_rates_map=lambda: {"RUB": 1}, canonical_anchor_for_hs=no_result,
             _special_duties_configured_for_hs=lambda hs: True)
for dto in ("PaymentQuoteLineItem", "PaymentQuoteWarning", "PaymentQuoteAssumption", "PaymentQuoteResponse"):
    quote[dto] = lambda **kw: NS(**kw)
def remedy(**overrides):
    fields = dict(id=1, hs_code_prefix="850940", origin_country="CN",
                  rate_percent=5, rate_specific=0, currency_code="", regulatory_act="Synthetic only",
                  measure_type="anti_dumping", manufacturer_exporter="", product_description="",
                  effective_from="2026-01-01", effective_to="2026-12-31", needs_verification=False)
    for prefix, code, revision in [
        ("source", "EEC_ANTI_DUMPING", "anti-dumping:2026-01-01"),
        ("safeguard_source", "EEC_SPECIAL_SAFEGUARD", "special-safeguard:2026-01-01"),
        ("countervailing_source", "EEC_COUNTERVAILING", "countervailing:2026-01-01")]:
        fields.update({prefix + "_code": code, prefix + "_revision": revision,
                       prefix + "_url": "https://eec.eaeunion.org/synthetic-test-only"})
    fields.update(overrides)
    return NS(**fields)
payload = dict(hs_code="8509400000", country="CN", customs_value=100000, insurance=0)
for label, rows, amount, vat_base, raw_total in [
    ("computable", [remedy()], 5000, 115000, 41300),
    ("unresolved", [remedy(manufacturer_exporter="Synthetic producer")], 0, 110000, 35200),
    ("mixed", [remedy(manufacturer_exporter="Synthetic producer"),
               remedy(id=2, rate_percent=3, measure_type="countervailing")], 3000, 113000, 38860),
    ("true_zero", [remedy(rate_percent=0)], 0, 110000, 35200)]:
    raw = engine["compute_payments"](payload)
    assert raw["special_duties_amount"] == amount
    assert raw["breakdown"]["vat_base"] == vat_base
    assert raw["breakdown"]["total_payable"] == raw_total
    assert raw["status"] == "REVIEW_REQUIRED" and raw["amounts_provisional"] is True
    assert all(not row["applied"] and not row["legal_review_verified"] for row in raw["special_duties"])
    result = quote["build_payment_quote"](payload)
    lines = {line.code: line for line in result.line_items}
    assert lines["special_duty"].status == lines["vat"].status == "manual_review_required"
    assert lines["special_duty"].amount_rub is lines["vat"].amount_rub is None
    assert lines["vat"].basis_amount_rub is result.total_payable_rub is None
    assert result.total_partial_rub == 11000 and result.status == "REVIEW_REQUIRED"
    assert any(w.code == "payment_review_required" for w in result.warnings)
    assert any(a.key == "provisional_total_payable_rub" for a in result.assumptions)
    saved = metadata["aggregate_payment_metadata"]([raw, {}])
    assert saved["payment_status"] == "REVIEW_REQUIRED" and saved["amounts_provisional"] is True
    comparison = engine["compare_payment_scenarios"](
        {"shared": payload, "scenarios": [{"hs_code": payload["hs_code"]}, {"hs_code": payload["hs_code"]}]})
    assert comparison["status"] == "REVIEW_REQUIRED"
    assert all(s["delta_total_vs_first_rub"] is None for s in comparison["scenarios"])
    print(f"{label}: special={amount}; vat_base={vat_base}; raw_total={raw_total}; quote_final=None; quote_partial=11000; REVIEW_REQUIRED; comparison_delta=None")
assert metadata["payment_result_metadata"]({})["amounts_provisional"] is None
print("PASS: 4 AST-isolated cases; quote/compare/metadata guards; no database or application imports")
print("Dependency availability:", {x: importlib.util.find_spec(x) is not None for x in ("pytest", "sqlalchemy", "fastapi")})

# Current admission branches; parser/storage infrastructure remains synthetic.
admission = load("official_payment_admission")
class DTO(NS):
    def model_dump(self, **kwargs): return vars(self)
for domain, stem in [
    ("import_duty", "ImportDuty"), ("vat", "Vat"), ("excise", "Excise"),
    ("anti_dumping", "AntiDumping"), ("special_safeguard", "SpecialSafeguard"),
    ("countervailing", "Countervailing")]:
    func = "run_" + domain + "_apply"
    scope = load(domain + "_ingestion", {func, "_blocked_response"})
    scope.update(_utc_now_iso=lambda: "synthetic-only",
                 _build_provenance=lambda **kw: NS(),
                 payment_admission_blocker=admission["payment_admission_blocker"])
    scope["discover_" + domain + "_bundle_path"] = lambda **kw: "synthetic-only"
    scope[stem + "IngestionResponse"] = DTO
    scope[stem + "RowCounts"] = DTO
    for parse_blockers in ([], ["parser_failed: synthetic malformed input"]):
        scope["_validate_bundle_for_ingest"] = lambda path: (
            {"legal_review_verified": True}, {"status": "parsed" if not parse_blockers else "parser_failed"},
            "synthetic-only", [{}], parse_blockers)
        result = scope[func]()
        expected = "parser_failed" if parse_blockers else "manual_review_required"
        assert result["status"] == expected
        assert result["db_mutated"] is result["active_rates_written"] is result["legal_review_verified"] is False
        if not parse_blockers:
            assert result["row_counts"].blocked == 1 and result["blockers"]
    print(domain + ": apply blocked; parser_failed preserved; no write dependency called")

# Select only the named functions: no module setup, provider or database import.
tamdoc = load("tamdoc_sync", {"_upsert_vat_preferences", "_upsert_special_duties",
                             "approve_tamdoc_candidate", "approve_tamdoc_candidates_batch"})
tamdoc.update(LEGAL_REVIEW_BLOCKER=admission["LEGAL_REVIEW_BLOCKER"],
              blocked_payment_import=admission["blocked_payment_import"])
for name, args in [
    ("_upsert_vat_preferences", (["850940"], [10], "synthetic", "")),
    ("_upsert_special_duties", (["850940"], ["CN"], [5], "synthetic"))]:
    try:
        tamdoc[name](*args)
        raise AssertionError("Writer unexpectedly returned")
    except PermissionError as exc:
        assert str(exc) == admission["LEGAL_REVIEW_BLOCKER"]
class CandidateField:
    def __eq__(self, value): return True
    def asc(self): return self
class CandidateSession(Session):
    def first(self): return rows[0]
    def order_by(self, *args): return self
    def limit(self, *args): return self
rows = [NS(id=1, doc_type="vat", vat_rates="10", percent_rates="", status="pending")]
tamdoc.update(SessionLocal=CandidateSession,
              TamdocSyncCandidate=NS(id=CandidateField(), status=CandidateField(), updated_at=CandidateField()))
result = tamdoc["approve_tamdoc_candidate"](1)
assert result["status"] == "manual_review_required" and result["db_mutated"] is False
assert rows[0].status == result["candidate_status"] == "pending"
batch = tamdoc["approve_tamdoc_candidates_batch"]()
assert batch["processed"] == batch["blocked"] == 1
assert batch["approved"] == batch["rejected"] == batch["errors"] == 0
assert batch["status"] == "manual_review_required" and batch["db_mutated"] is False
print("tamdoc: writers raise; candidate remains pending; batch processed=blocked=1, approved=0")
readiness = load("payment_source_ingestion", {"_candidate_readiness"})
readiness["_lookup_source_status"] = lambda code: NS(is_stale=False)
status, blockers, manual = readiness["_candidate_readiness"](
    NS(manual_review_default=False, loader_status="ready", source_status_code="synthetic"),
    "official", {"status": "parsed"}, domain_normalization_status="present")
assert status == "manual_review_required" and manual is True
assert admission["LEGAL_REVIEW_BLOCKER"] in blockers
print("readiness: parsed + official label + present normalization remains manual_review_required")
print("PASS: current admission branch replay; no database, provider or product module opened")
```
