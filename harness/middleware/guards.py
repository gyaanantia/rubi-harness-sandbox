"""A rule a definition declares and middleware enforces."""

from harness import learning


def reusable_answer(ctx, call):
    """(answer, feedback_id) when an active deal-reach row matches this exact question."""
    run = ctx["run"]
    row = ctx["feedback"].match(
        run.firm_id,
        run.bindings.get("deal_id"),
        learning.signature(call["name"], call["args"]),
    )
    return (row.answer, row.id) if row else None
