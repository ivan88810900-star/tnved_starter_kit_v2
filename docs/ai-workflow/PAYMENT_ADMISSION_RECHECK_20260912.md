# Payment admission recheck — 12 September 2026

Task: TARIFF-ADMISSION-RECHECK-001. Author: A1, native session `/root/smoke_rates`.
Reviewed PR #187 source: `22a7df5590a7442d943d89af285feb1228e80938`.
Report branch: `agent/rates-tariff-admission-recheck-001-9231ffbdb5`.
Worktree: `/workspace/scratch/cd6734a40504/tariff-agent-worktrees/tariff-admission-recheck-001-9231ffbdb5`.

This is a bounded technical evidence report. Product code, databases and flags were
not changed. No production, HTTP, external source or provider request was made.
Git object retrieval was used to read the pinned source in this sparse checkout.
No legal applicability, rate approval, CI, independent QA or A6 pass is asserted.

## Conclusions

| Item | Classification | Evidence and consequence |
|---|---|---|
| A special-duty candidate has `applied=False` and `legal_review_verified=False`, but contributes to raw total and VAT base | **CONFIRMED / INTENTIONAL** | The resolver's computable branch explicitly produces `status=provisional`, a retained amount and `legal_review_unverified`. The current corrective document permits this preliminary arithmetic. The two booleans do not assert that arithmetic must be absent. |
| That preliminary amount becomes a definitive quote or savings comparison | **UNCONFIRMED; existing safeguards present** | Four isolated executions preserve `REVIEW_REQUIRED`, null special-duty/VAT quote amounts, null VAT quote basis and null final quote total. Comparison deltas are null. Historical correction is present at the reviewed SHA; this report introduces no fix. |
| Pending counters disagree | **UNCONFIRMED** | The quote service/schema has no exported `pending_count` or shared pending-summary counter. Its `preference_pending` is a boolean. Adjacent payment coverage/audit summaries inspected below expose no pending counter to compare. No concrete conflicting outputs or shared counting contract were identified; do not open a defect from this hypothesis. |
| Payment admission recovery is already complete | **Not supported; confirmed open implementation paths** | The inspected import-duty apply and Tamdoc approval paths can reach rate writers without manifest-bound legal review. This agrees with the recovery task's unfinished scope; it is not a newly discovered legal interpretation. |

## Current authority and exact code anchors

Read `AGENTS.md`, `.ai/DECISIONS.md`, `CURRENT_PROJECT_FOCUS.md` and
`TASK-RATE-ADMISSION-RECOVERY.md` on the pinned product branch. The current owner
mandate authorizes this scoped technical commit despite older manual commit clauses.

- [Payment preference contract](PAYMENT_PREFERENCE_REVIEW_GUARD.md), Decision:
  retain explicitly preliminary arithmetic and suppress final payable quotes.
- [Rate-source corrections](RATE_SOURCE_FAIL_CLOSED_CORRECTIONS.md), “Unresolved
  trade-remedy applicability”: source-marked computable remedies supply provisional
  arithmetic only; unresolved candidates have no applied amount. Source markers
  are not manifest-bound legal approval.
- [Current focus](CURRENT_PROJECT_FOCUS.md), “Next recommended implementation tasks”,
  and [DM-0014](../../.ai/decisions/DM-0014-ett-review-authority.md): Option A remains
  accepted; fail-closed technical work continues. The human legal authorization
  policy remains a future gate.
- [Admission recovery task](TASK-RATE-ADMISSION-RECOVERY.md) explicitly states that
  later uncommitted admission changes were lost and are not proof of fixed paths.

All following service paths are under `customs-clear/backend/app/services/`;
line anchors refer to the reviewed source SHA.

| Function / branch | Observed behavior |
|---|---|
| `payment_engine.py:_resolve_special_duties` (194; branches 328–353) | Temporal/condition/provenance/unit/overlap uncertainty gives `needs_clarification` and no amount. The computable branch adds preliminary money while retaining false approval flags. |
| `payment_engine.py:compute_payments` (564; 769–855, 865–868, 933–937) | Both remedy uncertainty states become review reasons. Preliminary special duty enters VAT base and raw `total_payable`; the result remains provisional. |
| `payment_quote_service.py:_resolve_special_duty_line` (167); `build_payment_quote` (384; 474–518, 547–560) | Both remedy states block special-duty money and dependent VAT money/basis. Any provisional result or uncertain blocking line suppresses `total_payable_rub`. |
| `payment_quote_service.py:_build_assumptions` (303) | Retained raw totals are explicitly preliminary assumptions. Source lists and a partial subtotal are not approval evidence. |
| `payment_engine.py:compare_payment_scenarios` (1005; 1088–1103); `payment_profile_builder.py:build_compare_payment_profiles` (88; 129–144) | Pending scenarios cannot establish savings; profile comparisons also expose `comparison_complete=False`. |
| `payment_profile_builder.py:_map_raw_to_profile` (17); `payment_result_status.py:payment_result_metadata` (11), `aggregate_payment_metadata` (41) | Profile/history metadata preserves provisional status/reasons. Unknown legacy finality is not promoted to verified. Profile `total_payable` is explicitly provisional in `app/schemas/payment_profile.py:12`. |
| `payment_quote_service.py`, `app/schemas/payment_quote.py`; `payment_data_coverage.py:run_payment_data_coverage_report` (1008); `official_payment_coverage_audit.py:_build_domain_summary` (610) | Bounded pending-counter inspection: no common exported pending count found. Coverage categories must not be silently treated as legal-review queue counts. |

Admission paths below were **statically inspected, not executed**:

