from typing import Literal

from harness.registry import tool_def


@tool_def("request_input", input_required=True, kind="choose")
async def request_input(
    prompt: str,
    options: list[dict] | None = None,
    kind: Literal["choose", "approve"] = "choose",
    mode: Literal["single", "multi"] = "single",
    option_type: Literal["text", "entity"] = "text",
    allow_other: bool = False,
    safe_default: dict | None = None,
    context: str | None = None,
    action_summary: str | None = None,
    payload: dict | None = None,
) -> str:
    """Ask for one decision and pause until an answer arrives.

    Make one call per question. Emit independent questions together as
    sibling tool calls; they become separate cards in one pause batch.
    Do not combine unrelated decisions into a single question.

    Use choose for a selection. Each option has an id and label, and may
    have a description. Entity options also carry an entity_id.
    Use option_type=entity when selecting a banker or another record.
    Single mode accepts one option id; multi mode accepts a list.

    Set allow_other when a typed answer is useful. Free text comes back
    as other_text. For a free-text-only question, use an empty options list
    and allow_other=True. Prefer offering options whenever possible.

    Use approve for a draft without its own gated tool. Describe it with
    action_summary and payload. For CRM writes and status updates, call
    their dedicated tools directly: those tools already request approval.
    Never wrap a gated tool with another approval question.

    Keep the prompt short. Put supporting details in context.
    A safe_default is an answer object, for example {"selected": "skip"}.
    Provide one only when it is safe to take without a person deciding.
    It must select an offered option, or use permitted free text.
    Defaults apply after the deadline and are attributed to no user.
    Without a usable default, expiration stops the run.
    Never default an irreversible business decision just to keep running.

    Skip, reject or cancel of a field choice means drop that field.
    Do not write the declined value, retry it, or ask again in this run.
    Continue other work and report what was skipped.

    The gate returns the answer as a tool message during a fresh invoke.
    A choose decision bypasses this function's body.
    Approval of a draft only acknowledges that draft; it performs no write.
    The model's last assistant text supplies the card rationale.
    An answer a person marks reusable is stored and can appear in a later
    run's memory; an identical question may be answered from that record.
    """
    return "Draft approved. No side effect was performed."
