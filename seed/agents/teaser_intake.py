from harness.store.definitions import AgentDefinition


def definition(firm_id):
    return AgentDefinition(
        "teaser_intake",
        firm_id,
        1,
        "Teaser Intake",
        "Read the teaser, list contacts and field definitions. Log the deal by writing "
        "deal_source_individual. Ask which banker when the document lists several. "
        "Do nothing else. Drop the field if the user skips or rejects the choice.",
        skills=["crm_sync_rules"],
        tools=["read_document", "list_deal_contacts", "list_crm_fields", "write_crm_field"],
        triggers=["document_received"],
    )
