"""End to end: the installed CLI, the example configs, a real filesystem, a real git.

Everything else in the suite calls into the package. This runs the command the
way an operator runs it, from a different working directory, and reads the JSON
report off disk.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "runprobe.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
    )


def findings_of(report_path):
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    return data, {f"{f['surface']}:{f['carrier']}": f for f in data["findings"]}


@pytest.fixture(scope="module")
def example_run(tmp_path_factory):
    cwd = tmp_path_factory.mktemp("e2e")
    result = run_cli(["probe", "--config", str(EXAMPLES / "surfaces.json")], cwd)
    return result, cwd


@needs_git
def test_the_example_config_exits_one(example_run):
    result, _ = example_run
    assert result.returncode == 1, result.stderr


@needs_git
def test_the_report_lands_at_the_default_path_in_the_working_directory(example_run):
    _, cwd = example_run
    assert (cwd / "runprobe-report.json").is_file()


@needs_git
def test_the_table_goes_to_stdout(example_run):
    result, _ = example_run
    assert result.stdout.splitlines()[0].startswith("SURFACE")
    assert "report written to" in result.stderr


@needs_git
def test_the_name_carriers_on_both_surfaces_fail(example_run):
    """The two rows that matter most: neither one is a file content read."""
    _, cwd = example_run
    _, findings = findings_of(cwd / "runprobe-report.json")
    assert findings["filesystem:directory_name"]["verdict"] == "FAIL"
    assert findings["git_remote:branch_name"]["verdict"] == "FAIL"


@needs_git
def test_the_deleted_ref_passes(example_run):
    _, cwd = example_run
    _, findings = findings_of(cwd / "runprobe-report.json")
    assert findings["git_remote:deleted_ref"]["verdict"] == "PASS"
    assert findings["git_remote:deleted_ref"]["persistence"] == "transient"


@needs_git
def test_the_report_covers_all_thirteen_carriers(example_run):
    _, cwd = example_run
    data, findings = findings_of(cwd / "runprobe-report.json")
    assert len(findings) == 13
    assert data["schema_version"] == 1
    assert len(data["nonce"]) == 16
    assert data["run_id_a"] != data["run_id_b"]


@needs_git
def test_the_nonce_is_not_in_the_report_findings(example_run):
    """The report says where the nonce was found, and shows it. That is the evidence."""
    _, cwd = example_run
    data, findings = findings_of(cwd / "runprobe-report.json")
    assert data["nonce"] in findings["filesystem:directory_name"]["detail"]


@needs_git
def test_the_declared_example_authorizes_one_row(tmp_path):
    result = run_cli(["probe", "--config", str(EXAMPLES / "surfaces-declared.json")], tmp_path)
    assert result.returncode == 1, result.stderr
    _, findings = findings_of(tmp_path / "runprobe-report.json")
    assert findings["git_remote:branch_name"]["verdict"] == "AUTHORIZED"
    assert findings["git_remote:tag_name"]["verdict"] == "FAIL"


@needs_git
def test_the_probe_leaves_nothing_behind_in_the_working_directory(tmp_path):
    run_cli(["probe", "--config", str(EXAMPLES / "surfaces.json")], tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["runprobe-report.json"]


def test_the_example_configs_are_valid_json_and_load():
    from runprobe.config import load

    for name in ("surfaces.json", "surfaces-declared.json"):
        config = load(EXAMPLES / name)
        assert [s.type for s in config.surfaces] == ["filesystem", "git_remote"]

    assert load(EXAMPLES / "surfaces-declared.json").is_declared("git_remote", "branch_name")
    assert load(EXAMPLES / "surfaces.json").declared == []
