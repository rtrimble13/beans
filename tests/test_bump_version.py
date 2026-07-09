"""Tests for scripts/bump_version.py — the release version bumper."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "bump_version", ROOT / "scripts" / "bump_version.py"
)
bump_version = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bump_version)


@pytest.mark.parametrize(
    "value,number",
    [
        ("v1.2.3", "1.2.3"),
        ("v0.1.0", "0.1.0"),
        ("v10.20.30", "10.20.30"),
        ("v1.2.3rc1", "1.2.3rc1"),
        ("v2.0.0b2", "2.0.0b2"),
        ("v1.5.0.dev1", "1.5.0.dev1"),
    ],
)
def test_valid_versions_match(value, number):
    m = bump_version.VERSION_RE.match(value)
    assert m is not None
    assert m.group("num") == number


@pytest.mark.parametrize(
    "value",
    ["1.2.3", "v1.2", "v1", "vX.X.X", "v1.2.3.4", "version1.2.3", "v1.2.3-1"],
)
def test_invalid_versions_rejected(value):
    assert bump_version.VERSION_RE.match(value) is None


def test_read_current_version_matches_package():
    import beans

    assert bump_version.read_current_version() == beans.__version__


def test_write_version_round_trips(tmp_path, monkeypatch):
    init = tmp_path / "__init__.py"
    init.write_text('"""doc."""\n\n__version__ = "0.1.0"\n')
    monkeypatch.setattr(bump_version, "INIT_FILE", init)

    assert bump_version.read_current_version() == "0.1.0"
    bump_version.write_version("1.2.3")
    assert bump_version.read_current_version() == "1.2.3"
    # Only the version line changed; surrounding content is preserved.
    assert init.read_text() == '"""doc."""\n\n__version__ = "1.2.3"\n'


def test_show_prints_current_version(capsys):
    rc = bump_version.main(["--show"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    import beans

    assert out == f"v{beans.__version__}"


def test_invalid_version_exits_2(capsys):
    with pytest.raises(SystemExit) as excinfo:
        bump_version.main(["1.2.3"])
    assert excinfo.value.code == 2
    assert "not a valid version" in capsys.readouterr().err


def test_no_commit_edits_without_git(tmp_path, monkeypatch, capsys):
    init = tmp_path / "__init__.py"
    init.write_text('__version__ = "0.1.0"\n')
    monkeypatch.setattr(bump_version, "INIT_FILE", init)

    def _boom(*args):
        raise AssertionError("git should not be called with --no-commit")

    monkeypatch.setattr(bump_version, "git", _boom)

    rc = bump_version.main(["v2.3.4", "--no-commit"])
    assert rc == 0
    assert bump_version.read_current_version() == "2.3.4"


def _init_git_repo(root: Path) -> None:
    def run(*args):
        subprocess.run(["git", *args], cwd=root, check=True,
                       capture_output=True, text=True)

    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("add", ".")
    run("commit", "-q", "-m", "initial")


def _setup_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    pkg = root / "beans"
    pkg.mkdir(parents=True)
    init = pkg / "__init__.py"
    init.write_text('__version__ = "0.1.0"\n')
    _init_git_repo(root)
    monkeypatch.setattr(bump_version, "ROOT", root)
    monkeypatch.setattr(bump_version, "INIT_FILE", init)
    return root, init


def _git_out(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    ).stdout.strip()


def test_bump_commits_and_tags(tmp_path, monkeypatch):
    root, init = _setup_repo(tmp_path, monkeypatch)

    rc = bump_version.main(["v1.2.3"])
    assert rc == 0

    assert init.read_text() == '__version__ = "1.2.3"\n'
    # A commit was made with the expected message.
    assert _git_out(root, "log", "-1", "--pretty=%s") == "Release v1.2.3"
    # An annotated tag v1.2.3 now exists.
    assert _git_out(root, "tag", "--list", "v1.2.3") == "v1.2.3"
    assert _git_out(root, "cat-file", "-t", "v1.2.3") == "tag"
    # Working tree is clean afterwards (only the version file was committed).
    assert _git_out(root, "status", "--porcelain") == ""


def test_bump_no_tag_skips_tag(tmp_path, monkeypatch):
    root, _ = _setup_repo(tmp_path, monkeypatch)

    rc = bump_version.main(["v1.2.3", "--no-tag"])
    assert rc == 0
    assert _git_out(root, "log", "-1", "--pretty=%s") == "Release v1.2.3"
    assert _git_out(root, "tag", "--list") == ""


def test_bump_refuses_dirty_worktree(tmp_path, monkeypatch, capsys):
    root, _ = _setup_repo(tmp_path, monkeypatch)
    (root / "dirty.txt").write_text("uncommitted\n")

    with pytest.raises(SystemExit) as excinfo:
        bump_version.main(["v1.2.3"])
    assert excinfo.value.code == 2
    assert "not clean" in capsys.readouterr().err


def test_bump_refuses_existing_tag(tmp_path, monkeypatch, capsys):
    root, _ = _setup_repo(tmp_path, monkeypatch)
    subprocess.run(["git", "tag", "v1.2.3"], cwd=root, check=True)

    with pytest.raises(SystemExit) as excinfo:
        bump_version.main(["v1.2.3"])
    assert excinfo.value.code == 2
    assert "already exists" in capsys.readouterr().err


def test_bump_refuses_noop(tmp_path, monkeypatch, capsys):
    root, _ = _setup_repo(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        bump_version.main(["v0.1.0"])
    assert excinfo.value.code == 2
    assert "already" in capsys.readouterr().err
