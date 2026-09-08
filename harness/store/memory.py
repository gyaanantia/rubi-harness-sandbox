from copy import deepcopy


class MemoryStore:
    def __init__(self):
        self.rows: dict[tuple[str, str | None, str | None], list[str]] = {}

    def put(self, firm_id: str, user_id: str | None, text: str, deal_id: str | None = None):
        self.rows.setdefault((firm_id, user_id, deal_id), []).append(text)

    def search(self, firm_id: str, user_id: str | None, deal_id: str | None = None):
        keys = {(firm_id, user_id, None), (firm_id, user_id, deal_id)}
        return deepcopy([text for key in sorted(keys, key=str) for text in self.rows.get(key, [])])
