from collections import defaultdict, deque
from copy import deepcopy

from seed.crm import FIELDS, SECTIONS, STATUSES
from seed.deals import DEALS, DOCUMENTS


class Gateway:
    def __init__(self):
        self.deals = deepcopy(DEALS)
        self.documents = deepcopy(DOCUMENTS)
        self.failures = defaultdict(deque)
        self.writes = []

    def fail_next(self, tool, reason):
        self.failures[tool].append(reason)

    def _check_failure(self, tool):
        if self.failures[tool]:
            raise RuntimeError(self.failures[tool].popleft())

    def deal(self, firm_id, deal_id):
        deal = self.deals.get(deal_id)
        if deal is None or deal["firm_id"] != firm_id:
            raise KeyError("Deal not found")
        return deal

    def read_document(self, firm_id, document_id):
        self._check_failure("read_document")
        document = self.documents.get(document_id)
        if document is None or document["firm_id"] != firm_id:
            raise KeyError("Document not found")
        return document["body"]

    def get_deal_info(self, firm_id, deal_id, sections):
        deal = self.deal(firm_id, deal_id)
        if any(section not in SECTIONS for section in sections):
            return "Invalid section. Valid sections: " + ", ".join(SECTIONS)
        data = {
            "overview": {"name": deal["name"], "status": deal["status"]},
            "financials": {"ebitda_millions": deal["ebitda_millions"]},
            "contacts": deal["contacts"],
            "documents": [deal["document_id"]],
            "crm": deal["fields"],
            "screening": {"geography": deal["geography"], "concentration": deal["concentration"]},
        }
        return deepcopy({section: data[section] for section in sections})

    def list_deal_contacts(self, firm_id, deal_id):
        return deepcopy(self.deal(firm_id, deal_id)["contacts"])

    def list_crm_fields(self, entity):
        if entity != "deal":
            raise ValueError("Only entity=deal is supported")
        return deepcopy(FIELDS)

    def write_crm_field(self, firm_id, deal_id, field, value):
        deal = self.deal(firm_id, deal_id)
        if field not in FIELDS:
            raise ValueError("Unknown CRM field")
        if field == "deal_source_individual":
            if isinstance(value, list):
                if len(value) != 1:
                    raise ValueError("deal_source_individual is single-select")
                value = value[0]
            if value not in {contact["id"] for contact in deal["contacts"]}:
                raise ValueError("Contact is not on this deal")
        elif field == "status" and value not in STATUSES:
            raise ValueError("Unknown deal status")
        elif field == "geography" and (not isinstance(value, str) or not value):
            raise ValueError("Geography requires text")
        self._check_failure("write_crm_field")
        deal["fields"][field] = value
        if field == "status":
            deal["status"] = value
        self.writes.append({"firm_id": firm_id, "deal_id": deal_id, "field": field, "value": value})
        return {"written": True, "field": field, "value": value}

    def set_deal_status(self, firm_id, deal_id, status):
        deal = self.deal(firm_id, deal_id)
        if status not in STATUSES:
            raise ValueError("Unknown deal status")
        self._check_failure("set_deal_status")
        deal["status"] = status
        self.writes.append(
            {"firm_id": firm_id, "deal_id": deal_id, "field": "status", "value": status}
        )
        return {"status": status}

    def snapshot(self):
        return deepcopy({"deals": self.deals, "writes": self.writes})
