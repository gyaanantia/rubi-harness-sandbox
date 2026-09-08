FOUNDATION = """You operate on synthetic deals for one firm. Use tools for facts.

Tool approval: call the gated tool directly. Its card is where the user
approves the action; never ask for that approval in chat. Use request_input
for choices. Batch independent questions in one assistant turn.
After a rejected or skipped field choice, drop that field and continue.
A terminal REJECTED retry limit means report the failure without retrying.
Do not invent ids. Never act on another firm's records.
"""


def compose(definition, ctx):
    run = ctx["run"]
    memory = ctx["memory"].search(run.firm_id, run.user_id, run.bindings.get("deal_id"))
    sections = [
        FOUNDATION,
        "# Memory\n" + "\n".join(memory),
        f"# Agent: {definition.name}\n{definition.instructions}",
    ]
    for name in definition.skills:
        skill = ctx["skills"].get(run.firm_id, name)
        sections.append(f"## Skill: {skill.name}\n{skill.body}")
    return "\n\n".join(sections)
