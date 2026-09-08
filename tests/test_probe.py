"""Executor tests.

Every verdict the executor can produce is exercised here through scripted fake
adapters, so that a real adapter test never has to also prove that the verdict
mapping works.
"""

import pytest

from runwarden.config import SURFACE_TYPES, parse
from runwarden.probe import run_probe
from runwarden.surfaces import Carrier, Recovered, Surface

OMIT = object()


def scripted(
    type_name,
    carriers=(("only_carrier", "durable"),),
    results=None,
    raise_at=None,
    log=None,
    cleanup_raises=False,
):
    """Build a fake adapter class with scripted behaviour.

    `results` maps a carrier name to a Recovered, to OMIT to leave it out of the
    recover result, or is absent to report not found.
    """
    carrier_list = [
        Carrier(name, persistence, f"the {name} channel") for name, persistence in carriers
    ]
    plan = dict(results or {})
    events = log if log is not None else []

    class Scripted(Surface):
        type_name_value = type_name

        def __init__(self, name, params, work):
            if raise_at == "construct":
                raise RuntimeError("cannot construct")
            super().__init__(name, params, work)

        @classmethod
        def carriers(cls):
            return list(carrier_list)

        def setup(self):
            events.append(f"setup:{self.name}")
            if raise_at == "setup":
                raise RuntimeError("cannot set up")

        def plant(self, nonce, run):
            events.append(f"plant:{self.name}")
            assert run.label == "A"
            if raise_at == "plant":
                raise RuntimeError("cannot plant")

        def recover(self, run):
            events.append(f"recover:{self.name}")
            assert run.label == "B"
            if raise_at == "recover":
                raise RuntimeError("cannot recover")
            out = []
            for carrier in carrier_list:
                entry = plan.get(carrier.name)
                if entry is OMIT:
                    continue
                if entry is None:
                    entry = Recovered(carrier.name, False, "not found")
                if isinstance(entry, list):
                    out.extend(entry)
                else:
                    out.append(entry)
            return out

        def cleanup(self):
            events.append(f"cleanup:{self.name}")
            if cleanup_raises:
                raise RuntimeError("cannot clean up")

    Scripted.type_name = type_name
    Scripted.__name__ = f"Scripted_{type_name}"
    return Scripted


@pytest.fixture
def register_scripted(monkeypatch):
    def _register(adapter):
        monkeypatch.setitem(SURFACE_TYPES, adapter.type_name, adapter)
        return adapter

    return _register


def probe_with(adapter, register, tmp_path, declared=(), params=None):
    register(adapter)
    surface = {"name": "s", "type": adapter.type_name}
    if params is not None:
        surface["params"] = params
    config = parse({"surfaces": [surface], "declared": list(declared)})
    return run_probe(config, tmp_path / "work")


def only(report):
    assert len(report.findings) == 1
    return report.findings[0]


def test_recovered_and_undeclared_is_a_fail(register_scripted, tmp_path):
    adapter = scripted(
        "fails", results={"only_carrier": Recovered("only_carrier", True, "nonce in the name")}
    )
    finding = only(probe_with(adapter, register_scripted, tmp_path))
    assert finding.verdict == "FAIL"
    assert finding.detail == "nonce in the name"
    assert finding.persistence == "durable"


def test_not_recovered_is_a_pass(register_scripted, tmp_path):
    finding = only(probe_with(scripted("passes"), register_scripted, tmp_path))
    assert finding.verdict == "PASS"


def test_recovered_and_declared_is_authorized(register_scripted, tmp_path):
    adapter = scripted(
        "authorized", results={"only_carrier": Recovered("only_carrier", True, "found")}
    )
    report = probe_with(adapter, register_scripted, tmp_path, declared=["s:only_carrier"])
    assert only(report).verdict == "AUTHORIZED"
    assert report.exit_code() == 0


