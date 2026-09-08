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

    def load(self, firm_id: str, path: Path):
        _, header, body = path.read_text().split("---", 2)
        frontmatter = yaml.safe_load(header)
        skill = Skill(frontmatter["name"], frontmatter, body.strip(), frontmatter["version"])
        self.rows[(firm_id, skill.name)] = skill

    def get(self, firm_id: str, name: str):
        return deepcopy(self.rows[(firm_id, name)])