- `import_duty_ingestion.py:run_import_duty_apply` (565) calls
  `_validate_bundle_for_ingest` (391), then `_apply_duty_rows` (604 call site)
  and provenance writers. The inspected validation covers legacy revisions,
  URLs, parsing and row scope, not manifest-bound review.
- `tamdoc_sync.py:approve_tamdoc_candidate` (828) calls
  `_upsert_vat_preferences` / `_upsert_special_duties` for parsed candidate
  rates and then marks the candidate approved. Those helpers commit writes
  (561–636). `approve_tamdoc_candidates_batch` (903) delegates to it.
- `payment_source_ingestion.py:_candidate_readiness` (359–420) can return
  `ready_to_ingest` from “official” legacy provenance, parse/SourceStatus and
  normalization state. This is another recovery-contract gap, not proof of
  legal review. This report is not an exhaustive audit of all six ingestors.

## Verification

Executed on the report worktree:

- `git branch --show-current`, `git rev-parse HEAD`, initial
  `git status --short --untracked-files=all`: expected branch/source SHA,
  clean worktree, exit 0.
- The complete Python replay below: **4 cases passed, exit 0**. It compiles
  unchanged function ASTs and constants from the pinned Git objects. Real
  revision/URL marker helpers are retained. Synthetic lookup/session objects,
  fee/FX/description dependencies and DTO constructors replace application
  infrastructure. No application module or database is opened.
- An initial replay-harness setup failed before completing a scenario
  (`KeyError: '__name__' not in globals`). Setting the isolated namespace/import
  hook before compiling functions corrected the harness; no product code changed.
- Dependency probe: `pytest=False, sqlalchemy=False, fastapi=False`.
  Repository pytest, real SQLAlchemy/Pydantic integration, HTTP smoke and CI
  were **not run**. The replay is narrower than those tests and does not
  verify SQL filtering, DTO validation, legal data or every downstream renderer.

The synthetic baseline is customs value 100,000, ordinary duty 10,000,
fee 1,000 and VAT arithmetic at 22%; these values are test inputs, not a rate claim.

| Replay case | Raw special duty | Raw VAT base | Raw total | Final quote | Quote partial |
|---|---:|---:|---:|---|---:|
| Computable 5% candidate | 5,000 | 115,000 | 41,300 | null | 11,000 |
| Unresolved producer condition | 0 | 110,000 | 35,200 | null | 11,000 |
| Unresolved candidate + computable 3% other family | 3,000 | 113,000 | 38,860 | null | 11,000 |
| Explicit zero candidate | 0 | 110,000 | 35,200 | null | 11,000 |

Every case also asserts review flags, warnings, preliminary assumptions, null
dependent VAT/basis, null comparison deltas and conservative aggregate metadata.

Existing tests **read, not executed**:

- `tests/test_payment_special_duty_applicability.py`:
  `test_unproved_rows_keep_evidence_and_block_money_and_dependent_vat`,
  `test_known_distinct_family_partial_is_retained_but_never_final`,
  `test_explicit_unconditional_zero_is_provisional_arithmetic_and_different_from_unknown`.
- `tests/test_payment_consumer_review.py`:
  `test_extended_comparison_does_not_rank_pending_estimates`,
  `test_profile_comparison_keeps_provisional_contract_and_nulls_deltas`.
- `tests/test_payment_history_uncertainty.py`:
  `test_one_pending_item_keeps_entire_history_summary_under_review`,
  `test_batch_unknown_member_cannot_become_confirmed`.
- `tests/test_payment_quote.py` and `tests/test_payment_quote_explanation.py`:
  incomplete quotes and explanatory bases; no shared pending-counter contract.
- `tests/test_import_duty_ingestion.py` still has positive legacy apply tests
  such as `test_apply_imports_official_rows_with_provenance` and
  `test_versioned_ett_revision_accepted`. Their existence does not prove
  current legal authorization; the admission recovery must distinguish public
  rejection from explicitly isolated technical fixtures.

## Minimal next tasks

1. A5 independently reruns this pinned replay and inspects the report diff.
   Run the existing disposable backend CI profile separately; bind its actual
   completion to the relevant source/report commits.
2. Continue `TASK-RATE-ADMISSION-RECOVERY` in separately owned code tasks:
   first the public dedicated apply boundary, then Tamdoc payment approval,
   preserving parse diagnostics/staging and proving no writes/provenance/cache
   mutation on rejection. Align marker-based readiness reports with that boundary.
   Keep generic writers and the other listed recovery paths in the existing task;
   this report does not certify them.
3. Preserve the intentional preliminary arithmetic and existing finality guards.
   Do not change amount semantics or open a counter defect without a concrete
   reproducer. No human legal authority or production action is requested here.

## Reproduce the executed check

From this repository, run the following Python with `python3` (stdlib only).
It reads the exact source SHA irrespective of the report branch HEAD.
This is the full executed replay, without private fixtures or hidden state.

```python
import ast, builtins, importlib.util, re, subprocess, __future__
from collections import Counter
from datetime import date
from math import isfinite
from types import SimpleNamespace as NS
from urllib.parse import urlparse

SHA = "22a7df5590a7442d943d89af285feb1228e80938"
ROOT = "customs-clear/backend/app/services/"
def blocked_import(name, *args, **kwargs):
    if name == "rate_display":
        return NS(resolve_excise_for_hs=lambda hs: ("none", 0, ""))
    raise AssertionError("Unexpected application import: " + name)
def load(name):
    source = subprocess.check_output(["git", "show", SHA + ":" + ROOT + name + ".py"], text=True)
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign, ast.AnnAssign))]
    scope = dict(re=re, Counter=Counter, date=date, isfinite=isfinite, urlparse=urlparse,
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
```
