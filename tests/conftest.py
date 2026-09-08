"""Shared test fixtures.

FakeSurface exists so that config tests can reach a valid config without
depending on a real adapter. Config validation and adapter behaviour are
separate concerns and the tests keep them separate.
"""

import pytest

from runprobe.config import SURFACE_TYPES
from runprobe.surfaces import Carrier, Recovered, Surface, validate_param_keys


class FakeSurface(Surface):
    """A surface that plants nothing and recovers nothing."""

    type_name = "fake"

    @classmethod
    def validate_params(cls, params, path="params"):
        validate_param_keys(params, {"path": str}, path)

    @classmethod
    def carriers(cls):
        return [
            Carrier("file_content", "durable", "bytes of a file"),
            Carrier("directory_name", "durable", "name of a directory"),
        ]

    def plant(self, nonce, run):
        return None

    def recover(self, run):
        return [Recovered(c.name, False, "fake surface recovers nothing") for c in self.carriers()]


@pytest.fixture
def registered_type(monkeypatch):
    """Register FakeSurface as type 'fake' for the duration of one test."""
    monkeypatch.setitem(SURFACE_TYPES, "fake", FakeSurface)
    return "fake"
