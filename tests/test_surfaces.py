"""Adapter contract tests: carriers, registration, and param validation.

These test the contract itself, with fake adapters. Real adapter behaviour is
tested in test_filesystem.py and test_git_remote.py.
"""

import json

import pytest

from runwarden.config import SURFACE_TYPES, ConfigError, parse
from runwarden.report import PERSISTENCE_CLASSES
from runwarden.surfaces import Carrier, Recovered, Surface, register, validate_param_keys


@pytest.fixture
def clean_registry(monkeypatch):
    """Give a test its own copy of the registry so register() cannot leak."""
    monkeypatch.setattr("runwarden.config.SURFACE_TYPES", dict(SURFACE_TYPES))
    return None


def make_adapter(type_name, allowed=None, carrier_names=("only_carrier",)):
    """Build a throwaway adapter class with the given type name and carriers."""
    allowed_keys = allowed or {}

    class Adapter(Surface):
        pass

    Adapter.type_name = type_name
    Adapter.__name__ = f"Adapter_{type_name}"

    @classmethod
    def _validate_params(cls, params, path="params"):
        validate_param_keys(params, allowed_keys, path)

    @classmethod
    def _carriers(cls):
        return [Carrier(name, "durable", f"the {name} channel") for name in carrier_names]

    Adapter.validate_params = _validate_params
    Adapter.carriers = _carriers
    Adapter.plant = lambda self, nonce, run: None
    Adapter.recover = lambda self, run: []
    # __abstractmethods__ is computed when the class body closes, so the
    # attributes assigned above have to be announced explicitly.
    Adapter.__abstractmethods__ = frozenset()
    return Adapter


def test_carrier_rejects_an_unknown_persistence_class():
    with pytest.raises(ValueError, match="persistence"):
        Carrier("branch_name", "forever", "a branch name")


def test_carrier_accepts_every_declared_persistence_class():
    for persistence in PERSISTENCE_CLASSES:
        assert Carrier("c", persistence, "d").persistence == persistence


def test_recovered_defaults_to_supported():
    assert Recovered("file_name", False, "not found").supported is True


def test_recovered_can_report_unsupported():
    """PASS and SKIPPED must stay distinguishable, otherwise the probe overclaims."""
    result = Recovered("xattr", False, "filesystem does not support xattrs", supported=False)
    assert result.supported is False
    assert result.found is False


def test_surface_cannot_be_instantiated_without_the_required_methods(tmp_path):
    class Incomplete(Surface):
        type_name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete("a", {}, tmp_path)


def test_setup_and_cleanup_default_to_doing_nothing(tmp_path):
    adapter = make_adapter("noop")("a", {}, tmp_path)
    assert adapter.setup() is None
    assert adapter.cleanup() is None


def test_surface_keeps_its_name_params_and_work_dir(tmp_path):
    adapter = make_adapter("keeps", allowed={"path": str})("shared", {"path": "/tmp"}, tmp_path)
    assert adapter.name == "shared"
    assert adapter.params == {"path": "/tmp"}
    assert adapter.work == tmp_path


def test_surface_copies_params_rather_than_aliasing_them(tmp_path):
    params = {"path": "/tmp"}
    adapter = make_adapter("copies", allowed={"path": str})("shared", params, tmp_path)
    params["path"] = "/elsewhere"
    assert adapter.params == {"path": "/tmp"}


def test_register_inserts_the_class_into_the_registry(clean_registry):
    adapter = register(make_adapter("registered_here"))
    from runwarden.config import SURFACE_TYPES as live

    assert live["registered_here"] is adapter


def test_register_rejects_a_class_without_a_type_name(clean_registry):
    class Nameless(Surface):
        type_name = ""

        @classmethod
        def carriers(cls):
            return []

        def plant(self, nonce, run):
            return None

        def recover(self, run):
            return []

    with pytest.raises(ValueError, match="type_name"):
        register(Nameless)


