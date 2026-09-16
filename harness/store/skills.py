from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Skill:
    name: str
    frontmatter: dict
    body: str
    version: int


class SkillStore:
    def __init__(self):
        self.rows: dict[tuple[str, str], Skill] = {}
        self.versions: dict[tuple[str, str, int], Skill] = {}

    def load(self, firm_id: str, path: Path):
        _, header, body = path.read_text().split("---", 2)
        frontmatter = yaml.safe_load(header)
        skill = Skill(frontmatter["name"], frontmatter, body.strip(), frontmatter["version"])
        return self._register(firm_id, skill)

    def append(self, firm_id: str, name: str, text: str):
        """PLAN 10.8: a new version whose body is the old body, a blank line, then text."""
        current = self.rows[(firm_id, name)]
        version = current.version + 1
        return self._register(
            firm_id,
            Skill(
                current.name,
                {**current.frontmatter, "version": version},
                f"{current.body}\n\n{text}",
                version,
            ),
        )

    def _register(self, firm_id: str, skill: Skill):
        self.versions[(firm_id, skill.name, skill.version)] = skill
        self.rows[(firm_id, skill.name)] = skill
        return skill

    def get(self, firm_id: str, name: str, version: int | None = None):
        if version is None:
            return deepcopy(self.rows[(firm_id, name)])
        return deepcopy(self.versions[(firm_id, name, version)])
