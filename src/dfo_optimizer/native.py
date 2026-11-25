"""Load the required platform extension at the computation boundary."""
from importlib import import_module
from types import ModuleType


def require_native() -> ModuleType:
    try:
        return import_module("._native", __package__)
    except ImportError as exc:
        raise RuntimeError(
            "DFO requires its native extension. Install a dfo-optimizer wheel "
            "for your Python and platform, or run 'python -m pip install .' "
            "from the repository with a C++17 compiler."
        ) from exc
