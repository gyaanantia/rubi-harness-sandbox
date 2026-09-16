"""Turn answered request_input cards into feedback rows, memory lines and proposals."""

from copy import deepcopy

from harness.middleware.trace import record
from harness.store.feedback import Feedback

FINISHED = {"success", "error"}


def normalised(text):
    return " ".join((text or "").split()).lower().rstrip(".?!,;:")


def signature(tool_name, args):
    """Identify "the same question" across runs, from the raw tool arguments."""
    options = args.get("options") or []
    entity_ids = sorted(option["entity_id"] for option in options if option.get("entity_id"))
    if entity_ids:
        return f"{tool_name}|entity:" + ",".join(entity_ids)
    prompt = normalised(args.get("prompt"))
    if not options:
        return f"{tool_name}|free:{prompt}"
    return f"{tool_name}|text:{prompt}|" + ",".join(sorted(option["id"] for option in options))


def selections(row):
    selected = (row.response or {}).get("args", {}).get("selected")
    if selected is None:
        return []
    return selected if isinstance(selected, list) else [selected]


def other_text(row):
    return (row.response or {}).get("args", {}).get("other_text")


def answer_of(row):
    selected = (row.response or {}).get("args", {}).get("selected")
    return {"selected": selected} if selected is not None else {"other_text": other_text(row)}


def shape(row):
    """The category a row's answer would carry, or None when it carries no answer."""
    if row.response is None or row.response.get("action") != "choose":
        return None
    chosen = selections(row)
    if not chosen:
        return "free_text" if other_text(row) else None
    options = (row.choose or {}).get("options") or []
    # Entity ids, not option_type, are what did_not_reask and the signature key on.
    if any(option.get("entity_id") for option in options):
        return "fact"
    return "judgement"


def is_recovery(run, pending_id):
    """PLAN 10.3: an ask that follows a failed tool call is failure recovery.

    The plan reads the single nearest finished tool event, assuming the retry question
    follows the failed write directly. It does not: a failed write and a successful
    sibling land in one batch, and the sibling finishes last. So the whole tool batch
    before the ask is read, and any error in it makes the ask recovery.
    """
    gate = next(
        (
            index
            for index, event in enumerate(run.trace)
            if event["kind"] == "gate" and pending_id in event.get("pending_ids", [])
        ),
        None,
    )
    if gate is None:
        return False
    statuses = []
    for event in reversed(run.trace[:gate]):
        if event["kind"] == "model":
            continue  # The model turn that produced the ask sits between batch and gate.
        if event["kind"] != "tool":
            break  # A gate or decision event ends the batch this ask followed.
        if event.get("tool_call_id") and event["status"] in FINISHED:
            statuses.append(event["status"])
    return "error" in statuses


def refusal(run, row):
    """The reason this row teaches nothing, or None when it may be stored."""
    if row.kind == "approve":
        return "approval"
    if shape(row) is None:
        return "declined"
    if row.decided_by_user_id is None:
        return "default"
    if is_recovery(run, row.id):
        return "recovery"
    if row.response.get("remember") == "none":
        return "opted_out"
    return None


def reach_of(row, category):
    remember = row.response.get("remember")
    if remember in {"deal", "firm"}:
        return remember
    return "deal" if category == "fact" else "once"


def labels(row):
    chosen = set(selections(row))
    options = (row.choose or {}).get("options") or []
    names = [option["label"] for option in options if option["id"] in chosen]
    return ", ".join(names) or None


def store(ctx, row, category):
    run = ctx["run"]
    reach = reach_of(row, category)
    stored = ctx["feedback"].add(
        Feedback(
            firm_id=run.firm_id,
            agent_id=run.agent_id,
            run_id=run.id,
            pending_id=row.id,
            user_id=row.decided_by_user_id,
            deal_id=run.bindings.get("deal_id"),
            signature=signature(row.tool_name, row.tool_args),
            category=category,
            answer=deepcopy(answer_of(row)),
            prompt=(row.choose or {}).get("prompt", ""),
            label=labels(row),
            reason=row.response.get("reason"),
            reach=reach,
        )
    )
    if reach == "firm":
        definition = ctx["definition"]
        target = definition.skills[0] if definition.skills else definition.agent_id
        ctx["proposals"].create(
            firm_id=run.firm_id,
            feedback_id=stored.id,
            target=target,
            proposed_text=proposed_text(stored),
        )
    return stored


def absorb(ctx):
    """PLAN 10.7: learn from a completed run's answered cards, then re-render memory."""
    run = ctx["run"]
    for row in ctx["pending_inputs"].for_run(run.id):
        reason = refusal(run, row)
        category = "approval" if row.kind == "approve" else shape(row)
        stored = None if reason else store(ctx, row, category)
        record(
            ctx,
            "learning",
            tool=row.tool_name,
            status="refused" if reason else "stored",
            category=category,
            reach=stored.reach if stored else None,
            pending_id=row.id,
            feedback_id=stored.id if stored else None,
            reason=reason,
        )
    rebuild(ctx["feedback"], ctx["memory"], run.firm_id, run.bindings.get("deal_id"))


def rebuild(feedback, memory, firm_id, deal_id):
    """PLAN 10.2: re-render both firm-wide memory keys from the active rows."""
    if deal_id is not None:
        memory.replace(
            firm_id,
            None,
            deal_id,
            [
                deal_line(row)
                for row in feedback.active(firm_id, deal_id=deal_id)
                if row.reach in {"deal", "once"}
            ],
        )
    memory.replace(
        firm_id,
        None,
        None,
        [firm_line(row) for row in feedback.active(firm_id, reach="firm")],
    )


def date_of(row):
    return row.created_at.date().isoformat()


def chosen_text(row):
    selected = row.answer.get("selected")
    if selected is None:
        return row.answer.get("other_text")
    return ", ".join(selected) if isinstance(selected, list) else selected


def because(row):
    return f", reason: {row.reason}" if row.reason else ""


def deal_line(row):
    return context_line(row) if row.reach == "once" else decision_line(row)


def decision_line(row):
    subject = f"{chosen_text(row)} ({row.label})" if row.label else chosen_text(row)
    return (
        f'Decision for this deal on "{row.prompt}": {subject}. '
        f"Chosen by {row.user_id} on {date_of(row)}{because(row)}. "
        "Do not ask this again; act on it, using gated tools for any write."
    )


def context_line(row):
    if row.category == "free_text":
        return (
            f'Context for this deal on "{row.prompt}": {row.user_id} '
            f'wrote "{chosen_text(row)}" on {date_of(row)}. Ask again before acting on it.'
        )
    subject = f"{chosen_text(row)} ({row.label})" if row.label else chosen_text(row)
    return (
        f'Context for this deal on "{row.prompt}": {row.user_id} chose {subject} '
        f"on {date_of(row)}{because(row)}. Ask again before acting on it."
    )


def firm_line(row):
    return (
        f"Suggested for all deals by {row.user_id} on {date_of(row)}, not yet accepted: "
        f'on "{row.prompt}", {chosen_text(row)}{because(row)}. Ask as usual.'
    )


def proposed_text(row):
    reason = f" (reason: {row.reason})" if row.reason else ""
    return (
        f"{row.user_id} on {date_of(row)}: for all deals, "
        f'on "{row.prompt}", choose {chosen_text(row)}{reason}.'
    )
