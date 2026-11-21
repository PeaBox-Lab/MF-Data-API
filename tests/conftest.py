from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(name="fixture")
def fixture_loader():
    """Return a callable that loads a fixture file as text."""

    def load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return load
