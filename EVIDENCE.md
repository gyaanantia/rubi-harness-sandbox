# Evidence: learning from `request_input` answers

**Sections 1–8 are from the scripted fake model** (`--fake`), which is deterministic and
free. **Section 9 is a real model** (`gpt-4.1-mini`, one iteration). Every table says which.

Reproduce:

```sh
uv run python -m eval.replay day2_repeat   --n 5 --fake --output-dir replay-output/after
uv run python -m eval.replay day2_remember --n 5 --fake --output-dir replay-output/after
uv run python -m eval.replay unattended    --n 5 --fake --output-dir replay-output/after
uv run python -m eval.replay sync_failure  --n 5 --fake --output-dir replay-output/after
uv run python -m eval.replay day1_screen   --n 5 --fake --output-dir replay-output/after
```

`replay-output/` is gitignored. The "before" numbers come from the same command run at
commit `d2534d2` (the branch point) into `replay-output/before`. Every iteration of every
scenario below was identical across `--n 5`.

## 1. The headline: `day2_repeat`, fake model

PLAN 7.1's primary metric is asks per question signature per deal across runs.

| Metric | Before | After | Source |
| --- | --- | --- | --- |
| Pending cards created | 10 | **8** | `asks` in `replay-output/{before,after}/day2_repeat-*.json` |
| Source-contact question asked | 3 | **1** | entity-option rows in `pending_inputs` |
| CRM writes | 5 | 5 | `writes` |
| **Write-approval cards** | **5** | **5** | `kind == "approve"` rows in `pending_inputs` |
| Feedback rows stored | 0 | 3 | `feedback` |
| Reused decisions (guard) | 0 | 0 | `reused` — see §4 |
| `did_not_reask` | FAIL | **PASS** | `passed` / `error` |

The approval count is the safety number: it does not move. Every `write_crm_field` and
`set_deal_status` still stops at its own card.

Per-run breakdown after the change (`replay-output/after/day2_repeat-*.json`):

| Run | Agent | Cards |
| --- | --- | --- |
| 1 | `cim_screener` | banker choice, hard-fail choice, 2 write approvals |
| 2 | `teaser_intake` | 1 write approval — **it never asks who the banker is** |
| 3 | `cim_screener` | hard-fail choice, 2 write approvals |

Run 2 is the cross-agent case from the brief: a *different* agent on the same deal acts on
what a person told the screener on day one.

Tests: `tests/test_scenarios.py::test_day2_repeat_stops_reasking_the_answered_question`
asserts 8 cards, exactly one banker ask, 5 writes and that `did_not_reask` passes.

## 2. What reached the model: run 3's system prompt

**Before** — the `# Memory` section is empty (`replay-output/before/day2_repeat-*.json`,
`runs[2]`, first `model` trace event, `input_messages[0]`):

```
# Memory


# Agent: CIM Screener
```

**After** — the same field, same run index (`replay-output/after/day2_repeat-*.json`):

```
# Memory
Decision for this deal on "Which banker should be the deal source?": contact-a-1 (Avery Lark). Chosen by user-a1 on 2026-09-16. Do not ask this again; act on it, using gated tools for any write.
Context for this deal on "Hard fail: kill or override?": user-a1 chose override (Override) on 2026-09-16. Ask again before acting on it.
```

Two things to notice:

- The **`Decision`** line is a settled fact, so the agent acts on it and asks nothing. The
  **`Context`** line is a judgement call recorded as background — run 3 still asks it. That
  difference is the classifier from PLAN §3 doing its job, visible in the prompt.
- No deal id appears. Memory is keyed by deal; the text says "this deal". The existing
  isolation test `tests/test_round_trip.py::test_firm_isolation_and_prompt_inputs` still
  guards this, and `tests/test_learning.py::test_feedback_never_crosses_a_firm` shows a
  firm B run's prompt carries no `Decision` line from firm A.

## 3. A person widening the reach: `day2_remember`

The scenario answers the hard-fail card with `remember=deal` (CLI: `--remember deal`).

| Run | Cards | Source |
| --- | --- | --- |
| 1 | banker choice, hard-fail choice, 2 write approvals | `replay-output/after/day2_remember-*.json` |
| 2 | **only the 2 write approvals** | same |

6 cards and 4 writes on every iteration, exit 0. The second run's `set_deal_status` card
proposes `open`, which is what the remembered `override` means — so the decision is carried
forward *and* still approved by hand.

Test: `tests/test_scenarios.py::test_day2_remember_skips_the_flagged_question_on_the_second_run`.

## 4. Why `reused` is 0, and where the guard is shown instead

`reused` counts `decision` trace events with `status="reused"` — cards the middleware guard
answered from feedback. It is **0 in every fake replay, by design** (PLAN 7.1): the fake
reads the memory line and never asks, so no card ever reaches the guard. The guard is the
defence against a model that ignores memory and asks anyway.

