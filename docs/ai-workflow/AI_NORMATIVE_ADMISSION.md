# AI normative extraction admission

Status: reconstructed for independent review and fresh CI. This does not complete
official-source coverage or authorize rates, obligations, prohibitions or legal
applicability. A0 owns integration into PR #187.

## Recovery and reproduced defects

Recovery uses actual GitHub source at
`22a7df5590a7442d943d89af285feb1228e80938`, with the frozen shared admission
dependency from `22473e172c042f08cd5b72aece5dd221c54bdc9d`.
The disconnected executor's local commits `6dd1971`, `631e6dd` and `685d522`
were never published. Their captured edits and test definitions were reconstructed
using exact, single-occurrence anchors in the current GitHub files. The new tree
requires its own review/test results; the earlier 48 passing local tests are
historical evidence only.

Independent A5 reproduced a model-generated 7.5% duty and 10% VAT written directly
to `hs_rates`, with only `bulk-normative-ai` as the source label. The authenticated
admin background job and historical crawler both committed that writer's output.
The same writer expanded inferred NTM prefixes to as many as 400 commodity codes
and populated `document_required` with default `quality=normal`, without product
conditions or reviewed applicability. Legacy lookup includes such normal rows.

The writer synthesized zero duty when only VAT/date or excise was inferred.
Substring classification could interpret `special_duty` as `duty`. Repairing that
heuristic would not establish legal authority; its active write branches have
been removed. Existing application data is not modified by this correction.

## Admission and extraction contract

`apply_structured_rows` now raises `AINormativeAdmissionError` before session
access, row iteration, code expansion or mutation, for every category, malformed
or empty list, mixed batch and forged approval/confidence field. No success,
feature flag or model-provided grant can bypass the boundary. The shared payment
blocker is reused within a distinct AI normative blocker; NTM is not recategorized
as a payment fact.

Bulk and historical extraction instead use `stage_structured_rows_for_review`.
The existing local content-addressed store retains separate objects for the
original uploaded/fetched body, extracted text, raw model output, system prompt,
and a JSON record binding their SHA-256 values and the unreviewed parsed claims.
The source tag remains untrusted metadata. Model-input truncation is disclosed.

Results remain `manual_review_required`, with zero `measures_applied` and false
source verification, legal review, retention, active-rate and active-measure write
flags. Local storage is not durable retention/legal hold, and fetched bytes alone
are not authenticated official provenance. Source facts and model interpretations
remain separate objects. A storage/serialization failure produces an error,
without a successful evidence checkpoint.

The default store is
`customs-clear/backend/data/runtime/ai_normative_review`.
Runtime database writes are limited to existing job/checkpoint metadata. The
checkpoint status is `pending_review`, fitting the existing `String(16)` columns;
public results and bulk job state use `manual_review_required`. Repeated
checkpoints avoid a repeated model call and still require review. Historical
`ok` counts remain historical records, not fresh legal approval. Checkpoint
deduplication itself is not a storage-integrity or legal audit.

No active normative table is updated and no preview cache revision is bumped.
Empty or unsupported model output never proves the absence of measures.
The grounded assistant remains a consumer of canonical/payment/NTM facts.

## Legacy invoice code scripts

`sync_invoice_codes.py` and `sync_missing_codes.py` previously wrote Gemini rate
estimates; the first also created synthetic commodity records and inferred NTM
documents, without isolated-fixture or legal-review guards. Non-dry invocation
now emits a structured `manual_review_required` report and exits 2 before
invoice/DB/provider access. Direct apply, placeholder and provider helpers reject
as well; the old active writers and rate-guessing prompts have been removed.

`--dry-run` preserves invoice code parsing. Without `--database`, no database is
checked and missing-rate information stays unknown. An explicit snapshot enables
only technical missing-code inspection, with the exact used-byte SHA-256 and size
in the report, never legal approval.

A5 independently found that SQLite `mode=ro` may create WAL/SHM files even for a
closed WAL-format snapshot. The recovered correction therefore never opens the
user's source path through SQLite. It refuses WAL-format headers and every
existing journal/WAL/SHM sidecar, including dangling symlinks. It reads at most
64 MiB through a no-follow, nonblocking descriptor, verifies a regular file and
rechecks its identity/size before and after the read. Only those retained bytes
are deserialized into an isolated in-memory SQLite database with query-only mode.

Oversized, changing, symlink/FIFO, WAL/live-journal or unsupported-platform inputs
return explicit errors; data is never truncated and live WAL is never ignored.
A larger application database requires a separately prepared consistent,
bounded `hs_rates` snapshot. This optional diagnostic does not create that
snapshot, purchase storage or mutate the source.

## Extraction CLI status and historical evidence

`bulk_ai_importer.py` and `historical_crawler.py` report unreviewed extraction
rather than an UPSERT or generic completion promise. Review exits 2 and extraction
errors exit 1. Existing `--reset-checkpoints` arguments now return a non-mutating
block before DB access, preserving historical review/extraction evidence.
Bulk `--list-only` creates neither an input directory nor a job.

## Verification gate

The dedicated A5-owned `admission-agent-qa.yml` executes these explicit files on
fresh disposable databases, with schedulers, enforcement and provider keys off:

- `tests/test_ai_normative_admission.py`: direct/mixed writer rejection, existing
  active-table immutability, exact evidence replay, repeat/legacy checkpoints,
  evidence failure, changed uploads, job errors and authenticated admin routes.
- `tests/test_ai_normative_cli_admission.py`: real blocked CLI subprocesses,
  direct-helper bypasses, no implicit DB, exact snapshot byte/hash preservation,
  CLI review/error statuses, preserved checkpoints, closed/live WAL, journal and
  dangling-link rejection, FIFO replacement without blocking, size limits and
  source mutations.

All provider/network responses in tests are mocked. Fresh CI and independent A5
review are required before integration; reconstructed definitions are not a test
result. No positive legal approval, flag activation, application DB migration,
merge, production deployment or source acceptance is included.
