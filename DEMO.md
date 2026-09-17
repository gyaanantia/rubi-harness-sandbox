# Live demo runbook

A rehearsed script for the walkthrough. The Act 1–4 commands were run end to end on this
branch and the outputs below are what actually appeared; Act 5's numbers vary by run, and the
optional "before" worktree is plain git.

**How you interact with the agent.** You do not chat with it. These agents are *triggered*
(a document arrives, a cron fires), they work autonomously, and they stop to ask a person
only when they need judgement. Your side of the conversation is answering cards:
`sandbox answer <pending-id> <option-id>`. That is the interaction the challenge is about,
and it is the thing the loop learns from.

## Setup, once, before you present

```sh
uv sync --reinstall-package rubi-harness-sandbox   # cli.py is force-included in the wheel
uv run pytest -q                                   # 64 passed
```

Two terminals, both in the repo root. **Terminal 1** runs the agent; **Terminal 2** is the
human. Stop any running session with Ctrl+C before starting another — one session owns the
socket.

Optional 60-second "before", in a throwaway worktree so you never switch branches on stage:

```sh
git worktree add /tmp/before d2534d2 && (cd /tmp/before && uv run python -m eval.replay day2_repeat --n 1 --fake)
#   1 |   10 |      5 | FAIL: Repeated source-contact question on the same deal
git worktree remove /tmp/before          # afterwards
```

---

## Act 1 — the repeat is gone, and you can watch it happen (3 min)

**Terminal 1:**

```sh
uv run sandbox run day2_repeat --fake
```

It pauses and prints two cards with their pending ids. **Terminal 2**, using the ids on
screen:

```sh
uv run sandbox answer <banker-id> contact-a-1
uv run sandbox answer <hardfail-id> override
```

Then approve the two writes it proposes. What the room sees, run by run:

| Run | Agent | Cards it creates |
| --- | --- | --- |
| 1 | `cim_screener` | **banker question**, hard-fail question, 2 write approvals |
| 2 | `teaser_intake` | **1 write approval — it never asks who the banker is** |
| 3 | `cim_screener` | hard-fail question, 2 write approvals — **still no banker question** |

The line to say out loud on run 2: *this is a different agent, on the same deal, acting on
what a person told a different agent a moment ago.* On run 3: *the banker question is gone,
but the hard-fail question came back, because a person's judgement call was recorded as
context, not as settled fact.*

## Act 2 — why it happened (4 min)

Leave Terminal 1 running; it holds the state. In **Terminal 2**:

```sh
uv run sandbox inspect <run-1-id> | jq -r '.feedback[] | "\(.category)/\(.reach)  [\(.status)]  \(.prompt)\n    answer = \(.answer)  by \(.user_id)\n    sig    = \(.signature)"'
```

```
fact/deal  [active]  Which banker should be the deal source?
    answer = {"selected":"contact-a-1"}  by user-a1
    sig    = request_input|entity:contact-a-1,contact-a-2,contact-a-3
judgement/once  [superseded]  Hard fail: kill or override?
    answer = {"selected":"override"}  by user-a1
    sig    = request_input|text:hard fail: kill or override|kill,override
```

(`superseded` is a free bonus to point at: run 3 answered that question again, and the newer
answer replaced the older one — memory renders only the newer.)