That path is exercised by a `SequenceModel` test, which emits the identical question after
the answer was learned. From
`tests/test_round_trip.py::test_a_learned_answer_skips_its_card_but_never_a_write_approval`:

```json
{
  "kind": "decision",
  "tool": "request_input",
  "args": { "selected": "contact-a-1" },
  "status": "reused",
  "ts": "2026-09-16T03:12:13.869190+00:00",
  "feedback_id": "415c2c8c-9bc1-411d-8e65-d64167c931a1"
}
```

matching feedback row
`request_input|entity:contact-a-1,contact-a-2,contact-a-3` · reach `deal` · status `active`.

In that same batch the model also emitted an approve-kind `request_input` and a
`write_crm_field`. Both still created their cards and the run paused; `gateway.writes` was
empty. The guard removed one choose card and nothing else.

Related tests:
- `test_reuse_needs_the_definition_to_declare_the_guard` — without `guards=["reuse_answers"]`
  the card is created exactly as before.
- `test_a_changed_option_set_is_a_different_question` — a fourth banker changes the
  signature, so the agent asks again.

## 5. Negative cases: feedback the loop refuses

### `unattended` — timeout defaults are not human feedback

| Metric | Value | Source |
| --- | --- | --- |
| Feedback rows | **0** | `feedback` in `replay-output/after/unattended-*.json` |
| Memory rows | **0** | `runtime.memory.rows` in the test |
| Learning refusals | 2, all `reason="default"` | `learning` trace events |
| CRM writes | 0 | `writes` |

`sweep_expired` resolves rows with `decided_by_user_id=None`. No person decided, so there is
nothing to learn. Test: `tests/test_learning.py::test_a_timeout_default_is_not_human_feedback`.

### `sync_failure` — a runtime failure routed to a person is not a preference

| Metric | Value | Source |
| --- | --- | --- |
| Feedback rows from the retry ask | **0** | `feedback` prompts in `replay-output/after/sync_failure-*.json` |
| Learning refusals with `reason="recovery"` | 3 | `learning` trace events |
| Retry questions still asked | 3 | `pending_inputs` |

**One correction to the brief's wording.** The task asked for sync_failure's feedback count
to be zero. Its *recovery* count is zero, which is the claim that matters, but the scenario's
total is 3 rows, and that is correct rather than a defect: run 1 also answers the banker
question and the hard-fail question, and PLAN §3 says an entity fact is exactly what the loop
should learn. Reporting a flat zero would have meant either distorting the design or hiding a
row. The three stored rows are the banker fact and two hard-fail judgements; none is the
retry answer. Test: `tests/test_learning.py::test_a_recovery_ask_teaches_nothing`, and
`test_reach_cannot_rescue_a_recovery_ask` shows a person cannot flag a recovery ask
`remember=deal` to force it in.

### Approvals are never learned from

In every completed run each `kind == "approve"` row is refused with `reason="approval"`
(2 in day1_screen, 5 in day2_repeat, 4 in day2_remember, 6 in sync_failure). `unattended`'s
two approval cards belong to runs that expired, and an expired run never reaches the learning
step at all. An approval is a gate, not a preference; reusing one would be exactly the
failure mode the challenge warns about.

## 6. Firm reach proposes, it does not apply

Answering with `remember=firm` stores the row, opens a **pending proposal** against the
firm's `screening_criteria` skill, and renders an attributed line under the firm memory key:

```
Suggested for all deals by user-a1 on 2026-09-16, not yet accepted: on "Hard fail: kill or override?", override, reason: Board cleared the size breach. Ask as usual.
```

While it is pending the skill stays at version 1, byte-identical, and the next run still
asks. Accepting appends **version 2** (old body, blank line, proposed text), leaves version 1
reachable, and retracts the suggestion line. One person does not set firm policy with a
checkbox. Test:
`tests/test_learning.py::test_firm_reach_proposes_a_skill_change_instead_of_making_one`.

## 7. Undo and supersede

A newer answer to the same signature on the same deal supersedes the older row, and memory
renders only the newer one. In `day2_repeat` the hard-fail question is answered in run 1 and
again in run 3: two rows, statuses `["superseded", "active"]`, and exactly one hard-fail line
in memory. Test: `tests/test_learning.py::test_a_newer_answer_supersedes_the_older_one`.

## 8. Full check status

| Check | Result |
| --- | --- |
| `uv run ruff check .` | pass |
| `uv run ruff format --check .` | pass |
| `uv run pytest -q` | **65 passed**, no `baseline` marker remains |
| `eval.replay day1_screen --n 5 --fake` | exit 0 — 4 asks, 2 writes |
| `eval.replay day2_repeat --n 5 --fake` | exit 0 — 8 asks, 5 writes |
| `eval.replay day2_remember --n 5 --fake` | exit 0 — 6 asks, 4 writes |
| `eval.replay unattended --n 5 --fake` | exit 0 — 4 asks, 0 writes |
| `eval.replay sync_failure --n 5 --fake` | exit 0 — 12 asks, 3 writes |

