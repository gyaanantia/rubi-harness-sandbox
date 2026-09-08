from seed.deals import DEAL_A, DOCUMENT_A


async def start(
    runtime,
    agent_id,
    *,
    deal_id=DEAL_A,
    document_id=DOCUMENT_A,
    firm_id="firm-a",
    user="user-a1",
    task="Screen and update the CRM.",
):
    definition = runtime.definitions.get(firm_id, agent_id)
    kickoff = f"Document received (document_id: {document_id}, deal_id: {deal_id}). {task}"
    return await runtime.run(
        definition,
        kickoff,
        {"deal_id": deal_id, "document_id": document_id, "trigger": "document_received"},
        user,
    )


async def auto_answer(runtime, result):
    while result.get("paused"):
        run = runtime.runs.rows[result["run_id"]]
        for row in runtime.pending(run.id):
            if row.kind == "approve":
                response = {"action": "approve"}
            else:
                options = row.choose["options"]
                option_ids = [option["id"] for option in options]
                selected = next(
                    (option for option in ["override", "retry", "skip"] if option in option_ids),
                    option_ids[0] if option_ids else None,
                )
                arguments = (
                    {"selected": selected} if selected else {"other_text": "Synthetic answer"}
                )
                if row.choose["mode"] == "multi" and selected:
                    arguments["selected"] = [selected]
                response = {"action": "choose", "args": arguments}
            runtime.pending_inputs.respond(
                row.id, response, firm_id=run.firm_id, user_id=run.user_id
            )
        result = await runtime.resume(run.id, firm_id=run.firm_id)
    if "error" in result:
        raise RuntimeError(result["error"])
    return result
