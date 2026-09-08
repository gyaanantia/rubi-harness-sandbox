from copy import deepcopy


class PreferenceStore:
    def __init__(self):
        self.rows: dict[tuple[str, str, str | None], dict] = {}

    def get(self, firm_id: str, agent_id: str, user_id: str | None = None):
        return deepcopy(self.rows.get((firm_id, agent_id, user_id), {}))

    def set(self, firm_id: str, agent_id: str, values: dict, user_id: str | None = None):
        self.rows[(firm_id, agent_id, user_id)] = deepcopy(values)
