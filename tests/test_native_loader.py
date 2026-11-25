import pytest

from dfo_optimizer import native


def test_missing_extension_explains_how_to_install(monkeypatch):
    def missing(name, package):
        raise ImportError("cannot load shared library")

    monkeypatch.setattr(native, "import_module", missing)
    with pytest.raises(RuntimeError, match="wheel"):
        native.require_native()
