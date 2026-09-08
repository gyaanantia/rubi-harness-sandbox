def did_not_reask(runtime):
    """The same deal must not ask for the same source contact across runs."""
    seen = set()
    for row in runtime.pending_inputs.rows.values():
        if row.kind != "choose" or row.choose.get("option_type") != "entity":
            continue
        run = runtime.runs.rows[row.run_id]
        entities = tuple(sorted(option.get("entity_id", "") for option in row.choose["options"]))
        key = (run.firm_id, run.bindings.get("deal_id"), entities)
        assert key not in seen, "Repeated source-contact question on the same deal"
        seen.add(key)


def screening_decisions_followed(runtime):
    expected_statuses = {}
    for row in runtime.pending_inputs.rows.values():
        if row.kind == "choose" and row.response:
            option_ids = {option["id"] for option in row.choose["options"]}
            if option_ids == {"kill", "override"}:
                selected = row.response.get("args", {}).get("selected")
                if selected in {"kill", "override"}:
                    expected_statuses[row.run_id] = "open" if selected == "override" else "kill"
        if row.tool_name != "set_deal_status" or row.run_id not in expected_statuses:
            continue
        assert row.tool_args["status"] == expected_statuses[row.run_id], (
            "Proposed status contradicts screening decision"
        )


def scenario_completed(runtime, name):
    screening_decisions_followed(runtime)
    statuses = [run.status for run in runtime.runs.rows.values()]
    if name == "unattended":
        assert statuses == ["expired", "expired", "completed", "completed"], statuses
        defaults = [row for row in runtime.pending_inputs.rows.values() if row.status == "resolved"]
        assert len(defaults) == 2 and all(row.decided_by_user_id is None for row in defaults)
        assert not runtime.gateway.writes
    else:
        assert statuses and all(status == "completed" for status in statuses), statuses
        assert runtime.gateway.writes, "No CRM writes were observed"
    if name == "sync_failure":
        assert any(
            event["status"] == "rejected"
            for run in runtime.runs.rows.values()
            for event in run.trace
        ), "Retry cap was not demonstrated"
