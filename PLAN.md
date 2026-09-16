# Learning from `request_input` answers: design plan

Planning artifact for the Rubi harness challenge. This document records how the
problem was framed, the options considered, the chosen design, what is
deliberately left out, and how the effect will be measured. It is written to be
read before the code.

## 1. The problem, precisely

An agent pauses with `request_input` when it needs a person. The person's answer
is stored on a pending-input row and replayed into the run as a tool message.
After the run, nothing reads that row again. The next run of the same agent, or
a sibling agent on the same deal, asks from scratch.

In the sandbox this shows up as the `day2_repeat` scenario: screener, then
teaser intake, then screener again, all on deal A. The banker question ("which
of these three contacts is the deal source?") is asked three times. The
`did_not_reask` assertion flags the repeat and the replay exits 1.

Baseline measured on 2026-09-14 with the fake model:

| Runs | Cards created | Banker question asked | Kill/override asked | CRM writes |
| --- | --- | --- | --- | --- |
| 3 | 10 | 3 | 2 | 5 |

The system prompt for run 3 contains an empty `# Memory` section. That empty
section is the gap.

## 2. Constraints found in the code

These shape what a correct design can look like. They are not all in the README.

- **The repeat check counts every pending-input row regardless of status**
  (`eval/assertions.py`). A learned answer must prevent the row from being
  created. Either the model does not call `request_input`, or middleware
  answers the call before the gate registers a card.
- **The fake model ignores memory.** It emits the banker question whenever no
  banker ask exists in the message history. A prose-only mechanism would work
  with a real model and show nothing in CI. The README permits extending the
  fake; the CI comment requires the learning path to be "exercised by the test
  model." The extension must be small and its simulation explained.
- **Memory is user-scoped.** `MemoryStore.search` returns rows keyed to the
  running user only. A deal's source contact is a firm fact, not a user
  preference. Scope rules need a firm-wide level.
- **Deal ids must not appear in the system prompt.** An existing isolation test
  asserts this. Memory is already filtered by deal key, so rendered lines must
  say "this deal" and never print the id.
- **Unattended defaults are attributed to no user.** `sweep_expired` resolves
  rows with `decided_by_user_id=None`. A naive extractor would learn "skip"
  from a timeout. That is a runtime event, not human feedback.
- **The `guards` slot is declared after the approval gate.** Middleware wraps
  outer to inner in list order. Anything placed there never runs for a gated
  call because the gate raises first. Reuse has to be evaluated inside or
  before the gate.
- **The CRM already holds the banker answer after run 1.** Later runs never
  read it, and the intake agent has no tool to read it. A "check the CRM first"
  fix would solve the banker case only. It would not cover skips, rejections,
  or judgement calls, and it is not learning. Both signals are worth having;
  this plan builds the feedback path and notes the CRM path as a complement.
- **The stored rationale is the model's text.** There is no field for the
  human's reason, and the `request_input` docstring tells the model its answers
  are never reused. Both are inputs to the real model's behaviour.
- **The preference store is never read.** Prompt composition ignores it. It is a
  slot, not a mechanism.

## 3. Kinds of ask

The brief says some asks patch a data-model gap, some route a runtime failure to
a person, and some are real judgement calls. The sandbox fires every shape. The
loop's first job is to tell them apart, because the right destination differs.

| Ask | Category | Reusable? | Default reach | Where it lands |
| --- | --- | --- | --- | --- |
| Which banker is the source (entity options) | Fact the data model lacks | Yes | This deal, whole firm | Memory note; guard may answer silently |
| Kill or override a hard fail (text options) | Judgement | Only if the human says so | Once, shown as context | Memory note; ask again |
| Retry, exclude or map after a failed write | Failure recovery | No | None | Nowhere |
| Approve a `write_crm_field` or `set_deal_status` | Gate | Never | None | Kept as evidence only |
| Safe-default skip after TTL, no user | Not human feedback | No | None | Nowhere |
| Typed free text (`other_text`) | Judgement, unstructured | No | Once, shown as context | Memory note |

Classification is generic and does not mention bankers or deals:

- `kind == "approve"` is a gate. Never reusable.
- `decided_by_user_id is None` is a default. Refused.
- A choose card whose preceding tool event in the run trace has `status ==
  "error"` is recovery. Refused.
- A choose card with `option_type == "entity"` is a fact. Reach defaults to the
  deal.
- Any other choose card is a judgement. Reach defaults to once.
- `other_text` answers are judgement prose. Reach defaults to once.

The human can override the default reach with the flag described in section 5.
The classifier only sets the default.

## 4. Where feedback could land, and why the alternatives lose

| Destination | Who reads it | Blast radius | Verdict |
| --- | --- | --- | --- |
| Memory (firm, user, deal keys) | Every agent in scope, on the next run | Small: one deal, or one firm | **Primary.** Already model-readable. Scope keys exist; they need a firm-wide level. |
| Preference store (firm, agent, user) | Nobody today | Medium | Skip. Not wired into the prompt, and agent scope is wrong for deal facts. |
| Skill body | Every agent with the skill, firm-wide | Large | Only through a proposal a person accepts. Skills are versioned; a checkbox must not rewrite firm criteria. |
| Agent instructions | One agent, firm-wide | Large | Only through a proposal. `DefinitionStore.append` already versions. |
| Middleware guard | The runtime, at call time | Precise | **Secondary.** Reuse of an exact-signature deal fact for choose cards. Never for approve cards. |
| Kickoff message | One run | Small | Rejected. The kickoff belongs to the trigger, and injecting there hides learning from the trace's system message. |

Where extraction runs was also a choice:

| When | Trade-off |
| --- | --- |
| At answer time, in `PendingInputStore.respond` | Earliest, but the store is dumb and the answer may still be rejected at the write gate. |
| In `apply_decision` in the approval gate | Has the call and the decision, but mixes learning into gating. |
| At run completion, in `Runtime._invoke` | Sees the whole outcome, including whether the chosen value was written. **Chosen.** |

Extraction is deterministic. An LLM summariser for free-text reasons is a later
extension; it cannot run under the fake and would blur what the demo proves.

## 5. Chosen design

### 5.1 Components

1. **`FeedbackStore`** (`harness/store/feedback.py`). Structured rows, one per
   learned answer. Firm-keyed like every other store.
2. **Learning step** (`harness/learning.py`). Runs when a run completes. Reads
   the run's pending-input rows, classifies each, writes feedback rows, renders
   active rows into memory. Refuses the categories in section 3.
3. **Memory scope extension.** `MemoryStore.search` also returns firm-wide rows
   (`user_id=None`) for the deal and for no deal. Firm isolation is unchanged.
4. **Human reach and reason on answers.** The response object gains optional
   `remember` and `reason` fields. The CLI exposes them as `--remember` and
   `--reason`. Validation limits which cards may carry them.
5. **Guard in the approval gate.** Before registering a choose card, the gate
   looks up an active feedback row with deal reach matching the card's
   signature. On a hit it returns the stored answer as the tool message and
   records a `decision` trace event with `status="reused"`. No pending row is
   created. Approve cards are never consulted.
6. **Proposals** (`harness/store/proposals.py`). Firm-reach answers create a
   proposal targeting a skill or an agent's instructions. Accepting appends a
   new version; rejecting closes it. Until accepted, memory shows an attributed
   suggestion and the agent keeps asking.
7. **Fake model extension.** Reads one structured memory line for a source
   contact and, when present, skips the banker question and writes the contact
   directly. Reads a "do not ask again" line for the hard-fail decision and
   applies it. Without those lines it behaves exactly as today.
8. **Prompt and docstring updates.** The foundation prompt explains the Memory
   section: decisions there were made by a person, do not re-ask them, still
   use gated tools for writes. The `request_input` docstring stops claiming
   answers are never reused.

### 5.2 Data model

```
Feedback
  id, firm_id, agent_id, run_id, pending_id
  user_id            who decided; never None for a stored row
  deal_id            from run bindings; None for firm-level rows
  signature          tool + normalised prompt + sorted option ids (+ entity ids)
  category           fact | judgement | free_text | approval
  answer             {"selected": ...} or {"other_text": ...}
  reason             the human's words, optional
  reach              once | deal | firm
  status             active | superseded | retracted
  created_at

Proposal
  id, firm_id, feedback_id
  target             skill name or agent_id
  proposed_text
  status             pending | accepted | rejected
  decided_by_user_id, decided_at
```

The signature is what makes reuse safe. It includes the option set, so if a
fourth banker appears the signature changes and the agent asks again.

### 5.3 The path an answer takes

```
card answered ──► validate reach for this card kind
                   │  approve card: reach forbidden
                   │  recovery ask: reach forbidden
                   │  no user: nothing to learn
                   ▼
run completes ──► classify ──► FeedbackStore row (or refuse)
                                │
                     ┌──────────┼──────────────┐
                     ▼          ▼               ▼
              reach: once   reach: deal    reach: firm
              memory note   memory note    proposal + attributed note
              "ask again"   "do not ask"   "suggested, ask"
                                │
                     next run: model reads memory
                                │
                     model asks anyway? ──► gate checks signature
                                            hit ──► reused, no card
                                            miss ─► card as today
```

### 5.4 Three tiers of autonomy

1. **Automatic, as prose.** Feedback rows render into memory. The model reads
   them. This is the primary loop and the one the brief asks for.
2. **Automatic, with a hard boundary.** The guard answers an exact-match choose
   card silently. It cannot touch an approve card, so every CRM write still
   stops at its gate. This is the defence against a model that ignores memory,
   and it is what makes the effect countable.
3. **Proposed, not applied.** Firm-reach answers become proposals. A person
   accepts them into a new skill or definition version.

### 5.5 "Don't ask again" reach

The human's flag is the loop's best signal about which answers deserve reuse.
Rules:

- `remember=deal` is allowed on choose cards that are facts or judgements. It
  widens a judgement from once to deal.
- `remember=firm` is allowed on the same cards. It creates a proposal; it does
  not change anything an agent reads as a rule until accepted.
- `remember=none` opts an answer out of learning entirely.
- The flag is rejected on approve cards, on recovery asks, and it cannot exist
  on unattended defaults because there is no human.

The line it never crosses: the flag may change what the agent is told. It may
never change what the runtime enforces. Tool modes, allowlists, and gates stay
admin settings on the agent definition.

### 5.6 What is enforced versus what is prose

| Rule | Prose or guard | Where |
| --- | --- | --- |
| "This deal's source contact is X, do not ask again" | Prose | Memory note |
| Answer a matching choose card without a person | Guard | Approval gate, before card registration |
| Never auto-approve a write | Guard | Approval gate consults feedback only for `kind == "choose"` |
| Never learn from a timeout default | Guard | Learning step filters `decided_by_user_id is None` |
| Never cross firms | Guard | Every store is firm-keyed; the guard looks up by the run's firm |
| Reuse allowed for this agent at all | Definition setting | A `guards` field on `AgentDefinition`, versioned with it |

### 5.7 Undo and versioning

- A new human answer with the same signature on the same deal supersedes the
  old row. Memory renders active rows only.
- Any row can be retracted. Retracted rows stop rendering and the guard ignores
  them.
- Proposals accepted into a skill or definition create a new version; the
  previous version remains in the store.
- Whether an agent may reuse at all is a field on its definition, so turning it
  off is a definition version, with the same audit trail as any other change.

## 6. Not built, on purpose

- Automatic edits to skills or instructions. Everything firm-wide goes through a
  proposal.
- Aggregating across deals to detect a pattern ("user A overrides EBITDA on
  every deal"). The proposal mechanism is the hook for this; the aggregation is
  a next step.
- An LLM summariser for free-text reasons.
- Wiring the preference store into the prompt.
- Persistence, a database, or a UI. The stores stay in memory per process, as
  the README allows.
- Learning from a `modify` on an approve card. The corrected value is a strong
  signal, but it lives in write arguments rather than a choice, and the MVP
  keeps the boundary between choices and gates clean.

## 7. How to know it is working

### 7.1 Metrics in the replay report

- **Asks per question signature per deal across runs.** The primary number. For
  `day2_repeat` the banker question goes from 3 to 1.
- **Cards created.** Expected 10 before, 8 after with default reach, 7 when the
  override is flagged `remember=deal`.
- **Reused decisions.** Count of `decision` trace events with `status="reused"`.
  Zero with the fake reading memory, nonzero with a model that asks anyway.
- **Write approvals.** Must not drop. Every `write_crm_field` and
  `set_deal_status` still pauses.
- **Feedback rows by category** and **proposals by status**, added as sections
  of the JSON report.

### 7.2 Evidence to include

- Before and after replay reports for `day2_repeat`, fake model, `--n 5`.
- The system prompt from run 3 in each, showing the empty and the populated
  Memory section.
- A live-model replay when the key is available, with the reused-decision
  count and the trace excerpt where the gate answered a card.
- A negative case: `sync_failure` after the change, showing no feedback row for
  the retry question and the retry question still asked.
- A negative case: `unattended` after the change, showing no feedback row from
  the timeout defaults.
- A firm-reach case: the override flagged `remember=firm` creates a proposal,
  the skill is unchanged, and the next screener still asks.

### 7.3 Tests

The three `baseline` tests and the CI step that expects the failure are
replaced. New tests cover:

- `day2_repeat` passes `did_not_reask`; asks equal 8; memory holds the source
  contact line after run 1.
- Feedback rows are firm-isolated; a firm B run on deal B sees nothing from
  firm A.
- Timeout defaults create no feedback rows.
- Recovery asks create no feedback rows.
- Approve cards are never answered by the guard; writes still pause.
- A changed option set produces a different signature and a fresh card.
- A newer answer supersedes an older one and memory renders only the newer.
- `remember` is rejected on approve cards and on recovery asks.
- `remember=deal` on the override causes the third run to skip that question;
  the proposed status still matches the stored decision.
- `remember=firm` creates a pending proposal; accepting it appends a new skill
  version; the previous version is unchanged.
- A sequence model that asks despite memory gets a reused decision in the trace
  and no pending row.
- The deal id still never appears in the system prompt.

CI keeps the `day1_screen`, `unattended` and `sync_failure` replays, and
replaces the intentional-failure step with a passing `day2_repeat --n 5 --fake`
that also greps the report for the reuse marker.

## 8. Risks and open questions

- **A real model may ignore memory and ask anyway.** The guard covers the exact
  match. A paraphrased question with the same options still matches on the
  option set; a question with different options does not, by design.
- **Reach flags are only as good as the person's judgement.** Deal reach is
  contained. Firm reach is a proposal precisely because one person should not
  set firm policy with a checkbox.
- **The recovery heuristic is a heuristic.** "Preceded by a tool error" is right
  for the sandbox. A model-supplied hint on the ask (a `learn` argument on
  `request_input`) would be more honest and is a natural extension; the harness
  should treat it as a hint, not a verdict.
- **The fake extension proves the plumbing, not the model.** The live run is
  the evidence that a real model reads and honours the memory line.

## 9. Order of work

1. Feedback store, learning step, memory scope, rendering. Baseline tests
   replaced. `day2_repeat` passes under the extended fake.
2. Reach and reason on answers, CLI flags, validation limits.
3. Guard in the approval gate with the reused trace event and its tests.
4. Proposals store with accept and reject.
5. Report sections, before and after evidence, live run.
6. Walkthrough notes.

## 10. Implementation contract

Details that every piece of the build must agree on. Sections 1 to 9 explain
why; this section pins what.

### 10.1 Signature

The signature identifies "the same question" across runs.

- Entity questions (any option carries `entity_id`):
  `request_input|entity:` + comma-joined sorted `entity_id`s. The prompt text
  is not included, so a paraphrase with the same records matches. This mirrors
  how `did_not_reask` keys repeats.
- Text questions: `request_input|text:` + normalised prompt + `|` + comma-joined
  sorted option ids. Normalised means lowercased, whitespace collapsed,
  trailing punctuation stripped.
- Free-text-only questions (empty options): `request_input|free:` + normalised
  prompt.

A helper `signature(tool_name, args)` lives in `harness/learning.py` and is the
only place that computes it. The gate and the learning step both call it.

### 10.2 Memory rendering

The learning step owns two memory keys per firm: `(firm, None, deal_id)` for
deal rows and `(firm, None, None)` for firm-level notes. It rebuilds those keys
from active rows every time it runs, so supersede and retract take effect and
nothing duplicates. `MemoryStore` gains `replace(firm_id, user_id, deal_id,
lines)`. Existing `put` and user-keyed rows are untouched.

Line formats, exact, because the fake parses them:

| Row | Line |
| --- | --- |
| reach `deal` | `Decision for this deal on "{prompt}": {selected} ({label}). Chosen by {user} on {date}{, reason: {reason}}. Do not ask this again; act on it, using gated tools for any write.` |
| reach `once`, selected | `Context for this deal on "{prompt}": {user} chose {selected} ({label}) on {date}{, reason: {reason}}. Ask again before acting on it.` |
| reach `once`, free text | `Context for this deal on "{prompt}": {user} wrote "{other_text}" on {date}. Ask again before acting on it.` |
| reach `firm`, proposal pending | under the firm key: `Suggested for all deals by {user} on {date}, not yet accepted: on "{prompt}", {selected}{, reason: {reason}}. Ask as usual.` |

`{prompt}` is the original prompt text, `{date}` is `YYYY-MM-DD`. Lines never
contain a deal id and never contain the text `EBITDA above $`, which the fake
matches against the system prompt.

### 10.3 Recovery detection

For each choose row, find the `gate` trace event whose `pending_ids` include
the row id. Scan backwards for the nearest `tool` event with a `tool_call_id`
and a status of `success` or `error`, skipping `started` and `model` events. If
that status is `error`, the ask is recovery. In the sandbox the retry question
follows the failed write's error event directly.

### 10.4 The `remember` and `reason` fields

- Response objects may carry `remember` in `{"none", "deal", "firm"}` and
  `reason` as a string. Both are optional and live in `PendingInput.response`.
- `validate_response` rejects `remember` when the row's kind is `approve` or
  when the action is not `choose`. Message: "Reach cannot be set on an
  approval" or "Reach requires a choice".
- Recovery asks are only known from the trace, so the learning step refuses
  `remember` on them and records a `learning` trace event with
  `status="refused"` and `reason="recovery"`.
- CLI: `sandbox answer <id> <option> --remember deal --reason "..."`. The replay
  policy in `scenarios/common.py` takes an optional map from prompt text to
  reach and applies it when a card's prompt matches.

### 10.5 Definition field

`AgentDefinition` gains `guards: list[str] = field(default_factory=list)`. The
value `"reuse_answers"` allows the gate to answer from feedback. All three
seeded agents declare it. Without it the gate behaves exactly as today. The
empty `harness/middleware/guards.py` holds the pure lookup
`reusable_answer(ctx, call) -> tuple[dict, str] | None` returning the answer
and the feedback id.

### 10.6 Guard placement

Inside `ApprovalGate.awrap_tool_call`, after `should_gate` and before any card
is registered:

1. If `call["name"] == "request_input"`, the validated `kind` is `choose`, the
   definition declares `reuse_answers`, and `reusable_answer` returns a hit:
   record `decision` with `status="reused"` and `feedback_id`, and return a
   `ToolMessage` whose content is the JSON answer. No pending row.
2. In the sibling loop, skip siblings for which `reusable_answer` returns a
   hit, so they are not registered as cards either. They are answered when
   their own wrap runs.

Only rows with `status="active"` and `reach="deal"` for the run's firm and deal
are eligible. Approve cards never reach the lookup.

### 10.7 Learning hook

`Runtime` gains `self.feedback = FeedbackStore()` and
`self.proposals = ProposalStore()`, both passed into `ctx`. In `_invoke`, after
`run.status = "completed"`, call `learning.absorb(ctx)`. It records one
`learning` trace event per pending row with `status` in `{"stored",
"refused"}`, `category`, and `reach`. Failed and expired runs do not learn.

### 10.8 Proposals

`ProposalStore` rows follow section 5.2. `accept(proposal_id, *, firm_id,
user_id, runtime)`:

- target is a skill name: `SkillStore.append(firm_id, name, body)` writes a
  new `Skill` with `version + 1` and body equal to the old body, a blank line,
  and the proposed text. The old version stays reachable by version.
- target is an agent id: `DefinitionStore.append` with the same instructions
  plus a blank line and the proposed text, version incremented.

Proposed text: `{user} on {date}: for all deals, on "{prompt}", choose
{selected}{ (reason: {reason})}.` `reject` sets status and nothing else.
Accepting also retracts the firm-key memory suggestion line for that proposal.

### 10.9 Report and CLI

`eval/report.py` adds `feedback` (rows), `proposals` (rows), and `reused`
(count of `decision` events with `status="reused"` across runs). The `inspect`
command adds the run's feedback rows.

### 10.10 Scenarios and tests

- New scenario `day2_remember`: screener on deal A with the hard-fail answer
  flagged `remember=deal`, then screener again. The second run creates only
  the two write-approval cards.
- Firm reach is covered by a test, not a scenario: the override answered with
  `remember=firm` creates a pending proposal, the skill body is unchanged, the
  next screener still asks, and accepting appends skill version 2.
- The `baseline` marker is removed from `pyproject.toml` and the three tests
  that carry it are replaced by tests of the implemented behaviour in the
  normal group. `SCENARIOS` gains `day2_remember`, so the parametrised scenario
  test covers it.

### 10.11 CI

Remove the "Starting-point expectations" pytest step. Replace the final step
with two replays that must exit 0: `day2_repeat --n 5 --fake` and
`day2_remember --n 5 --fake`. Keep the other three replay steps unchanged.

### 10.12 Fake model

Before composing questions, the fake reads the system prompt for
`Decision for this deal on "Which banker should be the deal source?": (\S+)`
and `Decision for this deal on "Hard fail: kill or override?": (kill|override)`.
A remembered banker becomes the selected contact without a question. A
remembered screening decision sets the status without a question. Context lines
are ignored, which simulates a model that confirms judgement calls. Everything
else in the script is unchanged.
