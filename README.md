# Rubi harness sandbox

Three agents process invented deals: a CIM screener, a teaser intake agent,
and an unattended CRM hygiene agent. They share a gateway but do not learn
from each other's human decisions. Run the screener today and intake tomorrow:
the banker question comes back. That missing feedback path is the exercise.

A model calls tools through an ordered middleware stack. A gated call creates
pending-input rows and raises an exception. The caller returns the cards;
answering all cards starts a fresh graph invocation on the same checkpoint
thread. Decisions return as tool messages, then execution continues.

The human decision lives outside graph execution because a person can answer
later, after the original invocation has unwound. This uses neither a graph
interrupt nor a waiting model call. Everything lives in one local process's
memory. OpenAI is the only external runtime connection; the fake model needs
none. This repository was implemented independently with public dependencies.

## Run it

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and macOS or Linux.

```sh
uv sync --locked
cp .env.example .env
uv run sandbox run day1_screen --fake
```

Keep that terminal running. Cards print their ids, options, context, rationale
and deadline. In another terminal, in this repository:

```sh
uv run sandbox answer <banker-pending-id> contact-a-1
uv run sandbox answer <screening-pending-id> override
# The first terminal now prints two approval cards. Answer both:
uv run sandbox answer <write-pending-id> approve
uv run sandbox answer <status-pending-id> approve
uv run sandbox inspect <run-id>
```

`reject` and `cancel` decline a card. For a free-text card use
`sandbox answer <id> 'your answer' --other`. Multi-select cards take comma-separated
ids. To modify an approval, use a complete JSON response:

```sh
uv run sandbox answer <id> '{"action":"modify","args":{"deal_id":"10000000-0000-4000-8000-000000000001","field":"geography","value":"North America"}}' --json-response
```

The local Unix socket is private to your OS user. There is one session at a
time. `inspect` includes run status, trace, pending rows and the gateway's write
snapshot. Ctrl+C stops the process and discards all state. Run ids from a stopped
session cannot be answered. A second `run` refuses to replace an active session.

For a real model, put the dedicated sandbox key in `.env` and omit `--fake`.
`SANDBOX_FAKE_MODEL=1` makes the CLI use the fake by default. All model selection
comes from `SANDBOX_MODEL`; there is no hard-coded fallback.

## Scenarios and replay

| Scenario | What to look for |
| --- | --- |
| `day1_screen` | Three banker options plus kill/override in one batch, then gated writes |
| `day2_repeat` | Screener, intake, then screener on the same deal; source questions repeat |
| `unattended` | A write expires on each open deal; a separate source ask defaults to skip |
| `sync_failure` | One failed write recovers after retry; two raised failures cap the third attempt |

The unattended scenario advances the sweep clock past the deadline without
sleeping. Its default answers have `decided_by_user_id=None` and never write a
guessed banker. An approval gate has no safe default.

```sh
uv run python -m eval.replay day1_screen --n 5 --fake
uv run python -m eval.replay day2_repeat --n 5 --fake
uv run python -m eval.replay unattended --n 5 --fake
uv run python -m eval.replay sync_failure --n 5 --fake
```

Replay auto-answers cards from a small answer table, counts asks and writes,
and checks the results. `day2_repeat` deliberately prints red FAIL rows and
exits 1 because `did_not_reask()` fails. The other scenarios should pass.
Remove `--fake` to observe real-model variation. Each replay iteration gets
fresh stores; the runs *within* one iteration share them.

The fake is a scripted policy over visible messages. It uses the same graph,
middleware and tool bodies as the real model. Its choices are deterministic;
it does not emulate arbitrary prompt edits. Use real-model replay to evaluate
prompt changes, and extend the fake for new scripted behaviors.

## Harness map and levers

