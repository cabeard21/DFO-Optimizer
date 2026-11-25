import pytest

from dfo_optimizer.build_baselines import baseline_catalog, resolve_family_baseline
from dfo_optimizer.ruleset import load_ruleset


def test_validated_comparison_baselines_and_provenance():
    bundle = load_ruleset()
    rows = baseline_catalog(bundle)["baselines"]
    assert len(rows) == 16 and len(set(row["id"] for row in rows)) == 16
    caster = resolve_family_baseline("m1-breton-caster", bundle)
    elf = resolve_family_baseline("comparison-high-elf-caster", bundle)
    assert caster["class"] == elf["class"] and (caster["race_id"], elf["race_id"]) == (1, 5)
    martial = [r for r in rows if r["id"].startswith("dhargo/")]
    assert len(martial) == 14
    assert all(r["create_legal"] and r["difficulty_points"] == -12 and r["source_sha256"] for r in martial)
    assert all(r["profile_errors"] for r in martial)
    with pytest.raises(ValueError, match="Unknown"):
        resolve_family_baseline("unknown-historical-caster", bundle)