def test_register_rejects_a_duplicate_type_name(clean_registry):
    register(make_adapter("taken"))
    with pytest.raises(ValueError, match="already registered"):
        register(make_adapter("taken"))


def test_register_is_idempotent_for_the_same_class(clean_registry):
    adapter = make_adapter("same")
    register(adapter)
    assert register(adapter) is adapter


def test_validate_param_keys_rejects_an_unknown_key_and_names_the_path():
    with pytest.raises(ConfigError) as exc:
        validate_param_keys({"pth": "/tmp"}, {"path": str}, "surfaces[0].params")
    message = str(exc.value)
    assert "unknown key" in message
    assert "surfaces[0].params.pth" in message
    assert "allowed keys here: path" in message


def test_validate_param_keys_reports_when_no_params_are_accepted():
    with pytest.raises(ConfigError) as exc:
        validate_param_keys({"path": "/tmp"}, {}, "surfaces[0].params")
    assert "no params are accepted here" in str(exc.value)


def test_validate_param_keys_rejects_a_wrong_type():
    with pytest.raises(ConfigError) as exc:
        validate_param_keys({"path": 7}, {"path": str}, "surfaces[0].params")
    assert "surfaces[0].params.path must be a string, got int" in str(exc.value)


def test_validate_param_keys_does_not_accept_a_bool_as_an_int():
    """bool subclasses int, so an isinstance check alone would let true through."""
    with pytest.raises(ConfigError) as exc:
        validate_param_keys({"count": True}, {"count": int}, "surfaces[0].params")
    assert "got bool" in str(exc.value)


def test_validate_param_keys_accepts_a_bool_where_a_bool_is_wanted():
    validate_param_keys({"check_xattr": False}, {"check_xattr": bool}, "surfaces[0].params")


def test_config_parse_calls_the_adapter_param_validator(monkeypatch):
    monkeypatch.setitem(SURFACE_TYPES, "strict", make_adapter("strict", allowed={"path": str}))
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "strict", "params": {"nope": 1}}]})
    assert "surfaces[0].params.nope" in str(exc.value)


def test_config_parse_accepts_valid_params(monkeypatch):
    monkeypatch.setitem(SURFACE_TYPES, "strict", make_adapter("strict", allowed={"path": str}))
    config = parse({"surfaces": [{"name": "a", "type": "strict", "params": {"path": "/tmp"}}]})
    assert config.surfaces[0].params == {"path": "/tmp"}


def test_declared_carrier_that_does_not_exist_is_a_config_error(monkeypatch):
    monkeypatch.setitem(SURFACE_TYPES, "two", make_adapter("two", carrier_names=("x", "y")))
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "two"}], "declared": ["a:z"]})
    message = str(exc.value)
    assert "declared[0]" in message
    assert "carriers on this surface: x, y" in message


def test_declared_carrier_that_exists_is_accepted(monkeypatch):
    monkeypatch.setitem(SURFACE_TYPES, "two", make_adapter("two", carrier_names=("x", "y")))
    config = parse({"surfaces": [{"name": "a", "type": "two"}], "declared": ["a:y"]})
    assert config.is_declared("a", "y")


def test_declared_surface_half_is_reported_before_the_type_resolves():
    """An undefined surface name is a typo worth reporting on its own terms."""
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "unbuilt"}], "declared": ["b:x"]})
    assert "undefined surface" in str(exc.value)


def test_carriers_is_usable_without_constructing_the_adapter():
    """The declared check runs at config load, before anything is built."""
    adapter = make_adapter("classlevel", carrier_names=("x",))
    assert [c.name for c in adapter.carriers()] == ["x"]


def test_carrier_descriptions_are_json_serializable():
    adapter = make_adapter("serial", carrier_names=("x",))
    payload = [vars(c) for c in adapter.carriers()]
    assert json.loads(json.dumps(payload))[0]["name"] == "x"