Three things to point at: **category** (the classifier decided this on its own), **reach**
(`deal` vs `once` is why one question came back and the other didn't), and **signature**
(entity questions key on record ids, so re-wording the question still matches — and a fourth
banker would not).

Then, what run 3 was actually told:

```sh
uv run sandbox inspect <run-3-id> \
  | jq -r '.run.trace[] | select(.kind=="model") | .input_messages[0].content' \
  | sed -n '/# Memory/,/# Agent:/p' | head -5
```

```
# Memory
Decision for this deal on "Which banker should be the deal source?": contact-a-1 (Avery Lark). Chosen by user-a1 on 2026-09-17. Do not ask this again; act on it, using gated tools for any write.
Context for this deal on "Hard fail: kill or override?": user-a1 chose override (Override) on 2026-09-17. Ask again before acting on it.
```

This is the whole loop on one screen. Note there is **no deal id** in the prompt — memory is
keyed by deal, so the text says "this deal". A test guards that.

## Act 3 — the human decides how far an answer travels (3 min)

Ctrl+C Terminal 1, then:

```sh
uv run sandbox run day2_remember --fake
```

Answer the hard-fail card **with a reach flag**, typed live:

```sh
uv run sandbox answer <hardfail-id> override --remember deal --reason "Board cleared the size breach"
```

Approve the writes. The second run then creates **only the two write-approval cards** — both
questions are gone, because a person said this decision holds for the deal.

Then show the flag being refused where it would be unsafe:

```sh
uv run sandbox answer <a-write-approval-id> approve --remember deal
# {"error": "Reach cannot be set on an approval"}
```

*An approval is a gate, not a preference. You cannot teach the system to stop asking
permission to write.*

## Act 4 — what it refuses to learn (2 min)

```sh
uv run python -m eval.replay sync_failure --n 1 --fake
uv run python -m eval.replay unattended  --n 1 --fake
```

- `sync_failure`: the "retry, exclude or map?" question is asked **every time**. It is a
  runtime failure routed to a person, not a preference — 3 refusals, 0 feedback rows.
- `unattended`: the night agent's cards expire to a safe default with no human. 0 feedback
  rows, 0 memory. *Nobody decided, so there is nothing to learn.*

This is the part of the design worth defending: deciding what **not** to absorb.

## Act 5 — a real model, not the scripted one (3 min)

```sh
SANDBOX_MODEL=gpt-4.1-mini uv run python -m eval.replay day2_repeat --n 1 --output-dir replay-output/live
```

Expect a PASS with the source-contact question asked **once**. Card and write counts vary
between runs — the model writes its own question wording, and the loop does not care,
because entity signatures key on record ids. Show a line from the live report:

```sh
jq -r '.feedback[] | "\(.category)/\(.reach): \(.prompt)"' replay-output/live/day2_repeat-*.json
```

If you only have a minute, skip the live run and read the table in `EVIDENCE.md` §9 instead;
two independent live runs are recorded there.

## The two honest bits to volunteer before anyone asks

1. **A `Context` line says "Ask again before acting on it" — and both live runs ignored it.**
   The model acted on the judgement call without re-asking. Nothing unsafe happened (the
   status write still stopped at its card), but it is the cleanest possible demonstration of
   the design's central line: *a rule that reaches the model is prose, and prose can be
   ignored. A rule that reaches middleware is a guard.* `deal` reach has a guard behind it.
   `once` reach does not. That is a gap, and the fix is to move it into middleware.
2. **The guard can answer a replacement question after a failed write.** Choose `map` at the
   retry card and the agent asks for a *different* contact — same prompt, same options, so
   the same signature — and the guard answers it with the contact that just failed. No
   scenario reaches it and no write escapes approval, but it is wrong. Fix: refuse reuse when
   the preceding tool batch errored.

## If something breaks on stage

| Symptom | Cause | Fix |
| --- | --- | --- |
| `A sandbox session is already running` | previous Terminal 1 still alive | Ctrl+C it |
| `unrecognized arguments: --remember` | stale `cli.py` copy in the venv | `uv sync --reinstall-package rubi-harness-sandbox` |
| `Set OPENAI_API_KEY ... or use --fake` | `.env` lost, or an exported key shadowing it | `env -u OPENAI_API_KEY ...` |
| Live run dies with `finish_reason=length` | reasoning model vs `max_tokens=4096` | use `gpt-4.1-mini`, not `gpt-5-nano` |
| Live model uses different option ids | expected | answer the ids actually printed |
