# Rubi harness challenge

> **Submission.** The learning loop is built and merged to `main`. Read
> [PLAN.md](PLAN.md) first (the design, the alternatives, and the contract the
> code follows), then [EVIDENCE.md](EVIDENCE.md) (before and after numbers,
> the negative cases, a live-model run, and one gap found while writing it and
> since fixed), then [DEMO.md](DEMO.md) (the rehearsed live run). The rest of
> this file is the original brief; the two passages that described the
> starting defect are updated below to say what `main` does now.

Build an MVP that helps agents learn from human responses to `request_input`.
Today, answers are kept in the run record but never reused. A later run of the
same agent, or another agent working on the same deal, asks the same question
again.

Your loop should store useful feedback in a structured form and feed it into
context an agent can read: memory, skills, or its system prompt. Decide which
feedback to learn from, where it applies, and how to measure its effect. The
mechanism should support different agents and use cases; deal screening is the
worked example.

**Spend no more than 10 hours.** Incomplete work with a clear explanation of
what remains is welcome. Read the [full challenge brief](CHALLENGE.md) for the
design questions and assessment criteria.

## What to submit

1. **A planning artifact:** the options you considered, your chosen design,
   scope rules, tradeoffs, and how you would evaluate improvement.
2. **A working MVP:** code and before/after evidence showing how feedback
   changes a later run. Explain any incomplete work and next steps.
3. **A walkthrough:** prepare a 15–20 minute design explanation and live demo,
   followed by discussion in a roughly 45-minute session.

## Get started

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and macOS or Linux.
From your clone of this repository:

```sh
uv sync --locked
cp .env.example .env
uv run sandbox run day1_screen --fake
```

The scripted fake works without an API key. Keep this terminal running. It
prints two questions with pending-input ids. In a second terminal, answer
using the ids shown:

```sh
uv run sandbox answer <banker-pending-id> contact-a-1
uv run sandbox answer <screening-pending-id> override
```

The first terminal then prints two write-approval cards. Answer both and
inspect the completed run:

```sh
uv run sandbox answer <write-pending-id> approve
uv run sandbox answer <status-pending-id> approve
uv run sandbox inspect <run-id>
```

Use `reject` or `cancel` to decline a card. `inspect` shows the run, trace,
pending inputs, and synthetic CRM state. Ctrl+C ends the session and clears
its state. Stop the current session before starting another.

For a real model, add the supplied `OPENAI_API_KEY` to `.env`, set
`SANDBOX_FAKE_MODEL=0`, and omit `--fake`. `SANDBOX_MODEL` selects the model.
Answer the option ids actually printed; wording, batching, and tool order may
vary. Review each proposed write before approving it.

## Reproduce the problem

| Scenario | Behavior |
| --- | --- |
| `day1_screen` | Choose a banker and kill/override a screening failure, then approve writes |
| `day2_repeat` | Run screener → intake → screener on the same deal; the banker question repeats |
| `unattended` | Unanswered write approvals expire; safe choice defaults resolve without a human |
| `sync_failure` | Recover from a failed write and demonstrate the retry cap |

Save the starting behavior:

```sh
uv run python -m eval.replay day2_repeat --n 1 --fake --output-dir replay-output/before
```

**At the branch point this command exited 1:** `did_not_reask()` detected the
repeated banker question and still wrote a JSON report. On `main` it exits 0.
To reproduce the starting behavior, run it from a worktree at commit `d2534d2`
(`git worktree add ../before d2534d2`). The other scenarios pass at both.

`day2_repeat` includes all three runs in one process, sharing the stores.
Each replay iteration starts fresh. Separate CLI processes do not share memory.

## Demonstrate your improvement

After implementing the loop, run the same scenario with
`--output-dir replay-output/after`. Use `--n 5` to repeat an experiment.
Reports contain model input messages and responses, human decisions, tool calls,
run status, and the final CRM state. `replay-output/` is gitignored; include
relevant excerpts with your submission.

Show that the repeated-question check passes because applicable feedback was
reused. Explain what reached the model and how it affected the next run. Keep
required write approvals and firm isolation intact, and show a case where
feedback should not be reused.

Replay answers questions using the policy in `scenarios/common.py` and
automatically approves write cards against the synthetic CRM. Check proposed
arguments and resulting values when assessing correctness.

The fake uses the real graph, middleware, and tools, but follows a scripted
policy. It does not interpret arbitrary changes to memory, skills, or prompts.
You may extend it or add a test model to exercise your mechanism. Explain what
it simulates; changing the script alone does not demonstrate learning.

When API access permits, also capture a live-model run:

```sh
uv run python -m eval.replay day2_repeat --n 1 --output-dir replay-output/live
```

For replay, `--fake` selects the fake; omitting it selects the real model,
regardless of `SANDBOX_FAKE_MODEL`. Clearly identify which evidence uses a fake
and which uses a real model, and describe any validation you could not complete.

## Implementation scope

The sandbox's backend consists of in-memory Python stores. Feedback surviving
across runs within one process is sufficient for the MVP. A database,
deployment, and persistence across restarts are not required.

Memory currently uses firm, user, and optional deal keys. Matching entries are
included in the prompt, and agents in the same scope share them. You may extend
these scope rules or choose a different model-readable destination.

A gated tool call creates pending-input records and stops the run. Answering
all cards starts a fresh invocation on the same checkpoint thread, with the
decisions returned as tool messages. Preserve this pause/resume behavior.

The learning path is deliberately missing: nothing reads decisions across
runs, extracts them into memory, or updates preferences. The stored `rationale`
is the model's text, not the human's explanation. There is no input for a
human's reason, and the guards middleware is an empty slot. Decide which gaps
your MVP needs to address.

## Find the relevant code

| Area | Files |
| --- | --- |
| Agent instructions, tools, and versions | `seed/agents/`, `harness/store/definitions.py` |
| Prompt composition | `harness/prompt.py` |
| Memory and preferences | `harness/store/memory.py`, `harness/store/preferences.py` |
| Skills and firm criteria | `seed/skills/`, `harness/store/skills.py` |
| Human-input schema and decisions | `harness/request_input.py`, `harness/store/pending_inputs.py` |
| Approval, authorization, recovery, and guards | `harness/middleware/` |
| Execution and resume | `harness/runtime.py` |
| Tool definitions and synthetic CRM | `harness/tools.py`, `harness/store/gateway.py` |
| Scenario setup and replay answers | `scenarios/`, `scenarios/common.py` |
| Assertions and reports | `eval/`, `harness/middleware/trace.py` |
| Scripted model | `harness/fake_model.py` |

## Run the checks

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The brief shipped three `baseline` tests, behind a `-m baseline` marker, that
documented the starting defect: repeated questions, empty memory/preferences,
and a failed repeat replay. They are replaced by tests of the implemented
behavior in `tests/test_learning.py`, `tests/test_scenarios.py`, and
`tests/test_round_trip.py`, and the marker no longer exists. The rest of the
suite covers harness behavior, including approval, isolation, pause/resume,
and error recovery.

CI's former `Verify the intentional repeat-question failure` step is replaced
by two replays that must exit 0, `day2_repeat` and `day2_remember`. The
`day1_screen`, `unattended`, and `sync_failure` checks are unchanged.
