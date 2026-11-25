"""Keep test scratch readable by child processes on restricted Windows build accounts."""
import os

import pytest


if os.environ.get("DFO_TEST_SCRATCH"):
    @pytest.fixture
    def tmp_path():
        from dfo_optimizer.ruleset import adapter_directory
        with adapter_directory(os.environ["DFO_TEST_SCRATCH"]) as directory:
            yield directory