def test_unsupported_is_skipped_with_the_reason(register_scripted, tmp_path):
    adapter = scripted(
        "skips",
        results={
            "only_carrier": Recovered(
                "only_carrier", False, "no xattrs here", supported=False
            )
        },
    )
    finding = only(probe_with(adapter, register_scripted, tmp_path))
    assert finding.verdict == "SKIPPED"
    assert finding.detail == "no xattrs here"


def test_a_carrier_the_adapter_forgot_is_an_error(register_scripted, tmp_path):
    """Silence about a carrier is not evidence that the carrier is closed."""
    adapter = scripted("forgets", results={"only_carrier": OMIT})
    finding = only(probe_with(adapter, register_scripted, tmp_path))
    assert finding.verdict == "ERROR"
    assert finding.detail == "adapter did not report carrier only_carrier"


def test_a_carrier_the_adapter_never_declared_is_an_error(register_scripted, tmp_path):
    adapter = scripted(
        "surprises",
        results={"only_carrier": [Recovered("only_carrier", False, "not found"),
                                  Recovered("surprise", True, "found")]},
    )
    report = probe_with(adapter, register_scripted, tmp_path)
    verdicts = {f.carrier: f.verdict for f in report.findings}
    assert verdicts == {"only_carrier": "PASS", "surprise": "ERROR"}
    assert report.exit_code() == 1


def test_a_duplicated_carrier_is_an_error(register_scripted, tmp_path):
    adapter = scripted(
        "duplicates",
        results={"only_carrier": [Recovered("only_carrier", False, "a"),
                                  Recovered("only_carrier", True, "b")]},
    )
    finding = only(probe_with(adapter, register_scripted, tmp_path))
    assert finding.verdict == "ERROR"
    assert "more than once" in finding.detail


@pytest.mark.parametrize("stage", ["construct", "setup", "plant", "recover"])
def test_an_adapter_failure_at_any_stage_is_an_error(register_scripted, tmp_path, stage):
    adapter = scripted(f"breaks_{stage}", raise_at=stage)
    finding = only(probe_with(adapter, register_scripted, tmp_path))
    assert finding.verdict == "ERROR"
    assert stage in finding.detail or "construction" in finding.detail
    assert "RuntimeError" in finding.detail


def test_a_broken_surface_does_not_stop_the_others(register_scripted, tmp_path):
    register_scripted(scripted("broken", raise_at="plant"))
    register_scripted(
        scripted("working", results={"only_carrier": Recovered("only_carrier", True, "found")})
    )
    config = parse(
        {
            "surfaces": [
                {"name": "bad", "type": "broken"},
                {"name": "good", "type": "working"},
            ]
        }
    )
    report = run_probe(config, tmp_path / "work")
    verdicts = {f.surface: f.verdict for f in report.findings}
    assert verdicts == {"bad": "ERROR", "good": "FAIL"}
    assert report.exit_code() == 1


def test_setup_failure_skips_plant_and_recover_for_that_surface(register_scripted, tmp_path):
    log = []
    adapter = scripted("setup_breaks", raise_at="setup", log=log)
    probe_with(adapter, register_scripted, tmp_path)
    assert log == ["setup:s", "cleanup:s"]


def test_every_plant_happens_before_any_recover(register_scripted, tmp_path):
    """Two runs whose lifetimes overlap would be a weaker claim to test."""
    log = []
    register_scripted(scripted("first", log=log))
    register_scripted(scripted("second", log=log))
    config = parse(
        {"surfaces": [{"name": "one", "type": "first"}, {"name": "two", "type": "second"}]}
    )
    run_probe(config, tmp_path / "work")
    assert log == [
        "setup:one",
        "setup:two",
        "plant:one",
        "plant:two",
        "recover:one",
        "recover:two",
        "cleanup:one",
        "cleanup:two",
    ]


