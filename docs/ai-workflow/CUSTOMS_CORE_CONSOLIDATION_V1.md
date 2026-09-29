# Customs core consolidation v1

This branch consolidates the still-relevant customs payment and official-source
diagnostic work on top of `integration/customs-core-v1` at
`08e030a6053ac9638957119373797e0fbf2b10c2`. It deliberately does not merge the
old stacked branches: each retained change was replayed or reimplemented on the
current integration base.

## Dependency and supersession matrix

| PR | Exact reviewed head | Base family | Decision | Dependency / conflict note |
| --- | --- | --- | --- | --- |
| #187 | `5d3b0c1dc7dd8e396c4f812db2bf6f1fa6d293f9` | historical product stack | Do not merge | Large stale stack. It remains evidence and a source for narrowly reviewed behavior only. |
| #202 | `b326d11ca4931c9c2e67bbde738fdbffca8d312a` | #187 | Superseded for admission | Read-only CBR observation explicitly granted no payment admission. The strict same-sync binding from #232 is the selected runtime contract. |
| #203 | `dbb27aa857614b7b83111cddc0c5a1ed32f44580` | #187 | Deferred | Legacy invoice VAT-candidate boundary is not mechanically portable without its historical invoice stack. It must be re-evaluated against a current invoice candidate before inclusion. |
| #204 | `ee81a66eafaba008c2205cac65e5256f939822e2` | #187 | Reimplemented | The gap was reproduced on the current integration base. A narrow current-base contract now treats mutable legacy metadata as observation only, withholds dependent VAT/final totals, preserves named provisional arithmetic, and fails closed when the rate row is missing. |
| #205 | `d1324027cec636d05f2eb6b474a4bbb66758fcef` | #187 | Evidence only | Documentation records unresolved AD30 freshness and has no runtime behavior to integrate. |
| #212 | `fc19df03904430649e356978cf2086a616e6d244` | #187 | Deferred | Monitor-only source expansion is independent of payment admission and remains based on the stale stack. Compare with the current registry before any replay. |
| #216 | `eb702ef05735cec12afd03278edbf23c93cbe51b` | #187 | Reimplemented | The current engine now rejects automatic fixed excise without a typed unit/denominator while preserving an explicit manual amount. |
| #220 | `f6b7aab786c8dc698a216b865a373b73480bbf4a` | #216/#187 | Reimplemented | Finite, non-negative, non-boolean manual operands and finite dependent arithmetic were ported to current-main engine shape. |
| #222 | `1599999f00393fec9b4ed1224daef8ab860c6fa8` | main | Selected | Strict ISO date parsing and future-start exclusion apply before special-duty calculation. Its prior review does not transfer to the combined head. |
| #223 | `c62257d46f225d98942cba4563a59fc8f0a0d7a8` | main | Selected | A successful landing-page fetch remains partial evidence and cannot establish current legal edition. |
| #226 | `75abed16a684db4b78efe94083fe2962ec7d4eee` | main | Selected | Future or malformed bundle revision dates fail freshness checks. |
| #228 | `7b49d70650f26015f1b4edc62d6a5340e53d4bae` | main | Superseded | #232 strengthens FX provenance to one exact CBR synchronization marker and covers downstream consumers. |
| #229 | `38cae9f3c77498f6f597b52c1aaabd171ea4bf37` | main | Selected | Unitless fixed antidumping and unknown measure types withhold dependent VAT and final payable. |
| #231 | `ea02383e24238c365e452fcea1187ad74daaed6c` | main | Selected | Official-edition diagnostics reject malformed, future, seed/demo, or timezone-ambiguous provenance. |
| #232 | `fe4216997fd7adc5da487c5d917dbe95928ea2ef` | main | Selected | Foreign-currency calculations require a positive finite rate bound to the exact successful CBR sync marker; no hard-coded payment fallback remains. |
| #235 | `fd7820da28e4aa5bcf934680e5d6c32f5bf571a5` | main | Selected | Official-source update entrypoints are validated and missing/invalid/not-configured gaps require manual review. |
| #238 | `5b98d7c67a6b8b5d0a6dbd4a6313e1d656bf30b2` | main | Selected | Automatic duty grammar, operands, components, and totals fail closed on malformed, negative, or non-finite input. |
| #240 | `ed341749b8a1dc39300fd2e81245949fe94fe26a` | main | Selected | Update-health diagnostics require valid chronology, runtime types, scheduled-run evidence, and the explicit empty-string no-error sentinel. |

## Combined behavior now present

- Automatic and manual payment operands cannot inject negative, boolean,
  non-finite, overflowed, or partially parsed values into VAT or final totals.
- A legacy `HsRate` or `HsDutyRule` cannot authorize final payment from mutable
  URL/revision/date strings. Existing and missing rows both require reviewed,
  typed source binding; raw arithmetic remains explicitly provisional.
- Fixed excise and fixed antidumping amounts cannot reuse generic invoice
  quantity when their stored unit and denominator are unknown.
- Foreign-currency calculations require a rate from the same verified CBRF
  synchronization event used by the source status.
- Trade-remedy start/end dates are parsed conservatively before application.
- Landing-page observations, local bundle dates, official-edition provenance,
  configured sync entrypoints, and scheduler/run evidence are separate,
  fail-closed health signals.

## Evidence and remaining gates

Focused payment/source-admission author selection:

- `95 passed, 343 subtests passed`.

Expanded payment regression selection:

- `190 passed, 343 subtests passed`.

Focused source author selection, excluding three pre-existing workflow-file
assertions for a workflow absent from the exact integration base:

- `63 passed, 3 deselected, 57 subtests passed`.

The combined payment/source selection reports `167 passed, 3 deselected, 400
subtests passed`. The three deselected checks assert a scheduled refresh workflow
file that is absent from the exact integration base; the runtime/source tests in
the same files pass.

This is an in-progress candidate, not integration-ready. Before integration it
still requires:

1. fresh independent A5 on the final combined head;
2. live A6 for the high-risk payment/source changes after the post-verify
   admission bridge is available;
3. A0 validation of every A5/A6 finding and exact-head CI.

No previous PR review or CI result is carried forward to the combined head.
