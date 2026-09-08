"""http_cache adapter tests.

Each carrier is checked on its own, and the plant is inspected in the store
directly, so that a name carrier can be shown to be recoverable without any
body ever being read. A single test asserting "four FAILs" would pass even if
every carrier were really found by downloading the same artifact.

Reading the store directly is allowed here and nowhere else. The adapter itself
recovers over HTTP, and one test below proves that by looking at what the
server was actually asked.
"""

import json

import pytest

from runprobe.config import ConfigError, parse
from runprobe.probe import run_probe
from runprobe.run_context import make_pair
from runprobe.surfaces._cache_server import INDEX_PATH, LOOPBACK
from runprobe.surfaces.http_cache import (
    BOARD_PREFIX,
    KEY_PREFIX,
    MAILBOX_PATH,
    MISS_PREFIX,
    PROP_NAME,
    HttpCacheSurface,
)

NONCE = "0123456789abcdef"


@pytest.fixture
def plant():
    """Build a surface, start its server, run the plant, and always clean up."""
    made = []

    def build(tmp_path, params=None):
        work = tmp_path / "work"
        run_a, run_b = make_pair(work)
        surface = HttpCacheSurface("cache", params or {}, work / "surface")
        made.append(surface)
        surface.setup()
        surface.plant(NONCE, run_a)
        return surface, run_b

    yield build

    for surface in made:
        surface.cleanup()


@pytest.fixture
def recovered(plant):
    def build(tmp_path, params=None):
        surface, run_b = plant(tmp_path, params)
        return surface, {r.carrier: r for r in surface.recover(run_b)}

    return build


def probe_http_cache(tmp_path, params=None, declared=()):
    surface = {"name": "cache", "type": "http_cache"}
    if params:
        surface["params"] = params
    config = parse({"surfaces": [surface], "declared": list(declared)})
    report = run_probe(config, tmp_path / "work")
    return report, {f.carrier: f for f in report.findings}


def test_the_adapter_declares_four_durable_carriers():
    names = [c.name for c in HttpCacheSurface.carriers()]
    assert names == ["cache_key", "negative_lookup", "mkcol_dir", "property_field"]
    assert all(c.persistence == "durable" for c in HttpCacheSurface.carriers())


def test_the_surface_is_reachable_only_on_loopback(tmp_path, plant):
    surface, _ = plant(tmp_path)
    assert surface.base_url.startswith(f"http://{LOOPBACK}:")
    assert surface.server.bound_host == LOOPBACK


def test_cache_key_is_planted_as_a_name_with_an_innocuous_body(tmp_path, plant):
    """The name channel has to be provable without any content read at all."""
    surface, _ = plant(tmp_path)
    path = KEY_PREFIX + NONCE
    entry = surface.server.store.entries[path]
    assert entry.status == 200
    assert NONCE not in entry.content.decode()


def test_the_negative_lookup_is_stored_as_a_cached_404_with_no_body(tmp_path, plant):
    """Nothing was written. Asking for the name is what stored the name."""
    surface, _ = plant(tmp_path)
    entry = surface.server.store.entries[MISS_PREFIX + NONCE]
    assert entry.status == 404
    assert entry.content == b""
    assert ("PUT", MISS_PREFIX + NONCE) not in surface.server.store.requests


def test_mkcol_plants_a_collection_and_not_an_artifact(tmp_path, plant):
    surface, _ = plant(tmp_path)
    path = next(p for p in surface.server.store.entries if p.startswith(BOARD_PREFIX))
    entry = surface.server.store.entries[path]
    assert NONCE in path
    assert entry.collection is True
    assert entry.content == b""


def test_the_property_is_planted_on_an_entry_whose_name_says_nothing(tmp_path, plant):
    surface, _ = plant(tmp_path)
    entry = surface.server.store.entries[MAILBOX_PATH]
    assert NONCE not in MAILBOX_PATH
    assert NONCE in entry.properties[PROP_NAME]


def test_cache_key_is_recovered_from_the_listing(tmp_path, recovered):
    _, results = recovered(tmp_path)
    assert results["cache_key"].found is True
    assert KEY_PREFIX + NONCE in results["cache_key"].detail