| Layer / lever | File | Consumer |
| --- | --- | --- |
| Definition, versions, allowlist, tool modes | `harness/store/definitions.py`, `seed/agents/` | Agent builder, authorization and gate |
| Platform bindings | `scenarios/common.py`, `harness/store/runs.py` | Middleware context; not injected into model messages |
| Prompt composition | `harness/prompt.py` | Foundation → memory → agent instructions → skills |
| Skills and firm criteria | `seed/skills/`, `harness/store/skills.py` | One skill section per attachment, scoped to firm |
| Tool metadata | `harness/registry.py`, `harness/tools.py` | Discovery, authorization and approval |
| Middleware ordering | `harness/middleware/__init__.py` | Auth → error recovery → gate → empty guards slot → trace |
| Pause and decisions | `harness/middleware/approval_gate.py`, `harness/request_input.py` | Sibling batching and decision application |
| Input lifetime | `harness/store/pending_inputs.py` | Human responses and expiry sweep; default TTL is 72 hours |
| Execution | `harness/runtime.py` | Build, run, resume, in-memory checkpoints |
| Memory | `harness/store/memory.py` | Prompt search keyed by firm, user and optional deal |
| Preferences | `harness/store/preferences.py` | An available firm/agent/user store; no automatic consumer yet |
| Backend stand-in | `harness/store/gateway.py`, `seed/` | Synthetic documents, contacts, field validation, failure injection |
| Feedback and measurement | `harness/middleware/trace.py`, `eval/` | Run trace, replay and repeat-question assertion |

Pass `ttl=timedelta(...)` to `bootstrap()` to change input lifetime in experiments.
Definitions append versions; a paused run keeps the definition it started with.
Firm B has a different screening ceiling, making accidental cross-firm prompt
or data access visible. Contact ids are only valid for their own deal.

## The asks

The three representative decision shapes are: pick an introducing banker when
the CRM accepts one contact; kill or override a screening hard fail; and retry,
exclude or remap a failed CRM write. A write approval is a separate card.
These are production-shaped mechanics with synthetic firms, people and deals;
no customer records or production counts are included.

`rationale` is the model's last assistant text. It is not a person's explanation
of their choice. A choose answer is returned as JSON without running the tool
body. An approve decision runs the tool; modify replaces its arguments; reject
or cancel produces an error tool message. Unknown decisions reject.

Error recovery counts raised exceptions per tool in a run. After two consecutive
errors, another call receives terminal `REJECTED` before a pending card can be
registered. A successful result resets that tool's count. The model reports the
failure; the run continues. A tool that returns an error *string* does not raise
an exception, so it does not increment the count.

Provider errors fail the run without retrying. A truncated, filtered, malformed
or empty model response also fails; it must not look like a completed task.
The trace preserves response metadata and token usage for diagnosis.

## Deliberately missing

There is no cross-run read of pending inputs, no automatic extraction from tool
messages into memory, no automatic preference update, and no UI for capturing
a person's reason. The guards file is an empty slot. Apart from replay and the
mechanics regression suite, there is no evaluation framework. These gaps are
intentional; the baseline must reproduce repeat questions.

## Exercise

**Pending the final take-home brief.** The exercise will be inserted verbatim
when supplied. Meanwhile, reproduce the repeat with `day2_repeat` and inspect
where human decisions stop flowing back into subsequent runs.

## Model, key and budget

The default model id appears in `.env.example`. Its published standard text
rates are $0.05 per million input tokens and $0.40 per million output tokens
([model pricing](https://developers.openai.com/api/docs/models/gpt-5-nano)).
For example, 20,000 input and 5,000 output tokens cost about $0.003. Reasoning
tokens count toward output, and total run costs depend on every model call.

Only use a dedicated sandbox project key. Never use a production credential.
The repository does not include a key or claim that a project cap is configured.
Before distributing access, the owner must set a monthly amount and enable
**Enforce a hard limit** in project settings, confirm it is active, then share
the key through an expiring password-manager link. An alert alone does not cap
spending. Enforcement may lag slightly
([spend limits](https://developers.openai.com/api/docs/guides/spend-limits)).
Revoke the candidate's key when the exercise ends.

Runtime calls disable external tracing even if the parent environment enables
it. The tracing library is a transitive framework dependency; no tracing
service is configured. The fake and tests make no model requests.

## Checks

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

CI runs these checks and the deterministic scenarios without a key. The
repeat-question test asserts that the baseline failure remains observable.
