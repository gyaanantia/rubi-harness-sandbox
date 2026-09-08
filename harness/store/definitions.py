from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class AgentDefinition:
    agent_id: str
    firm_id: str
    version: int
    name: str
    instructions: str
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    tool_modes: dict[str, Literal["allow", "ask", "block"]] = field(default_factory=dict)
    sub_agents: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class DefinitionStore:
    def __init__(self):
        self.versions: dict[tuple[str, str, int], AgentDefinition] = {}
        self.current: dict[tuple[str, str], int] = {}

    def append(self, definition: AgentDefinition):
        key = (definition.firm_id, definition.agent_id)
        if definition.version <= self.current.get(key, 0):
            raise ValueError("Version must increase")
        self.versions[(*key, definition.version)] = deepcopy(definition)
        self.current[key] = definition.version

    def get(self, firm_id: str, agent_id: str, version: int | None = None):
        key = (firm_id, agent_id)
        return deepcopy(self.versions[(*key, version or self.current[key])])