def test_negative_lookup_is_recovered_and_reported_as_a_cached_404(tmp_path, recovered):
    """The status is the point of this carrier, so the detail has to say it."""
    _, results = recovered(tmp_path)
    result = results["negative_lookup"]
    assert result.found is True
    assert MISS_PREFIX + NONCE in result.detail
    assert "cached 404" in result.detail
    assert "not a stored artifact" in result.detail


def test_mkcol_dir_is_recovered_from_the_collection_name(tmp_path, recovered):
    _, results = recovered(tmp_path)
    assert results["mkcol_dir"].found is True
    assert "MKCOL" in results["mkcol_dir"].detail
    assert NONCE in results["mkcol_dir"].detail


def test_property_field_is_recovered_from_the_index_metadata(tmp_path, recovered):
    _, results = recovered(tmp_path)
    result = results["property_field"]
    assert result.found is True
    assert MAILBOX_PATH in result.detail
    assert f"{PROP_NAME}=" in result.detail


def test_every_carrier_reports_a_result_exactly_once(tmp_path, plant):
    surface, run_b = plant(tmp_path)
    results = surface.recover(run_b)
    assert [r.carrier for r in results] == [c.name for c in HttpCacheSurface.carriers()]
    assert all(r.supported for r in results)


def test_a_run_that_planted_nothing_recovers_nothing(tmp_path):
    """Guard against a recover that reports found for reasons of its own."""
    work = tmp_path / "work"
    _, run_b = make_pair(work)
    surface = HttpCacheSurface("cache", {}, work / "surface")
    surface.setup()
    try:
        results = {r.carrier: r for r in surface.recover(run_b)}
    finally:
        surface.cleanup()
    assert all(r.found is False for r in results.values())


def test_recovery_goes_over_http_and_reads_the_index(tmp_path, plant):
    """Run B's only contact with the surface is a request the server saw."""
    surface, run_b = plant(tmp_path)
    before = surface.server.store.request_count()
    surface.recover(run_b)
    assert (("GET", INDEX_PATH)) in surface.server.store.requests
    assert surface.server.store.request_count() > before


def test_recovery_downloads_bodies_only_when_content_reads_is_on(tmp_path, plant):
    surface, run_b = plant(tmp_path, {"content_reads": False})
    surface.recover(run_b)
    fetched = [path for method, path in surface.server.store.requests if method == "GET"]
    assert INDEX_PATH in fetched
    assert KEY_PREFIX + NONCE not in fetched[fetched.index(INDEX_PATH) :]


def test_all_four_carriers_are_found_with_content_reads_off(tmp_path, recovered):
    """The reason this surface is dangerous: blocking downloads closes nothing.

    Every carrier here rides on a name or on metadata, so a cache that exposes
    a search or listing API while refusing artifact download is still a fully
    open channel in all four directions.
    """
    _, results = recovered(tmp_path, {"content_reads": False})
    assert sorted(name for name, r in results.items() if r.found) == [
        "cache_key",
        "mkcol_dir",
        "negative_lookup",
        "property_field",
    ]


def test_the_probe_reports_four_fails(tmp_path):
    report, findings = probe_http_cache(tmp_path)
    assert [f.verdict for f in report.findings] == ["FAIL"] * 4
    assert report.exit_code() == 1
    assert all(f.persistence == "durable" for f in findings.values())


def test_the_probe_reports_four_fails_with_content_reads_off(tmp_path):
    _, findings = probe_http_cache(tmp_path, {"content_reads": False})
    assert [f.verdict for f in findings.values()] == ["FAIL"] * 4


def test_a_declared_carrier_is_authorized(tmp_path):
    _, findings = probe_http_cache(tmp_path, declared=["cache:mkcol_dir"])
    assert findings["mkcol_dir"].verdict == "AUTHORIZED"
    assert findings["cache_key"].verdict == "FAIL"
    assert findings["negative_lookup"].verdict == "FAIL"


