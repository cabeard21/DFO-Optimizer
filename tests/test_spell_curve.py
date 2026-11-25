import json
from pathlib import Path

import pytest

from dfo_optimizer.spell_curve import evaluate_spell_curve
from dfo_optimizer.spells import evaluate_spell


def fixed():
    return json.loads((Path(__file__).parents[1] / "examples/spell-fixed.json").read_text())


@pytest.mark.parametrize("axis,values", [
    ("level", [1, 10, 45]), ("destruction_live", [10, 75, 103]),
    ("destruction_trained", [75, 100, 125]),
])
def test_curve_matches_individual_native_evaluations(axis, values):
    base = fixed()
    req = {**base, "curve":{"axis":axis, "values":values}}
    result = evaluate_spell_curve(req)
    assert result["status"] == "evaluated" and result["points_checked"] == len(values)
    for point, value in zip(result["candidates"], values, strict=True):
        caster = {**base["caster"], axis:value}
        expected = evaluate_spell({**base, "caster":caster})["candidates"][0]["metrics"]
        assert point[axis] == value and point["metrics"] == expected
    assert req["caster"] == fixed()["caster"]


def test_curve_rejects_mislabeled_duplicate_or_out_of_range_axis_values():
    for axis, values in [("spell_power",[1]), ("level",[1,1]), ("level",[46]), ("destruction_trained",[True])]:
        with pytest.raises(ValueError):
            evaluate_spell_curve({**fixed(), "curve":{"axis":axis, "values":values}})


def test_curve_does_not_assume_an_unknown_observation_or_charge_an_unaffordable_spell():
    base = fixed()
    req = {**base,"caster":{**base["caster"],"current_sp":0},"curve":{"axis":"level","values":[10]}}
    row = evaluate_spell_curve(req)["candidates"][0]["metrics"]
    assert row["damage_per_sp"] is None and row["actual_sp_charged"] == 0
    result = evaluate_spell_curve({**req,"caster":{**req["caster"],"destruction_trained":None}})
    assert result["status"] == "unsupported" and result["candidates"] == []