## 9. The live model

**Real model, not the fake.** `SANDBOX_MODEL=gpt-4.1-mini`, one iteration:

```sh
uv run python -m eval.replay day2_repeat --n 1 --output-dir replay-output/live41
```

| Metric | Fake | **Live** | Baseline |
| --- | --- | --- | --- |
| Cards | 8 | **7** | 10 |
| Source-contact question | 1 | **1** | 3 |
| CRM writes | 5 | 5 | 5 |
| `reused` | 0 | **0** | — |
| `did_not_reask` | PASS | **PASS** | FAIL |
| Deal id in any system prompt | no | **no** | no |

Cards per run: `cim_screener` 4 → `teaser_intake` **1** → `cim_screener` **2**.

The model wrote its own questions, nothing like the fake's canned strings, and the loop did
not care:

> `Decision for this deal on "Multiple bankers introduced the deal: Avery Lark, Remy Finch, Tessa Wren. Please select one banker to sync into the deal_source_individual CRM field.": contact-a-1 (Avery Lark). Chosen by user-a1 on 2026-09-16. Do not ask this again; act on it, using gated tools for any write.`

That is the point of keying entity signatures on record ids rather than wording (PLAN 10.1):
the classifier still filed it as `fact`/reach `deal`, and runs 2 and 3 acted on it. Run 2 is a
*different agent* on the same deal, with a real model, not asking a question a person already
answered.

**One honest divergence from the fake.** Run 3 also skipped the hard-fail question, which the
fake asks again. Its memory line says `Ask again before acting on it.` — and the model acted
on it anyway. Nothing was unsafe (the status write still stopped at its approval card, and the
proposed `open` still matched the stored `override`), but it is a clean demonstration of
PLAN 5.6's line: **a rule that reaches the model is prose, and prose can be ignored.** If
"ask again" has to hold, it belongs in middleware as a guard, not in a sentence. The `once`
reach is currently prose only. That is the most useful thing the live run taught us.

`reused` is 0 live as well: the model never re-asked a matching question, so the guard never
had to fire. It stays the insurance policy, exercised by the `SequenceModel` test in §4.

**`gpt-5-nano` does not complete this scenario**, for a reason that predates this branch:
`harness/runtime.py:real_model()` sets `max_tokens=4096`, and a reasoning model spends that
budget on reasoning tokens, so `Trace` raises `IncompleteModelResponse
(finish_reason=length)`. Report: `replay-output/live/`. Before it died it had already shown
run 2 reading the memory and skipping the banker question. Fixing it means raising the cap or
using `max_completion_tokens` for reasoning models — a pre-existing harness change, out of
scope for this branch.

## What is not proven

- **Breadth of the live run.** One model, one iteration, one scenario. `day2_remember`,
  `sync_failure` and `unattended` have not been run live, and a real model's batching and
  wording vary between runs, so the live card counts are not as rigid as the fake's.
- **Paraphrase robustness.** Entity questions match on their record ids, so a reworded
  question about the same three bankers still matches. Text questions match on the normalised
  prompt plus option ids, so a genuinely reworded judgement question does not match and the
  agent asks again. That is deliberate, and untested against a real model's wording.
- **One gap in the guard's semantics, found while writing this document and since closed.**
  After a failed write, the `map` branch asks for a *replacement* contact using the same
  prompt and the same options — so it has the same signature, and the guard answered it with
  the contact that just failed to write. The learning step refused to *learn* from a recovery
  ask, but the gate did not refuse to *answer* one. No shipped scenario reaches it
  (`auto_answer` picks `retry` before `map`) and no write escapes its approval, so nothing was
  unsafe, but it was wrong. The plan did not cover this case: §3 rules out reusing the
  *retry/exclude/map* answer, but the replacement question is an entity ask, which §3 treats
  as reusable, and nothing anticipated that a replacement carries the same signature as the
  original.

  The fix is the narrow one: the rule `learning.is_recovery` applied after the run ("the tool
  batch before this ask contained an error") is now one function, `learning.follows_error`,
  and the gate's lookup in `guards.reusable_answer` applies it to the trace so far before
  consulting feedback. A recovery ask is now neither learned from nor answered from feedback.
  Test: `tests/test_round_trip.py::test_a_recovery_ask_is_never_answered_from_feedback` —
  a learned source contact, a failed write of it, then the identical entity question: the
  card is created, no `reused` decision appears, and no write happens. The test fails on the
  previous guard and passes with this one. All fake replay counts are unchanged. §8's
  `learn`-hint extension remains the broader, model-supplied version of the same signal.
