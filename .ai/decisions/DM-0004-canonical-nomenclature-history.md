# DM-0004: Canonical nomenclature history and code transitions

> **Status:** Proposed — awaiting Ivan **Date:** 2026-08-05 **Owner:** Ivan
> **Context:** [ADR-0001](ADR-0001-canonical-tnved-model.md),
> [ADR-0003](ADR-0003-canonical-anchor-identity.md),
> [TASK-CANONICAL-005](../tasks/TASK-CANONICAL-005.md),
> [TASK-CANONICAL-006](../tasks/TASK-CANONICAL-006.md),
> [CURRENT_PROJECT_FOCUS.md](../../docs/ai-workflow/CURRENT_PROJECT_FOCUS.md)

## Context

The current Canonical TN VED contour is intentionally a model of the **current**
nomenclature:

- `stable-id-v1` identifies a node by its versioned Canonical path and stays
  stable across content-only updates;
- `canonical-snapshot-v2` identifies the exact current output;
- current anchors expose `(stable_id, snapshot_id, code, node_type)` additively
  to search, code-card, Guided TN VED, payments, risk and the grounded
  assistant;
- `tnved_commodities.code` is unique and has no nomenclature-validity period;
- the current TN VED sync replaces sections, chapters and commodities instead of
  retaining prior catalog revisions;
- there is no repository model or verified source for code succession between
  nomenclature revisions.

ADR-0001 listed `aliases`, `previous_codes`, `valid_from`, `valid_to` and
`superseded_by` as future Canonical attributes. ADR-0003 deliberately did not
define their persistence or product behavior: a code/path change creates a new
identity, and future continuity must be explicit rather than silently reusing an
old identity.

The phrase **aliases/history** currently conflates three different domains which
must remain separate:

1. **Lexical search synonyms** — colloquial or domain terms such as «смартфон»
   and official wording. They improve retrieval but do not state legal
   equivalence between TN VED codes. The current deterministic search already
   has a separate curated synonym contour.
2. **Legal nomenclature transitions** — relationships between real coded
   positions in different official revisions: one-to-one renumbering,
   one-to-many split, many-to-one merge, withdrawal without a successor, or a
   scope change while the numeric code remains the same.
3. **Technical stable-ID migrations** — mapping old internal identifiers to new
   ones if `stable-id-v1` or the Canonical path contract is changed in a future
   ADR. This is an infrastructure migration, not evidence that one customs code
   legally replaces another.

Implementing one `aliases[]` list or one `superseded_by` field would erase these
distinctions. In particular, a singular successor cannot represent splits and
merges, and an inferred text match cannot be presented as an official legal
transition.

## Product need and boundary

The concrete product need is to handle an old code found in a declaration,
invoice, classification decision or customer archive without returning a false
current match. The product should be able to say that the code is current,
historical, future or unknown; show zero, one or several supported successor
candidates; cite the source; and require reclassification when a split or scope
change makes automatic resolution unsafe.

This decision does **not** make historical duty, VAT, NTM, sanctions or permit
results correct for a past date. Those overlays have independent validity and
provenance and would require separate decisions and datasets.

## Decision required

Choose how Tariff will represent and resolve TN VED changes across catalog
revisions without changing `stable-id-v1`, silently redirecting codes, or
treating inferred similarity as official evidence.

## Option A — Add simple history fields to current Canonical nodes

### Option A description

Add fields such as `aliases[]`, `previous_codes[]`, `valid_from`, `valid_to` and
a single `superseded_by` directly to `TreeNode`/`CanonicalModel`, populated
manually or from the current catalog.

### Option A pros

- smallest model and API diff;
- easy exact lookup for a curated one-to-one rename;
- resembles the preliminary field list in ADR-0001.

### Option A cons

- cannot correctly represent one-to-many and many-to-one changes;
- mixes lexical synonyms, legal code transitions and technical ID migration;
- the current source contains no retained revision history from which the fields
  can be populated reliably;
- risks silently redirecting a split code to one incorrect current code;
- mutates the current structural source of truth with a temporal overlay;
- a current node cannot by itself represent the same numeric code with different
  scope in different validity periods.

## Option B — Versioned many-to-many nomenclature-history overlay

### Option B description

Keep `CanonicalModel` current-only and add a separate, provenance-first temporal
overlay after source feasibility is proven. The target domain model contains:

- immutable **catalog revisions** with validity period, official source
  identity, source revision/URL and content hash;
- **code versions/occurrences** bound to one catalog revision, carrying the real
  code, title/scope and structural context for that revision;
- directed, many-to-many **transition edges** between code versions, with
  relation kind (`renumbered`, `split`, `merged`, `scope_changed` or an
  explicitly approved equivalent), effective date, regulatory act/evidence and
  authority level;
- a resolver which returns an explicit status and zero-to-many candidates while
  the current Canonical anchor remains a separate object.

Lexical search aliases remain in the search domain. Technical
`previous_stable_ids` are introduced only by a future stable-ID migration ADR
and never substitute for legal transition evidence.

### Option B pros

- models real split/merge cardinality and same-code scope changes;
- preserves the accepted current Canonical identity and snapshot contracts;
- keeps official, curated and inferred evidence isolated;
- supports old-document lookup, future stale-anchor revalidation and auditable
  UI;
