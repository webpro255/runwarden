"""git_remote adapter tests.

The plant is expensive, so the carriers that share one default configuration
share one plant. The variants that change behaviour get their own run.
"""

import pytest

from runprobe.config import ConfigError, parse
from runprobe.probe import run_probe
from runprobe.run_context import ALLOWED_ENV_KEYS, make_pair
from runprobe.surfaces.git_remote import (
    GUEST_BRANCH,
    OWNED_BRANCH,
    GitRemoteSurface,
)

CARRIER_NAMES = [
    "branch_name",
    "tag_name",
    "commit_message",
    "author_name",
    "file_content",
    "file_path",
    "deleted_ref",
    "dangling_object",
]


def probe_git(tmp_path, params=None, declared=()):
    surface = {"name": "git", "type": "git_remote"}
    if params:
        surface["params"] = params
    config = parse({"surfaces": [surface], "declared": list(declared)})
    report = run_probe(config, tmp_path / "work")
    return report, {f.carrier: f for f in report.findings}


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    """One plant, shared by every test that only reads the default outcome."""
    base = tmp_path_factory.mktemp("git-planted")
    run_a, run_b = make_pair(base / "work")
    surface = GitRemoteSurface("git", {}, base / "surface")
    surface.setup()
    if not surface.supported:
        pytest.skip("git not on PATH")
    surface.plant(surface_nonce := "0123456789abcdef", run_a)
    return surface, run_a, run_b, surface_nonce


@pytest.fixture(scope="module")
def recovered(planted):
    surface, _, run_b, nonce = planted
    return {result.carrier: result for result in surface.recover(run_b)}, nonce


@pytest.fixture(scope="module")
def default_probe(tmp_path_factory):
    base = tmp_path_factory.mktemp("git-probe")
    return probe_git(base)


def test_the_adapter_declares_eight_carriers():
    assert [c.name for c in GitRemoteSurface.carriers()] == CARRIER_NAMES


def test_persistence_classes_are_not_all_durable():
    """A created and deleted ref is not durable, and a dangling commit is not transient."""
    classes = {c.name: c.persistence for c in GitRemoteSurface.carriers()}
    assert classes["branch_name"] == "durable"
    assert classes["deleted_ref"] == "transient"
    assert classes["dangling_object"] == "until-gc"


def test_the_dangling_carrier_describes_the_protocol_caveat():
    description = {c.name: c.description for c in GitRemoteSurface.carriers()}["dangling_object"]
    assert "filesystem access" in description
    assert "unreachable object ids" in description


def test_the_run_environment_stays_at_four_keys_through_the_plant(planted):
    """Identity is passed by -c flags, so no GIT_ variable has to exist."""
    _, run_a, _, _ = planted
    assert set(run_a.env) == set(ALLOWED_ENV_KEYS)
    assert not [key for key in run_a.env if key.startswith("GIT_")]


def test_the_author_differs_from_the_committer(planted):
    """The author carrier only means something if it is a separate field."""
    surface, _, run_b, nonce = planted
    text = surface._text(
        run_b, ["-C", str(surface.bare), "log", "--format=%an|%cn", f"refs/heads/{OWNED_BRANCH}"]
    )
    pairs = [line.split("|") for line in text.splitlines() if line]
    authors = {author for author, _ in pairs}
    committers = {committer for _, committer in pairs}
    assert f"zzAUTH_{nonce}" in authors
    assert committers == {"runprobe run a"}


def test_branch_names_are_recoverable_without_any_clone(planted):
    """ls-remote reads every ref name over the transport, with no content read."""
    surface, _, run_b, nonce = planted
    refs = surface._ls_remote(run_b, ["--heads"])
    assert any(f"msg-{nonce}" in ref for _, ref in refs)
    assert not (run_b.workdir / "repo").exists()


def test_tag_names_are_recoverable_without_any_clone(planted):
    surface, _, run_b, nonce = planted
    tags = surface._ls_remote(run_b, ["--tags"])
    assert any(f"zz-{nonce}" in ref for _, ref in tags)


def test_the_deleted_ref_is_gone_from_the_listing(planted):
    surface, _, run_b, nonce = planted
    all_refs = surface._ls_remote(run_b, [])
    assert not any(f"tmp-{nonce}" in ref for _, ref in all_refs)


def test_the_empty_file_carries_only_its_path(planted):
    """file_path has to be provable without any content, or it is file_content."""
    surface, _, run_b, nonce = planted
    listed = surface._text(
        run_b, ["-C", str(surface.bare), "ls-tree", "-r", "--name-only", OWNED_BRANCH]
    ).split()
    named = [path for path in listed if nonce in path]
    assert named == [f"notes/zz-{nonce}.txt"]
    blob = surface._text(run_b, ["-C", str(surface.bare), "show", f"{OWNED_BRANCH}:{named[0]}"])
    assert blob == ""


def test_every_carrier_except_the_deleted_ref_is_recovered(recovered):
    results, _ = recovered
    assert set(results) == set(CARRIER_NAMES)
    for name in CARRIER_NAMES:
        if name == "deleted_ref":
            assert results[name].found is False
        else:
            assert results[name].found is True, f"{name} was not recovered"


def test_the_deleted_ref_detail_points_at_watch_mode(recovered):
    """The expected PASS is a statement about what visible state cannot show."""
    results, _ = recovered
    assert results["deleted_ref"].found is False
    assert results["deleted_ref"].supported is True
    assert "watch mode" in results["deleted_ref"].detail