def test_cleanup_runs_even_when_the_adapter_failed(register_scripted, tmp_path):
    log = []
    adapter = scripted("cleans", raise_at="recover", log=log)
    probe_with(adapter, register_scripted, tmp_path)
    assert log[-1] == "cleanup:s"


def test_a_cleanup_failure_is_logged_and_is_not_a_finding(register_scripted, tmp_path, capsys):
    adapter = scripted("dirty", cleanup_raises=True)
    report = probe_with(adapter, register_scripted, tmp_path)
    assert only(report).verdict == "PASS"
    assert report.exit_code() == 0
    assert "cleanup failed for surface s" in capsys.readouterr().err


def test_the_report_carries_the_nonce_and_both_run_ids(register_scripted, tmp_path):
    report = probe_with(scripted("ids"), register_scripted, tmp_path)
    assert len(report.nonce) == 16
    assert len(report.run_id_a) == 12
    assert report.run_id_a != report.run_id_b


def test_findings_follow_config_order_then_carrier_order(register_scripted, tmp_path):
    register_scripted(
        scripted("multi", carriers=(("b_first", "durable"), ("a_second", "transient")))
    )
    register_scripted(scripted("single", carriers=(("only", "unknown"),)))
    config = parse(
        {"surfaces": [{"name": "two", "type": "multi"}, {"name": "one", "type": "single"}]}
    )
    report = run_probe(config, tmp_path / "work")
    assert [(f.surface, f.carrier) for f in report.findings] == [
        ("two", "b_first"),
        ("two", "a_second"),
        ("one", "only"),
    ]


def test_the_two_runs_have_disjoint_work_directories(register_scripted, tmp_path):
    seen = {}

    class Watcher(Surface):
        type_name = "watcher"

        @classmethod
        def carriers(cls):
            return [Carrier("only", "durable", "d")]

        def plant(self, nonce, run):
            seen["a"] = run.workdir

        def recover(self, run):
            seen["b"] = run.workdir
            return [Recovered("only", False, "not found")]

    probe_with(Watcher, register_scripted, tmp_path)
    assert seen["a"] != seen["b"]
    assert not seen["a"].is_relative_to(seen["b"])


def test_the_surface_work_dir_is_outside_both_run_directories(register_scripted, tmp_path):
    seen = {}

    class Watcher(Surface):
        type_name = "watcher_work"

        @classmethod
        def carriers(cls):
            return [Carrier("only", "durable", "d")]

        def setup(self):
            seen["surface"] = self.work

        def plant(self, nonce, run):
            seen["a"] = run.workdir

        def recover(self, run):
            seen["b"] = run.workdir
            return [Recovered("only", False, "not found")]

    probe_with(Watcher, register_scripted, tmp_path)
    assert seen["surface"].is_dir()
    assert not seen["surface"].is_relative_to(seen["a"])
    assert not seen["surface"].is_relative_to(seen["b"])


def test_params_reach_the_adapter(register_scripted, tmp_path):
    seen = {}

    class Watcher(Surface):
        type_name = "watcher_params"

        @classmethod
        def validate_params(cls, params, path="params"):
            return None

        @classmethod
        def carriers(cls):
            return [Carrier("only", "durable", "d")]

        def plant(self, nonce, run):
            seen["params"] = self.params

        def recover(self, run):
            return [Recovered("only", False, "not found")]

    probe_with(Watcher, register_scripted, tmp_path, params={"path": "/tmp"})
    assert seen["params"] == {"path": "/tmp"}


def test_the_planted_nonce_is_the_reported_nonce(register_scripted, tmp_path):
    seen = {}

    class Watcher(Surface):
        type_name = "watcher_nonce"

        @classmethod
        def carriers(cls):
            return [Carrier("only", "durable", "d")]

        def plant(self, nonce, run):
            seen["nonce"] = nonce

        def recover(self, run):
            return [Recovered("only", False, "not found")]

    report = probe_with(Watcher, register_scripted, tmp_path)
    assert seen["nonce"] == report.nonce
