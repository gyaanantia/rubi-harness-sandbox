from pathlib import Path

from harness import request_input, tools  # noqa: F401
from harness.runtime import Runtime
from harness.store.gateway import Gateway
from seed.agents import cim_screener, crm_hygiene, teaser_intake
from seed.firms import FIRM_A, FIRM_B


def bootstrap(*, fake=False, **kwargs):
    runtime = Runtime(Gateway(), fake=fake, **kwargs)
    skill_directory = Path(__file__).parent / "skills"
    for firm_id, criteria_file in [(FIRM_A, "screening_a.md"), (FIRM_B, "screening_b.md")]:
        runtime.skills.load(firm_id, skill_directory / criteria_file)
        runtime.skills.load(firm_id, skill_directory / "crm_sync_rules.md")
        for agent in [cim_screener, teaser_intake, crm_hygiene]:
            runtime.definitions.append(agent.definition(firm_id))
    return runtime
