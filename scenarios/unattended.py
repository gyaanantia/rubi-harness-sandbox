from datetime import timedelta

from harness.store.pending_inputs import utc_now
from seed.deals import DEAL_A, DEAL_A2


async def run(runtime, answer):
    results = []
    definition = runtime.definitions.get("firm-a", "crm_hygiene")
    for field in ["geography", "deal_source_individual"]:
        # Exercise each branch on every open deal in firm A.
        for deal_id in [DEAL_A, DEAL_A2]:
            result = await runtime.run(
                definition,
                f"03:00 cron (deal_id: {deal_id}). Fill only {field} if missing.",
                {"deal_id": deal_id, "trigger": "cron", "ts": "03:00"},
                user=None,
            )
            if "error" in result:
                raise RuntimeError(result["error"])
            if not result.get("paused"):
                raise AssertionError("Unattended scenario must pause before expiry")
            await runtime.pending_inputs.sweep_expired(
                utc_now() + runtime.ttl + timedelta(seconds=1), runtime
            )
            results.append(
                {"run_id": result["run_id"], "status": runtime.runs.rows[result["run_id"]].status}
            )
    return results
