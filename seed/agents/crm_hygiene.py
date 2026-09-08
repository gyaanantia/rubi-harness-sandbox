from harness.store.definitions import AgentDefinition


def definition(firm_id):
    return AgentDefinition(
        "crm_hygiene",
        firm_id,
        1,
        "CRM Hygiene",
        "Check every supplied open deal and fill missing CRM fields. Read overview, crm, "
        "screening and contacts. Write an unambiguous missing geography directly using "
        "write_crm_field. For ambiguous source contacts, ask request_input with skip as an "
        'option and safe_default={"selected": "skip"}. There is no human present. '
        "If the kickoff limits the task to one field, only process that field.",
        skills=["crm_sync_rules"],
        tools=["get_deal_info", "list_crm_fields", "write_crm_field"],
        triggers=["cron"],
    )
