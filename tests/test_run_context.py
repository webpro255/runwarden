"""Run context tests. The env scrub is the part that matters most.

If a variable leaks in from the parent process, it becomes a channel between the
two runs that the probe was never asked about.
"""

import pytest

from runprobe.run_context import ALLOWED_ENV_KEYS, RunContext, make_context, make_pair

CANARY_NAME = "RUNPROBE_TEST_CANARY"


def test_pair_has_different_run_ids(tmp_path):
    run_a, run_b = make_pair(tmp_path)
    assert run_a.run_id != run_b.run_id
    assert len(run_a.run_id) == 12
    assert len(run_b.run_id) == 12


def test_pair_labels_are_a_and_b(tmp_path):
    run_a, run_b = make_pair(tmp_path)
    assert run_a.label == "A"
    assert run_b.label == "B"


def test_pair_workdirs_are_disjoint(tmp_path):
    run_a, run_b = make_pair(tmp_path)
    assert run_a.workdir != run_b.workdir
    assert not run_a.workdir.is_relative_to(run_b.workdir)
    assert not run_b.workdir.is_relative_to(run_a.workdir)


def test_pair_tmpdirs_are_disjoint(tmp_path):
    run_a, run_b = make_pair(tmp_path)
    assert run_a.tmpdir != run_b.tmpdir
    assert not run_a.tmpdir.is_relative_to(run_b.tmpdir)
    assert not run_b.tmpdir.is_relative_to(run_a.tmpdir)


def test_pair_directories_exist(tmp_path):
    run_a, run_b = make_pair(tmp_path)
    for run in (run_a, run_b):
        assert run.workdir.is_dir()
        assert run.tmpdir.is_dir()


def test_env_contains_exactly_the_four_allowed_keys(tmp_path, monkeypatch):
    monkeypatch.setenv(CANARY_NAME, "leaked")
    run_a, run_b = make_pair(tmp_path)
    for run in (run_a, run_b):
        assert set(run.env) == set(ALLOWED_ENV_KEYS)
        assert len(run.env) == 4


def test_canary_from_parent_env_is_absent(tmp_path, monkeypatch):
    monkeypatch.setenv(CANARY_NAME, "leaked")
    run_a, run_b = make_pair(tmp_path)
    for run in (run_a, run_b):
        assert CANARY_NAME not in run.env
        assert "leaked" not in run.env.values()


def test_env_home_and_tmpdir_point_at_the_run_directories(tmp_path):
    run_a, run_b = make_pair(tmp_path)
    for run in (run_a, run_b):
        assert run.env["HOME"] == str(run.workdir)
        assert run.env["TMPDIR"] == str(run.tmpdir)
        assert run.env["RUNPROBE_RUN_ID"] == run.run_id


def test_run_ids_in_env_are_not_shared(tmp_path):
    run_a, run_b = make_pair(tmp_path)
    assert run_a.env["RUNPROBE_RUN_ID"] != run_b.env["RUNPROBE_RUN_ID"]


def test_label_must_be_a_or_b(tmp_path):
    with pytest.raises(ValueError, match="label"):
        RunContext(
            run_id="0123456789ab",
            label="C",
            workdir=tmp_path,
            tmpdir=tmp_path,
            env={},
        )


def test_run_id_length_is_enforced(tmp_path):
    with pytest.raises(ValueError, match="run_id"):
        RunContext(run_id="abc", label="A", workdir=tmp_path, tmpdir=tmp_path, env={})


def test_make_context_accepts_an_explicit_run_id(tmp_path):
    run = make_context(tmp_path, "A", run_id="0123456789ab")
    assert run.run_id == "0123456789ab"
    assert run.env["RUNPROBE_RUN_ID"] == "0123456789ab"
