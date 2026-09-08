"""Report tests: table shape, JSON round trip, and exit code per verdict."""

import json

import pytest

from runprobe.report import (
    FAILING_VERDICTS,
    PERSISTENCE_CLASSES,
    VERDICTS,
    Finding,
    Report,
)


def make_report(findings=()):
    report = Report(nonce="0123456789abcdef", run_id_a="aaaaaaaaaaaa", run_id_b="bbbbbbbbbbbb")
    for finding in findings:
        report.add(finding)
    return report


def test_to_table_has_one_row_per_finding():
    findings = [
        Finding("filesystem", "file_content", "PASS", "transient"),
        Finding("filesystem", "directory_name", "FAIL", "durable", "nonce in shared dir"),
        Finding("git_remote", "branch_name", "AUTHORIZED", "durable"),
    ]
    table = make_report(findings).to_table()
    lines = table.split("\n")
    # Header line plus separator line plus one line per finding.
    assert len(lines) == 2 + len(findings)
    assert lines[0].startswith("SURFACE")
    assert set(lines[1]) <= {"-", " "}
    for line, finding in zip(lines[2:], findings, strict=True):
        assert line.startswith(finding.surface)
        assert finding.carrier in line
        assert finding.verdict in line


def test_to_table_with_no_findings_is_just_the_header():
    lines = make_report().to_table().split("\n")
    assert len(lines) == 2


def test_to_table_is_ascii_only():
    """No unicode box drawing. The table has to survive a plain CI log."""
    table = make_report(
        [Finding("filesystem", "file_content", "PASS", "transient", "nothing recovered")]
    ).to_table()
    assert table.isascii()


def test_to_table_columns_are_fixed_width():
    findings = [
        Finding("fs", "a", "PASS", "transient"),
        Finding("a_much_longer_surface", "b", "FAIL", "durable"),
    ]
    lines = make_report(findings).to_table().split("\n")
    carrier_column = lines[0].index("CARRIER")
    for line in lines[2:]:
        assert line[carrier_column] != " "


def test_to_json_round_trips():
    findings = [
        Finding("filesystem", "file_content", "PASS", "transient"),
        Finding("git_remote", "branch_name", "FAIL", "durable", "ls-remote listed the nonce"),
    ]
    original = make_report(findings)
    restored = Report.from_json(original.to_json())
    assert restored.to_dict() == original.to_dict()
    assert restored.findings == findings
    assert restored.nonce == original.nonce
    assert restored.run_id_a == original.run_id_a
    assert restored.run_id_b == original.run_id_b
    assert restored.timestamp == original.timestamp


def test_to_json_is_valid_json_with_the_expected_top_level_keys():
    data = json.loads(make_report().to_json())
    assert set(data) == {
        "schema_version",
        "nonce",
        "run_id_a",
        "run_id_b",
        "timestamp",
        "findings",
    }


def test_timestamp_is_utc_with_a_trailing_z():
    report = make_report()
    assert report.timestamp.endswith("Z")
    assert len(report.timestamp) == 20


@pytest.mark.parametrize("verdict", VERDICTS)
def test_exit_code_for_each_verdict(verdict):
    report = make_report([Finding("filesystem", "file_content", verdict, "unknown")])
    expected = 1 if verdict in ("FAIL", "ERROR") else 0
    assert report.exit_code() == expected


def test_exit_code_is_zero_with_no_findings():
    assert make_report().exit_code() == 0


def test_exit_code_is_one_if_any_finding_fails():
    report = make_report(
        [
            Finding("filesystem", "file_content", "PASS", "transient"),
            Finding("filesystem", "directory_name", "FAIL", "durable"),
            Finding("git_remote", "branch_name", "AUTHORIZED", "durable"),
        ]
    )
    assert report.exit_code() == 1


def test_authorized_and_skipped_do_not_fail_the_run():
    report = make_report(
        [
            Finding("filesystem", "file_content", "AUTHORIZED", "durable"),
            Finding("git_remote", "branch_name", "SKIPPED", "unknown", "git not on PATH"),
        ]
    )
    assert report.exit_code() == 0


def test_failing_verdicts_are_fail_and_error():
    assert FAILING_VERDICTS == {"FAIL", "ERROR"}


def test_invalid_verdict_is_rejected():
    with pytest.raises(ValueError, match="verdict"):
        Finding("filesystem", "file_content", "MAYBE", "transient")


def test_invalid_persistence_is_rejected():
    with pytest.raises(ValueError, match="persistence"):
        Finding("filesystem", "file_content", "PASS", "forever")


def test_persistence_classes_are_the_declared_set():
    assert PERSISTENCE_CLASSES == ("transient", "durable", "until-gc", "unknown")
