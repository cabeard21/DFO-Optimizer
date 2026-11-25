"""Find bundled examples and comparison observations in source and wheel installs."""
from pathlib import Path
import sysconfig


def shared_data(group):
    root = Path(__file__).resolve().parents[2]
    if (root / "DFO_Spellcasting_Optimizer_Codex_Handoff.md").is_file():
        return root / ("tests/fixtures/dhargo" if group == "baselines" else group)
    return Path(sysconfig.get_path("data")) / "share" / "dfo-optimizer" / group
