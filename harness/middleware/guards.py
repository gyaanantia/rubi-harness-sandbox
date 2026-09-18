"""A rule a definition declares and middleware enforces."""

from harness import learning


def reusable_answer(ctx, call):
    """(answer, feedback_id) when an active deal-reach row matches this exact question.

    An ask that follows a failed tool call is recovery: the person is being asked for
    a different answer, so the stored one must not be handed back. Same rule as the
    learning step, applied before the card exists instead of after the run.
    """
    run = ctx["run"]
    if learning.follows_error(run.trace):
        return None
    row = ctx["feedback"].match(
        run.firm_id,
        run.bindings.get("deal_id"),
        learning.signature(call["name"], call["args"]),
    )
    return (row.answer, row.id) if row else None
