"""End to end: the artifactory_mailbox fixture, run the way the README says.

This is the incident reproduction, so it is run through the installed CLI from
a scratch working directory rather than by calling into the package. What is
asserted here is what a reader of the fixture README would see on their own
box: four carriers open, twice, and an exit code of 1.
"""

import json
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "fixtures" / "artifactory_mailbox"
CONFIG = FIXTURE / "surfaces.json"

CARRIERS = ["cache_key", "negative_lookup", "mkcol_dir", "property_field"]
SURFACES = ["registry_cache", "registry_cache_no_downloads"]

FixtureRun = namedtuple("FixtureRun", "result cwd data findings")


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory):
    cwd = tmp_path_factory.mktemp("artifactory-mailbox")
    result = subprocess.run(
        [sys.executable, "-m", "runwarden.cli", "probe", "--config", str(CONFIG)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
    )
    data = json.loads((cwd / "runwarden-report.json").read_text(encoding="utf-8"))
    findings = {f"{f['surface']}:{f['carrier']}": f for f in data["findings"]}
    return FixtureRun(result, cwd, data, findings)


def test_the_fixture_exits_one_which_is_the_expected_result(fixture_run):
    """A zero here would mean the fixture had stopped reproducing the incident."""
    assert fixture_run.result.returncode == 1, fixture_run.result.stderr


def test_all_four_carriers_fail(fixture_run):
    verdicts = [fixture_run.findings[f"registry_cache:{c}"]["verdict"] for c in CARRIERS]
    assert verdicts == ["FAIL"] * 4


def test_all_four_still_fail_with_downloads_blocked(fixture_run):
    """The moral of the fixture, asserted rather than only written down."""
    verdicts = [
        fixture_run.findings[f"registry_cache_no_downloads:{c}"]["verdict"] for c in CARRIERS
    ]
    assert verdicts == ["FAIL"] * 4


def test_the_report_covers_both_surfaces_and_nothing_else(fixture_run):
    assert len(fixture_run.data["findings"]) == 8
    assert sorted(fixture_run.findings) == sorted(
        f"{surface}:{carrier}" for surface in SURFACES for carrier in CARRIERS
    )


def test_every_carrier_is_durable(fixture_run):
    assert {f["persistence"] for f in fixture_run.findings.values()} == {"durable"}


def test_the_nonce_is_the_evidence_in_every_row(fixture_run):
    nonce = fixture_run.data["nonce"]
    assert all(nonce in f["detail"] for f in fixture_run.findings.values())


def test_the_two_runs_are_distinct(fixture_run):
    assert fixture_run.data["run_id_a"] != fixture_run.data["run_id_b"]


def test_the_negative_lookup_row_reports_a_cached_404(fixture_run):
    """The distinction that makes this carrier worth its own row."""
    detail = fixture_run.findings["registry_cache:negative_lookup"]["detail"]
    assert "cached 404" in detail
    assert "not a stored artifact" in detail


def test_the_mkcol_row_names_the_incident_mechanic(fixture_run):
    detail = fixture_run.findings["registry_cache:mkcol_dir"]["detail"]
    assert "MKCOL" in detail
    assert "_SEEK_IDEA" in detail


def test_the_table_goes_to_stdout(fixture_run):
    assert fixture_run.result.stdout.splitlines()[0].startswith("SURFACE")
    assert "registry_cache_no_downloads" in fixture_run.result.stdout


def test_the_fixture_leaves_nothing_behind_but_the_report(fixture_run):
    """Both cache servers are the adapter's to stop, and the work directory goes too."""
    assert sorted(p.name for p in fixture_run.cwd.iterdir()) == ["runwarden-report.json"]


def test_the_fixture_config_declares_two_http_cache_surfaces():
    from runwarden.config import load

    config = load(CONFIG)
    assert [s.type for s in config.surfaces] == ["http_cache", "http_cache"]
    assert [s.name for s in config.surfaces] == SURFACES
    assert config.surfaces[1].params == {"content_reads": False}
    assert config.declared == []


def test_the_fixture_readme_says_the_non_zero_exit_is_correct():
    """Documentation guard: nobody should read exit 1 here as a tool failure."""
    text = (FIXTURE / "README.md").read_text(encoding="utf-8")
    assert "Exit code 1 is the expected and correct result" in text
    assert "Blocking content did not help" in text