def test_the_report_carries_the_nonce_as_evidence(tmp_path):
    report, findings = probe_http_cache(tmp_path)
    assert report.nonce in findings["mkcol_dir"].detail
    assert report.nonce in findings["negative_lookup"].detail


def test_the_server_is_closed_after_the_probe(tmp_path):
    """No orphaned socket and no orphaned thread once the run is over."""
    import socket

    surface = HttpCacheSurface("cache", {}, tmp_path / "surface")
    surface.setup()
    host, port = surface.server.bound_host, surface.server.port
    surface.cleanup()
    assert surface.server.running is False
    with pytest.raises(OSError):
        socket.create_connection((host, port), timeout=5.0).close()


def test_an_unknown_param_is_a_config_error():
    with pytest.raises(ConfigError) as excinfo:
        parse({"surfaces": [{"name": "c", "type": "http_cache", "params": {"nope": 1}}]})
    message = str(excinfo.value)
    assert "unknown key: 'nope'" in message
    assert "surfaces[0].params.nope" in message
    assert "content_reads" in message


def test_a_wrongly_typed_param_is_a_config_error():
    with pytest.raises(ConfigError) as excinfo:
        parse(
            {"surfaces": [{"name": "c", "type": "http_cache", "params": {"content_reads": "yes"}}]}
        )
    assert "must be true or false, got str" in str(excinfo.value)


def test_a_declared_carrier_that_does_not_exist_is_a_config_error():
    with pytest.raises(ConfigError) as excinfo:
        parse(
            {
                "surfaces": [{"name": "c", "type": "http_cache"}],
                "declared": ["c:header_echo"],
            }
        )
    assert "carrier that does not exist" in str(excinfo.value)


def test_plant_fails_closed_when_the_server_answers_wrongly(tmp_path, monkeypatch):
    """A surface that is not behaving like the cache under test yields ERROR."""
    work = tmp_path / "work"
    run_a, _ = make_pair(work)
    surface = HttpCacheSurface("cache", {}, work / "surface")
    surface.setup()

    def boom(path):
        raise RuntimeError("mkcol exploded")

    monkeypatch.setattr(surface.server.store, "mkcol", boom)
    try:
        with pytest.raises(RuntimeError) as excinfo:
            surface.plant(NONCE, run_a)
    finally:
        surface.cleanup()
    assert "unexpected statuses during plant" in str(excinfo.value)
    assert "'mkcol_dir': 500" in str(excinfo.value)


def test_recover_fails_closed_when_the_server_is_already_stopped(tmp_path, plant):
    surface, run_b = plant(tmp_path)
    surface.cleanup()
    with pytest.raises(RuntimeError) as excinfo:
        surface.recover(run_b)
    assert "not running" in str(excinfo.value)


def test_recover_fails_closed_when_the_index_cannot_be_read(tmp_path, plant, monkeypatch):
    """An index Run B cannot read is a broken probe, never a quiet PASS.

    The URL below is a loopback port that was bound and then closed, so this
    exercises the real unreachable case rather than a stubbed exception.
    """
    surface, run_b = plant(tmp_path)
    dead_url = surface.base_url
    surface.cleanup()
    monkeypatch.setattr(type(surface), "base_url", property(lambda self: dead_url))
    with pytest.raises(RuntimeError) as excinfo:
        surface.recover(run_b)
    assert "could not list" in str(excinfo.value)
    assert INDEX_PATH in str(excinfo.value)


def test_a_failing_plant_becomes_error_rows_and_a_non_zero_exit(tmp_path, monkeypatch):
    from runprobe.surfaces import http_cache as module

    def boom(self, nonce, run):
        raise RuntimeError("plant exploded")

    monkeypatch.setattr(module.HttpCacheSurface, "plant", boom)
    report, findings = probe_http_cache(tmp_path)
    assert [f.verdict for f in report.findings] == ["ERROR"] * 4
    assert report.exit_code() == 1
    assert "plant exploded" in findings["mkcol_dir"].detail


def test_the_carrier_descriptions_survive_a_json_round_trip():
    for carrier in HttpCacheSurface.carriers():
        assert json.loads(json.dumps(carrier.description)) == carrier.description
