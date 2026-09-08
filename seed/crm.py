SECTIONS = ["overview", "financials", "contacts", "documents", "crm", "screening"]
STATUSES = ["open", "qualified", "hold", "kill", "decline"]
FIELDS = {
    "deal_source_individual": {"type": "single_select", "entity": "contact"},
    "geography": {"type": "text"},
    "status": {"type": "enum", "options": STATUSES},
}
