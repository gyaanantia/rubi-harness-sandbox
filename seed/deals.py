DEAL_A = "10000000-0000-4000-8000-000000000001"
DEAL_A2 = "10000000-0000-4000-8000-000000000002"
DEAL_B = "10000000-0000-4000-8000-000000000003"
DOCUMENT_A = "20000000-0000-4000-8000-000000000001"
DOCUMENT_A2 = "20000000-0000-4000-8000-000000000002"
DOCUMENT_B = "20000000-0000-4000-8000-000000000003"


def contacts(prefix, names):
    return [
        {
            "id": f"{prefix}-{idx}",
            "name": name,
            "role": "intermediary",
            "banker_firm": "Paper Kite Advisory",
        }
        for idx, name in enumerate(names, 1)
    ]


DEALS = {
    DEAL_A: {
        "firm_id": "firm-a",
        "name": "Mosswheel Components",
        "document_id": DOCUMENT_A,
        "ebitda_millions": 18,
        "geography": "North America",
        "concentration": 0.25,
        "status": "open",
        "fields": {},
        "contacts": contacts("contact-a", ["Avery Lark", "Remy Finch", "Tessa Wren"]),
    },
    DEAL_A2: {
        "firm_id": "firm-a",
        "name": "Cloudspool Packaging",
        "document_id": DOCUMENT_A2,
        "ebitda_millions": 4,
        "geography": "North America",
        "concentration": 0.15,
        "status": "open",
        "fields": {},
        "contacts": contacts("contact-a2", ["Milo Reed", "Nora Vale"]),
    },
    DEAL_B: {
        "firm_id": "firm-b",
        "name": "Sunbutton Logistics",
        "document_id": DOCUMENT_B,
        "ebitda_millions": 18,
        "geography": "North America",
        "concentration": 0.25,
        "status": "open",
        "fields": {},
        "contacts": contacts("contact-b", ["Ellis Fern", "Sage Brook"]),
    },
}

DOCUMENTS = {
    deal["document_id"]: {
        "firm_id": deal["firm_id"],
        "deal_id": deal_id,
        "body": f"# {deal['name']} — CIM / teaser\n"
        f"EBITDA: ${deal['ebitda_millions']} million. "
        f"Geography: {deal['geography']}. "
        f"Largest customer: {deal['concentration']:.0%}.\n"
        "Introduced by " + ", ".join(contact["name"] for contact in deal["contacts"]) + ".",
    }
    for deal_id, deal in DEALS.items()
}
