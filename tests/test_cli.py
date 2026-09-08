"""CLI tests. Phase 0 has no adapters, so probe never exits 0."""

import json

import pytest

from runprobe import __version__
from runprobe.cli import EXIT_CANNOT_RUN, main


def test_version_flag_prints_the_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help_and_exits_two(capsys):
    assert main([]) == EXIT_CANNOT_RUN
    assert "usage: runprobe" in capsys.readouterr().err


def test_probe_with_a_missing_config_exits_two(capsys, tmp_path):
    assert main(["probe", "--config", str(tmp_path / "nope.json")]) == EXIT_CANNOT_RUN
    assert "config file not found" in capsys.readouterr().err


def test_probe_with_an_unknown_surface_type_exits_two(capsys, tmp_path):
    path = tmp_path / "surfaces.json"
    path.write_text(json.dumps({"surfaces": [{"name": "a", "type": "filesystem"}]}))
    assert main(["probe", "--config", str(path)]) == EXIT_CANNOT_RUN
    assert "unknown surface type: filesystem" in capsys.readouterr().err


def test_probe_runs_a_registered_surface_and_writes_a_report(capsys, tmp_path, registered_type):
    """FakeSurface recovers nothing, so the probe runs clean and exits zero."""
    path = tmp_path / "surfaces.json"
    path.write_text(json.dumps({"surfaces": [{"name": "a", "type": "fake"}]}))
    report_path = tmp_path / "report.json"
    assert main(["probe", "--config", str(path), "--report", str(report_path)]) == 0

    captured = capsys.readouterr()
    assert "SURFACE" in captured.out
    assert "file_content" in captured.out
    assert "PASS" in captured.out

    data = json.loads(report_path.read_text())
    assert {f["carrier"] for f in data["findings"]} == {"file_content", "directory_name"}
    assert all(f["verdict"] == "PASS" for f in data["findings"])


def test_probe_keep_work_prints_a_surviving_directory(capsys, tmp_path, registered_type):
    from pathlib import Path as _Path

    path = tmp_path / "surfaces.json"
    path.write_text(json.dumps({"surfaces": [{"name": "a", "type": "fake"}]}))
    main(
        [
            "probe",
            "--config",
            str(path),
            "--report",
            str(tmp_path / "report.json"),
            "--keep-work",
        ]
    )
    line = [
        line for line in capsys.readouterr().out.splitlines() if "work directory kept" in line
    ]
    assert len(line) == 1
    assert _Path(line[0].split("kept at ")[1]).is_dir()


def test_probe_deletes_the_work_directory_by_default(capsys, tmp_path, registered_type):
    path = tmp_path / "surfaces.json"
    path.write_text(json.dumps({"surfaces": [{"name": "a", "type": "fake"}]}))
    main(["probe", "--config", str(path), "--report", str(tmp_path / "report.json")])
    assert "work directory kept" not in capsys.readouterr().out


def test_probe_reports_an_unwritable_report_path(capsys, tmp_path, registered_type):
    path = tmp_path / "surfaces.json"
    path.write_text(json.dumps({"surfaces": [{"name": "a", "type": "fake"}]}))
    unwritable = tmp_path / "no_such_dir" / "report.json"
    assert main(["probe", "--config", str(path), "--report", str(unwritable)]) == EXIT_CANNOT_RUN
    assert "could not write report" in capsys.readouterr().err


def test_report_path_defaults(tmp_path):
    from runprobe.cli import build_parser

    args = build_parser().parse_args(["probe", "--config", "surfaces.json"])
    assert args.report == "runprobe-report.json"
    args = build_parser().parse_args(
        ["probe", "--config", "surfaces.json", "--report", "out.json"]
    )
    assert args.report == "out.json"
