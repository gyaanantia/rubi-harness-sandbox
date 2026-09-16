from harness.store.definitions import AgentDefinition


def definition(firm_id):
    return AgentDefinition(
        "cim_screener",
        firm_id,
        1,
        "CIM Screener",
        "Read the document, contacts and CRM fields. Screen against the attached criteria. "
        "On a hard fail ask kill/override. If several bankers introduced the deal, ask which "
        "one to sync into deal_source_individual. Emit those two questions together. "
        "Then call write_crm_field and set_deal_status with the decisions. "
        "If a CRM write fails, ask retry/exclude/map; retry only when selected. "
        "After a terminal retry rejection, report the failure and finish.",
        skills=["screening_criteria", "crm_sync_rules"],
        tools=[
            "read_document",
            "get_deal_info",
            "list_deal_contacts",
            "list_crm_fields",
            "write_crm_field",
            "set_deal_status",
        ],
        tool_modes={"write_crm_field": "ask", "set_deal_status": "ask"},
        guards=["reuse_answers"],
        triggers=["document_received"],
    )
