"""Distribution acceptance: run from outside the checkout in a fresh wheel environment."""
from array import array
from importlib import machinery, metadata

from dfo_optimizer import _native


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