- can be added behind a default-OFF boundary without changing current search or
  tree behavior;
- permits incremental ingestion of verified revisions.

### Option B cons

- requires at least two coherent official revisions and trustworthy transition
  evidence;
- needs new storage, importer validation, resolver semantics and UI states after
  this decision is accepted;
- historical catalog data is larger than a simple alias table;
- does not by itself provide historical payments or compliance conclusions.

## Option C — Make CanonicalModel a multi-revision temporal graph

### Option C description

Load current and historical nodes, validity periods and transitions into one
temporal Canonical model, and make every navigation/lookup operation date-aware.

### Option C pros

- one graph could answer current and historical structure queries;
- all consumers would share one temporal abstraction;
- can eventually support full as-of navigation.

### Option C cons

- changes the meaning and size of the current Canonical source of truth;
- complicates every current lookup, cache, validator, snapshot and fallback
  path;
- increases the risk of old nodes leaking into current classification/search;
- still requires the same currently absent official revision and transition
  sources;
- is disproportionate before a bounded old-code resolver is validated;
- would couple legal history rollout to the still default-OFF Canonical serving
  path.

## Codex recommendation

Choose **Option B**, subject to a source-feasibility gate before any schema or
runtime implementation.

The accepted identity contract should remain unchanged:

- a current `CanonicalAnchor` continues to reference one current node and
  snapshot;
- historical code occurrences and transition edges live in a separate overlay;
- no old code is silently replaced by a current code;
- a split, merge or scope change returns an explicit warning and all supported
  candidates rather than one guessed answer;
- for an ordinary current lookup, an exact current code always wins over any
  historical or lexical alias; an explicit historical/`as_of` lookup is instead
  constrained by the requested validity period;
- inferred snapshot/text similarity may create internal review candidates only
  and must never be serialized or labelled as an official transition;
- only source-backed edges may appear as official, and every displayed
  transition must retain its evidence and revision provenance.

A future resolver should distinguish at least `current`, `historical`, `future`,
`unknown` and `needs_reclassification`. It should return the queried code,
requested or effective date, validity information, relation cardinality,
candidate current anchors and evidence. Returning a current candidate must not
imply that historical payments, NTM or regulatory conclusions remain applicable.

## Risks and mitigations

1. **False legal equivalence.** Mitigation: authority levels are explicit;
   inferred candidates never leave the review contour as official.
2. **Incorrect one-code redirect after a split.** Mitigation: no silent redirect
   and a mandatory `needs_reclassification` outcome for ambiguous transitions.
3. **Mixing current and historical search.** Mitigation: current exact lookup
   has priority; history is a separate resolver/optional result block behind
   default OFF.
4. **False promise of historical compliance.** Mitigation: code history
   explicitly excludes historical Duty/NTM/permit calculations.
5. **Loss of provenance during ingestion.** Mitigation: immutable revision
   hashes, idempotent imports, source URL/revision/effective dates and
   reject-on-conflict validation.
6. **Premature stable-ID migration machinery.** Mitigation: technical aliasing
   is not implemented until a formula/path change or a persistent consumer
   requires it.

## What requires strategic review

Ivan should decide:

1. Is the first user scenario old-code lookup only, or is a complete historical
   tree required? The recommendation is the bounded old-code resolver first.
2. Which evidence may be labelled `official`, and must curated mappings require
   manual approval before product use?
3. Should inferred relations remain internal-only? The recommendation is yes.
4. Which date controls resolution: declaration date, document issue date or an
   explicit user-selected `as_of` date?
5. Is preserving every official catalog revision required, or only revisions for
   which authoritative transition data is available?
6. May history be shown in search automatically, or only after an exact current
   lookup misses / the user asks for historical resolution? The recommendation
   is current exact first and explicit historical disclosure.

## Proposed next task if the recommendation is accepted

### Source-feasibility audit — no schema or runtime implementation

**Goal:** prove that Tariff can obtain and validate enough official revision
data to populate Option B before creating migrations or product behavior.

**In scope:**

- inventory the current TN VED ingestion path and identify where prior revisions
  are discarded;
- identify candidate official catalog-revision and code-transition sources and
  record their licenses, availability, date semantics, identifiers and
  provenance fields;
- obtain or define test fixtures for one-to-one renumbering, split, merge,
  same-code scope change, withdrawal without successor and conflicting evidence;
- produce aggregate counts and a proposed source-authority matrix;
- define a deterministic, idempotent dry-run import contract and reject
  conditions;
- state explicitly whether official successor edges can be populated.

**Out of scope:**

- Alembic migrations or database writes;
- runtime resolver/API/frontend changes;
- changing Canonical stable IDs, snapshot inputs or serving flags;
- automatic redirects;
- external LLM classification of transitions;
- historical Duty/NTM/payment behavior.

**Exit gate:** if authoritative transition data is unavailable or cannot
represent split/merge provenance, do not implement product history. Snapshot
diffs may be kept as internal audit candidates only. If feasibility passes,
prepare a separate bounded ADR and implementation task for storage/import,
followed later by resolver and UI tasks.
