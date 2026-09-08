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


def test_probe_reports_no_adapters_once_a_type_resolves(capsys, tmp_path, registered_type):
    """With a type registered, config validation passes and the probe stops here."""
    path = tmp_path / "surfaces.json"
    path.write_text(json.dumps({"surfaces": [{"name": "a", "type": "fake"}]}))
    assert main(["probe", "--config", str(path)]) == EXIT_CANNOT_RUN
    assert "no adapters registered" in capsys.readouterr().err


def test_report_path_defaults(tmp_path):
    from runprobe.cli import build_parser

    args = build_parser().parse_args(["probe", "--config", "surfaces.json"])
    assert args.report == "runprobe-report.json"
    args = build_parser().parse_args(
        ["probe", "--config", "surfaces.json", "--report", "out.json"]
    )
    assert args.report == "out.json"
