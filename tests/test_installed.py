"""Distribution acceptance: run from outside the checkout in a fresh wheel environment."""
from array import array
from importlib import import_module, machinery, metadata
from pathlib import Path

import pytest

from dfo_optimizer import _native


@pytest.mark.parametrize("name", ["_native", "_spells", "_gear", "_progression", "_spellbook", "_lifecycle"])
def test_each_native_kernel_is_in_the_installed_distribution(name):
    dist = metadata.distribution("dfo-optimizer")
    path = Path(import_module(f"dfo_optimizer.{name}").__file__).resolve()
    assert any(path.name == name + suffix for suffix in machinery.EXTENSION_SUFFIXES)
    installed = {entry.as_posix(): entry for entry in dist.files}
    assert path == dist.locate_file(installed[f"dfo_optimizer/{path.name}"]).resolve()


def test_installed_platform_extension_does_real_work():
    assert any(_native.__file__.endswith(s) for s in machinery.EXTENSION_SUFFIXES)
    dist = metadata.distribution("dfo-optimizer")
    assert "Root-Is-Purelib: false" in dist.read_text("WHEEL")
    inputs = [array("i", xs) for xs in ([4, 8, 30], [0, 0, 10], [0, 0, -44])]
    report = _native.evaluate_batch(*inputs)
    assert list(report["points"]) == [-8, 0, -12]
    assert report["advancement"][-1] == 0.3
    assert report["rows"] == 3
    assert _native.build_info()["compiler"]
    assert _native.build_info()["flags"]
