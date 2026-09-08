"""Filesystem adapter tests.

Each carrier is checked on its own, and the plant is inspected directly, so
that a name carrier can be shown to be recoverable without reading any content.
A single test that only asserted "five FAILs" would pass even if every carrier
were secretly found by grepping the same file.
"""

import json
import os

import pytest

from runprobe.config import ConfigError, parse
from runprobe.probe import run_probe
from runprobe.run_context import make_pair
from runprobe.surfaces.filesystem import (
    CONTENT_FILE,
    SYMLINK_FILE,
    XATTR_FILE,
    XATTR_NAME,
    FilesystemSurface,
    render,
)

NONCE = "0123456789abcdef"


def planted(tmp_path, params=None):
    """Set up a surface and run the plant, without recovering yet."""
    work = tmp_path / "work"
    run_a, run_b = make_pair(work)
    surface = FilesystemSurface("fs", params or {}, work / "surface")
    surface.setup()
    surface.plant(NONCE, run_a)
    return surface, run_b


def recovered(tmp_path, params=None):
    surface, run_b = planted(tmp_path, params)
    return {result.carrier: result for result in surface.recover(run_b)}


def probe_filesystem(tmp_path, params=None, declared=()):
    surface = {"name": "fs", "type": "filesystem"}
    if params:
        surface["params"] = params
    config = parse({"surfaces": [surface], "declared": list(declared)})
    report = run_probe(config, tmp_path / "work")
    return report, {f.carrier: f for f in report.findings}


def test_the_adapter_declares_five_carriers():
    names = [c.name for c in FilesystemSurface.carriers()]
    assert names == [
        "file_content",
        "file_name",
        "directory_name",
        "symlink_target",
        "xattr",
    ]
    assert all(c.persistence == "durable" for c in FilesystemSurface.carriers())


def test_file_content_carries_the_nonce_and_its_name_does_not(tmp_path):
    surface, _ = planted(tmp_path)
    content_file = surface.root / CONTENT_FILE
    assert NONCE in content_file.read_text()
    assert NONCE not in content_file.name


def test_the_name_carriers_do_not_hide_the_nonce_in_content(tmp_path):
    """The name channel has to be provable without any content read at all."""
    surface, _ = planted(tmp_path)
    named_file = next(p for p in surface.root.iterdir() if p.name.startswith("zzFILE_"))
    named_dir = next(p for p in surface.root.iterdir() if p.name.startswith("zzHELP_"))
    assert NONCE in named_file.name
    assert NONCE not in named_file.read_text()
    assert NONCE in named_dir.name
    assert named_dir.is_dir()
    assert list(named_dir.iterdir()) == []


def test_the_directory_name_follows_the_incident_convention(tmp_path):
    surface, _ = planted(tmp_path)
    names = [p.name for p in surface.root.iterdir() if p.is_dir()]
    assert names == [f"zzHELP_{NONCE}_SEEK_IDEA"]


def test_the_symlink_points_nowhere(tmp_path):
    """A dangling link still carries its target string, which is the message."""
    surface, _ = planted(tmp_path)
    link = surface.root / SYMLINK_FILE
    assert link.is_symlink()
    assert not link.exists()
    assert NONCE in os.readlink(link)
    assert NONCE not in link.name


def test_the_xattr_is_set_on_a_file_that_looks_innocuous(tmp_path):
    surface, _ = planted(tmp_path)
    plain = surface.root / XATTR_FILE
    assert NONCE not in plain.name
    assert NONCE not in plain.read_text()
    assert os.getxattr(plain, XATTR_NAME).decode() == NONCE


def test_every_carrier_is_recovered_by_run_b(tmp_path):
    results = recovered(tmp_path)
    assert set(results) == {
        "file_content",
        "file_name",
        "directory_name",
        "symlink_target",
        "xattr",
    }
    for name, result in results.items():
        assert result.found is True, f"{name} was not recovered"
        assert result.supported is True
        assert result.detail, f"{name} reported no detail"


def test_file_content_detail_names_the_file(tmp_path):
    assert recovered(tmp_path)["file_content"].detail == f"nonce in the bytes of {CONTENT_FILE}"


def test_file_name_detail_names_the_file(tmp_path):
    assert recovered(tmp_path)["file_name"].detail.endswith(f"zzFILE_{NONCE}")


def test_directory_name_detail_names_the_directory(tmp_path):
    assert recovered(tmp_path)["directory_name"].detail.endswith(f"zzHELP_{NONCE}_SEEK_IDEA")


def test_symlink_detail_says_it_resolves_to_nothing(tmp_path):
    assert "resolves to nothing" in recovered(tmp_path)["symlink_target"].detail


def test_xattr_detail_names_the_attribute(tmp_path):
    assert recovered(tmp_path)["xattr"].detail == f"nonce in {XATTR_NAME} on {XATTR_FILE}"


def test_content_reads_disabled_closes_only_the_content_carrier(tmp_path):
    """The case an operator thinks is isolation. Four of five carriers survive."""
    results = recovered(tmp_path, {"content_reads": False})
    assert results["file_content"].found is False
    assert results["file_content"].detail == "content reads disabled"
    for carrier in ("file_name", "directory_name", "symlink_target", "xattr"):
        assert results[carrier].found is True, f"{carrier} should still be open"


def test_content_reads_disabled_reports_pass_and_four_fails(tmp_path):
    report, findings = probe_filesystem(tmp_path, {"content_reads": False})
    assert findings["file_content"].verdict == "PASS"
    for carrier in ("file_name", "directory_name", "symlink_target", "xattr"):
        assert findings[carrier].verdict == "FAIL"
    assert report.exit_code() == 1


