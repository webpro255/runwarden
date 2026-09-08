"""Config loader tests. Every case here is a fail closed case except the first."""

import json

import pytest

from runprobe.config import SURFACE_TYPES, Config, ConfigError, load, parse


def write_config(tmp_path, data):
    path = tmp_path / "surfaces.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def registered_type(monkeypatch):
    """Register a fake surface type so structural tests can reach a valid config.

    The real registry is empty in Phase 0, so without this every config would
    fail on type resolution and the valid case could not be tested at all.
    """
    monkeypatch.setitem(SURFACE_TYPES, "fake", "tests.fake")
    return "fake"


def test_valid_minimal_config_loads(tmp_path, registered_type):
    path = write_config(tmp_path, {"surfaces": [{"name": "shared_tmp", "type": "fake"}]})
    config = load(path)
    assert isinstance(config, Config)
    assert len(config.surfaces) == 1
    assert config.surfaces[0].name == "shared_tmp"
    assert config.surfaces[0].type == "fake"
    assert config.surfaces[0].params == {}
    assert config.declared == []
    assert config.source == path


def test_valid_config_with_params_and_declared(tmp_path, registered_type):
    path = write_config(
        tmp_path,
        {
            "surfaces": [{"name": "shared_tmp", "type": "fake", "params": {"path": "/tmp"}}],
            "declared": ["shared_tmp:file_content"],
        },
    )
    config = load(path)
    assert config.surfaces[0].params == {"path": "/tmp"}
    assert config.is_declared("shared_tmp", "file_content")
    assert not config.is_declared("shared_tmp", "directory_name")


def test_missing_surfaces_errors():
    with pytest.raises(ConfigError) as exc:
        parse({})
    assert "surfaces" in str(exc.value)


def test_empty_surfaces_errors():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": []})
    assert "must not be empty" in str(exc.value)


def test_surfaces_not_a_list_errors():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": {"name": "shared_tmp"}})
    assert "surfaces must be a list" in str(exc.value)


def test_duplicate_surface_name_errors():
    with pytest.raises(ConfigError) as exc:
        parse(
            {
                "surfaces": [
                    {"name": "shared_tmp", "type": "fake"},
                    {"name": "shared_tmp", "type": "fake"},
                ]
            }
        )
    message = str(exc.value)
    assert "duplicate surface name" in message
    assert "shared_tmp" in message


def test_unknown_top_level_key_errors_and_names_the_key():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "fake"}], "surfacez": []})
    message = str(exc.value)
    assert "unknown key" in message
    assert "surfacez" in message


def test_unknown_key_inside_a_surface_errors_and_names_the_path():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "fake", "parms": {}}]})
    message = str(exc.value)
    assert "unknown key" in message
    assert "parms" in message
    assert "surfaces[0].parms" in message


def test_declared_entry_without_a_colon_errors():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "fake"}], "declared": ["a_file_content"]})
    message = str(exc.value)
    assert "declared[0]" in message
    assert "surface_name:carrier_name" in message


def test_declared_entry_with_two_colons_errors():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "fake"}], "declared": ["a:b:c"]})
    assert "surface_name:carrier_name" in str(exc.value)


def test_declared_entry_naming_an_undefined_surface_errors():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "fake"}], "declared": ["b:file_content"]})
    assert "undefined surface" in str(exc.value)


def test_unknown_surface_type_errors_with_the_type_name():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "s3_bucket"}]})
    message = str(exc.value)
    assert "unknown surface type" in message
    assert "s3_bucket" in message


def test_surface_type_registry_is_empty_in_this_phase():
    assert SURFACE_TYPES == {}


def test_missing_surface_name_errors():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"type": "fake"}]})
    assert "'name'" in str(exc.value)


def test_missing_surface_type_errors():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a"}]})
    assert "'type'" in str(exc.value)


def test_surface_name_must_be_a_string():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": 7, "type": "fake"}]})
    assert "surfaces[0].name must be a string" in str(exc.value)


def test_params_must_be_an_object():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "fake", "params": []}]})
    assert "surfaces[0].params must be an object" in str(exc.value)


def test_root_must_be_an_object():
    with pytest.raises(ConfigError) as exc:
        parse([{"name": "a", "type": "fake"}])
    assert "config root must be an object" in str(exc.value)


def test_structural_errors_are_reported_before_unknown_type():
    """A config with both a typo and an unbuilt adapter reports the typo."""
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "a", "type": "not_built_yet", "parms": {}}]})
    assert "unknown key" in str(exc.value)


def test_missing_file_errors(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load(tmp_path / "does_not_exist.json")
    assert "config file not found" in str(exc.value)


def test_malformed_json_errors(tmp_path):
    path = tmp_path / "surfaces.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load(path)
    assert "not valid JSON" in str(exc.value)
