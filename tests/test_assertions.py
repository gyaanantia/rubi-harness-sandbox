from types import SimpleNamespace

import pytest

from eval.assertions import did_not_reask


def feedback_runtime(option_type, options):
    first_run = SimpleNamespace(firm_id="firm-a", bindings={"deal_id": "deal-a"})
    second_run = SimpleNamespace(firm_id="firm-a", bindings={"deal_id": "deal-a"})
    first_row = SimpleNamespace(
        kind="choose",
        run_id="first",
        choose={"option_type": "entity", "options": options},
    )
    second_row = SimpleNamespace(
        kind="choose",
        run_id="second",
        choose={"option_type": option_type, "options": list(reversed(options))},
    )
    return SimpleNamespace(
        runs=SimpleNamespace(rows={"first": first_run, "second": second_run}),
        pending_inputs=SimpleNamespace(rows={"first": first_row, "second": second_row}),
    )


@pytest.mark.parametrize("option_type", ["entity", "text"])
def test_repeat_detection_uses_entity_ids_regardless_of_option_type(option_type):
    runtime = feedback_runtime(
        option_type,
        [
            {"id": "one", "label": "First contact", "entity_id": "contact-a-1"},
            {"id": "two", "label": "Second contact", "entity_id": "contact-a-2"},
        ],
    )
    with pytest.raises(AssertionError, match="Repeated source-contact"):
        did_not_reask(runtime)


def test_plain_text_choices_are_not_treated_as_entity_choices():
    runtime = feedback_runtime("text", [{"id": "skip", "label": "Skip"}])
    runtime.pending_inputs.rows["first"].choose["option_type"] = "text"
    did_not_reask(runtime)
