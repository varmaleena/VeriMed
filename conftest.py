"""Keep test scratch data inside this workspace and isolated between concurrent runs."""

import os
from pathlib import Path
from uuid import uuid4


def pytest_configure() -> None:
    if "PYTEST_DEBUG_TEMPROOT" not in os.environ:
        root = Path(__file__).resolve().parent / ".pytest_tmp" / uuid4().hex
        root.mkdir(parents=True)
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(root)