def test_the_dangling_commit_is_still_readable_after_the_delete(recovered):
    results, _ = recovered
    assert results["dangling_object"].found is True
    assert "unreachable but present" in results["dangling_object"].detail


def test_the_message_carrier_reports_the_commit_subject(recovered):
    results, nonce = recovered
    assert f"zzMSG_{nonce}" in results["commit_message"].detail


def test_the_author_carrier_reports_the_author_name(recovered):
    results, nonce = recovered
    assert results["author_name"].detail.endswith(f"zzAUTH_{nonce}")


def test_the_content_and_path_carriers_name_different_files(recovered):
    results, nonce = recovered
    assert results["file_content"].detail == "nonce in the bytes of data.txt"
    assert results["file_path"].detail == f"nonce in the tracked path notes/zz-{nonce}.txt"


def test_the_probe_reports_seven_fails_and_one_pass(default_probe):
    report, findings = default_probe
    verdicts = {name: findings[name].verdict for name in CARRIER_NAMES}
    assert verdicts["deleted_ref"] == "PASS"
    assert [v for k, v in verdicts.items() if k != "deleted_ref"] == ["FAIL"] * 7
    assert report.exit_code() == 1


def test_check_dangling_false_skips_that_carrier(tmp_path):
    report, findings = probe_git(tmp_path, {"check_dangling": False})
    assert findings["dangling_object"].verdict == "SKIPPED"
    assert findings["dangling_object"].detail == "check_dangling is false"
    assert findings["branch_name"].verdict == "FAIL"


def test_a_declared_branch_name_is_authorized(tmp_path):
    report, findings = probe_git(tmp_path, declared=["git:branch_name"])
    assert findings["branch_name"].verdict == "AUTHORIZED"
    assert findings["tag_name"].verdict == "FAIL"
    assert report.exit_code() == 1


def test_git_missing_skips_every_carrier_and_exits_zero(tmp_path, monkeypatch):
    """A machine without git has an unprobed surface, not a failed run."""
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    report, findings = probe_git(tmp_path)
    assert {f.verdict for f in findings.values()} == {"SKIPPED"}
    assert {f.detail for f in findings.values()} == {"git not on PATH"}
    assert report.exit_code() == 0


def test_setup_does_not_raise_when_git_is_missing(tmp_path, monkeypatch):
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    surface = GitRemoteSurface("git", {}, tmp_path / "surface")
    surface.setup()
    assert surface.supported is False
    assert surface.unsupported_reason == "git not on PATH"
    surface.plant("0123456789abcdef", make_pair(tmp_path / "work")[0])


def test_a_configured_remote_uses_a_labelled_branch_and_is_left_in_place(tmp_path):
    """The probe must not push over a branch an operator already has."""
    import subprocess

    bare = tmp_path / "operator.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)

    report, findings = probe_git(tmp_path, {"remote": str(bare)})
    assert findings["branch_name"].verdict == "FAIL"
    assert bare.is_dir()

    listed = subprocess.run(
        ["git", "-C", str(bare), "for-each-ref", "--format=%(refname)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert GUEST_BRANCH not in [ref.split("/")[-1] for ref in listed]
    assert listed == []


def test_a_configured_remote_that_is_not_a_repository_is_an_error(tmp_path):
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    report, findings = probe_git(tmp_path, {"remote": str(not_a_repo)})
    assert {f.verdict for f in findings.values()} == {"ERROR"}
    assert "not a git repository" in findings["branch_name"].detail
    assert report.exit_code() == 1


def test_the_owned_branch_and_the_guest_branch_differ(tmp_path):
    owned = GitRemoteSurface("git", {}, tmp_path / "a")
    guest = GitRemoteSurface("git", {"remote": str(tmp_path / "b.git")}, tmp_path / "c")
    assert owned.branch == OWNED_BRANCH
    assert owned.owns_bare is True
    assert guest.branch == GUEST_BRANCH
    assert guest.owns_bare is False


@pytest.mark.parametrize(
    "remote",
    [
        "https://example.invalid/repo.git",
        "ssh://git@example.invalid/repo.git",
        "git@example.invalid:owner/repo.git",
        "file:///srv/repo.git",
    ],
)
def test_a_url_remote_is_rejected_at_config_time(remote):
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "git", "type": "git_remote", "params": {"remote": remote}}]})
    message = str(exc.value)
    assert "must be a local path" in message
    assert remote in message


def test_a_local_path_remote_is_accepted_at_config_time(tmp_path):
    config = parse(
        {
            "surfaces": [
                {"name": "git", "type": "git_remote", "params": {"remote": str(tmp_path)}}
            ]
        }
    )
    assert config.surfaces[0].params["remote"] == str(tmp_path)


def test_an_empty_remote_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "git", "type": "git_remote", "params": {"remote": " "}}]})
    assert "must not be empty" in str(exc.value)


def test_an_unknown_param_key_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        parse({"surfaces": [{"name": "git", "type": "git_remote", "params": {"remotes": "x"}}]})
    message = str(exc.value)
    assert "unknown key" in message
    assert "check_dangling, remote" in message


def test_a_wrongly_typed_param_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        parse(
            {
                "surfaces": [
                    {"name": "git", "type": "git_remote", "params": {"check_dangling": 1}}
                ]
            }
        )
    assert "check_dangling must be true or false" in str(exc.value)


def test_a_declared_carrier_that_does_not_exist_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        parse(
            {"surfaces": [{"name": "git", "type": "git_remote"}], "declared": ["git:branch_names"]}
        )
    assert "carriers on this surface" in str(exc.value)