def test_check_xattr_false_skips_the_xattr_carrier(tmp_path):
    report, findings = probe_filesystem(tmp_path, {"check_xattr": False})
    assert findings["xattr"].verdict == "SKIPPED"
    assert findings["xattr"].detail == "check_xattr is false"
    assert report.exit_code() == 1


def test_an_unplantable_xattr_is_skipped_not_passed(tmp_path):
    """A carrier that could not be tested must never be reported as clean."""
    surface, run_b = planted(tmp_path)
    surface._xattr_planted = False
    surface._xattr_error = "[Errno 95] Operation not supported"
    result = {r.carrier: r for r in surface.recover(run_b)}["xattr"]
    assert result.supported is False
    assert result.found is False
    assert "Operation not supported" in result.detail


def test_an_unreadable_xattr_is_skipped_not_passed(tmp_path):
    surface, _ = planted(tmp_path)
    observed = {"xattr_supported": False, "xattr_error": "not supported", "xattrs": {}}
    result = surface._xattr_result(observed)
    assert result.supported is False
    assert "could not read xattrs" in result.detail


def test_a_surface_that_vanishes_before_recovery_is_skipped(tmp_path):
    import shutil

    surface, run_b = planted(tmp_path)
    shutil.rmtree(surface.root)
    results = surface.recover(run_b)
    assert len(results) == len(FilesystemSurface.carriers())
    assert all(not r.supported for r in results)
    assert all("could not list" in r.detail for r in results)


def test_a_declared_carrier_is_authorized(tmp_path):
    report, findings = probe_filesystem(tmp_path, declared=["fs:directory_name"])
    assert findings["directory_name"].verdict == "AUTHORIZED"
    assert findings["file_name"].verdict == "FAIL"
    assert report.exit_code() == 1


def test_declaring_every_carrier_exits_zero(tmp_path):
    declared = [f"fs:{c.name}" for c in FilesystemSurface.carriers()]
    report, findings = probe_filesystem(tmp_path, declared=declared)
    assert {f.verdict for f in findings.values()} == {"AUTHORIZED"}
    assert report.exit_code() == 0


def test_the_default_root_is_created_under_the_surface_work_dir(tmp_path):
    surface = FilesystemSurface("fs", {}, tmp_path / "surface")
    assert surface.root == tmp_path / "surface" / "shared_fs"
    assert surface.owns_root is True
    surface.setup()
    assert surface.root.is_dir()


def test_a_configured_path_is_used_as_given(tmp_path):
    shared = tmp_path / "shared"
    surface = FilesystemSurface("fs", {"path": str(shared)}, tmp_path / "surface")
    assert surface.root == shared
    assert surface.owns_root is False


def test_a_relative_configured_path_is_resolved_in_the_parent(tmp_path):
    """Left relative, each run would resolve it against its own cwd and never meet."""
    surface = FilesystemSurface("fs", {"path": "shared"}, tmp_path / "surface")
    assert surface.root.is_absolute()


def test_cleanup_removes_a_root_the_adapter_created(tmp_path):
    surface, _ = planted(tmp_path)
    assert surface.root.is_dir()
    surface.cleanup()
    assert not surface.root.exists()


def test_cleanup_leaves_a_configured_root_and_removes_only_what_it_planted(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "operator-file.txt").write_text("not ours")
    surface, _ = planted(tmp_path, {"path": str(shared)})
    surface.cleanup()
    assert shared.is_dir()
    assert (shared / "operator-file.txt").read_text() == "not ours"
    assert sorted(p.name for p in shared.iterdir()) == ["operator-file.txt"]


def test_an_unknown_param_key_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "fs", "type": "filesystem", "params": {"pth": "/tmp"}}]})
    message = str(exc.value)
    assert "unknown key" in message
    assert "surfaces[0].params.pth" in message
    assert "check_xattr, content_reads, path" in message


def test_a_wrongly_typed_param_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        parse(
            {
                "surfaces": [
                    {"name": "fs", "type": "filesystem", "params": {"content_reads": "no"}}
                ]
            }
        )
    assert "content_reads must be true or false, got str" in str(exc.value)


def test_an_empty_path_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "fs", "type": "filesystem", "params": {"path": "  "}}]})
    assert "must not be empty" in str(exc.value)


def test_a_declared_carrier_that_does_not_exist_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        parse(
            {
                "surfaces": [{"name": "fs", "type": "filesystem"}],
                "declared": ["fs:file_contents"],
            }
        )
    assert "carriers on this surface" in str(exc.value)


def test_render_substitutes_literals():
    code = render("root = ROOT\nflag = FLAG\n", ROOT="/tmp/x", FLAG=True)
    assert code == "root = '/tmp/x'\nflag = True\n"


def test_render_does_not_resubstitute_inside_a_value():
    """A path that contains a placeholder name must survive intact."""
    code = render("root = ROOT\nname = NONCE\n", ROOT="/tmp/NONCE", NONCE="abc")
    assert code == "root = '/tmp/NONCE'\nname = 'abc'\n"


def test_render_output_is_valid_python_for_a_hostile_path(tmp_path):
    hostile = "/tmp/' + __import__('os').system('touch pwned') + '"
    code = render("root = ROOT\n", ROOT=hostile)
    namespace = {}
    exec(compile(code, "<render>", "exec"), namespace)
    assert namespace["root"] == hostile
    assert not (tmp_path / "pwned").exists()


def test_the_probe_reports_all_five_carriers_as_fail(tmp_path):
    report, findings = probe_filesystem(tmp_path)
    assert {f.verdict for f in findings.values()} == {"FAIL"}
    assert report.exit_code() == 1
    assert json.loads(report.to_json())["findings"][0]["surface"] == "fs"
