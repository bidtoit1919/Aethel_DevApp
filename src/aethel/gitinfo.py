import os
import subprocess
import threading
from dataclasses import dataclass

from gi.repository import GLib

# Read-only only (SPEC 2.7): rev-parse, status, log. --no-optional-locks
# stops `git status` from writing an index-refresh lock into the repo.
TIMEOUT_SECONDS = 5

# LC_ALL=C keeps stderr in English so the ownership check below can match it.
_ENV = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}

_UNBORN_OID = "(initial)"
_DETACHED_HEAD = "(detached)"


@dataclass
class GitInfo:
    # kind: ok | no-commits | no-repo | no-git | error
    # upstream_gone: an upstream is configured but its remote branch no
    # longer exists, so ahead/behind cannot be computed.
    kind: str
    branch: str = ""
    detached: bool = False
    dirty: bool = False
    changed_files: int = 0
    has_upstream: bool = False
    upstream: str = ""
    upstream_gone: bool = False
    ahead: int = 0
    behind: int = 0
    last_hash: str = ""
    subject: str = ""
    message: str = ""


def _git(project_path: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", project_path, *args],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        env=_ENV,
    )


def fetch(project_path: str) -> GitInfo:
    try:
        return _fetch(project_path)
    except FileNotFoundError:
        return GitInfo(
            "no-git",
            message=(
                "The git command was not found on this system. Install git "
                "(for example: sudo apt install git), then reload this view."
            ),
        )
    except subprocess.TimeoutExpired:
        return GitInfo(
            "error",
            message=(
                f"git took longer than {TIMEOUT_SECONDS} seconds to answer "
                "for this folder. The repository may be on a slow disk or "
                "network share. Press Refresh to try again."
            ),
        )


def _fetch(project_path: str) -> GitInfo:
    inside = _git(project_path, "rev-parse", "--is-inside-work-tree")
    if "dubious ownership" in inside.stderr:
        return GitInfo(
            "error",
            message=(
                "git refuses to read this repository because it is owned by "
                "another user. If you trust it, run 'git config --global --add "
                f"safe.directory {project_path}' in a terminal, then press "
                "Refresh."
            ),
        )
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitInfo(
            "no-repo",
            message=(
                "This folder is not a git repository, so there is no branch "
                "or commit history to show."
            ),
        )

    status = _git(
        project_path, "--no-optional-locks", "status", "--porcelain=v2", "--branch"
    )
    if status.returncode != 0:
        return GitInfo(
            "error",
            message=(
                "git could not read the status of this repository. Check the "
                "folder permissions and that the repo is intact, then press "
                "Refresh."
            ),
        )

    oid = ""
    head = ""
    upstream = ""
    ahead = behind = 0
    has_ab = False
    changes = 0
    for line in status.stdout.splitlines():
        if line.startswith("# branch.oid "):
            oid = line[len("# branch.oid ") :]
        elif line.startswith("# branch.head "):
            head = line[len("# branch.head ") :]
        elif line.startswith("# branch.upstream "):
            upstream = line[len("# branch.upstream ") :]
        elif line.startswith("# branch.ab "):
            # Format is "+<ahead> -<behind>" relative to the upstream.
            plus, minus = line[len("# branch.ab ") :].split()
            ahead, behind = int(plus[1:]), int(minus[1:])
            has_ab = True
        elif line[:1] in ("1", "2", "u", "?", "!"):
            changes += 1

    dirty = changes > 0
    if oid == _UNBORN_OID:
        return GitInfo(
            "no-commits",
            branch=head,
            dirty=dirty,
            changed_files=changes,
        )

    log = _git(project_path, "log", "-1", "--format=%h%x1f%s")
    if log.returncode != 0:
        return GitInfo(
            "error",
            message=(
                "git reported a repository here but its history could not be "
                "read. The repository may be corrupted; run 'git fsck' in a "
                "terminal to check."
            ),
        )
    last_hash, _, subject = log.stdout.partition("\x1f")
    subject = subject.strip()

    detached = head == _DETACHED_HEAD
    return GitInfo(
        "ok",
        branch="" if detached else head,
        detached=detached,
        dirty=dirty,
        changed_files=changes,
        has_upstream=bool(upstream),
        upstream=upstream,
        upstream_gone=bool(upstream) and not has_ab,
        ahead=ahead,
        behind=behind,
        last_hash=last_hash,
        subject=subject,
    )


def fetch_async(project_path: str, callback) -> None:
    # Subprocess work stays off the main thread (SPEC 2.3); GLib.idle_add
    # marshals the result back where touching widgets is safe.
    def work():
        GLib.idle_add(callback, fetch(project_path))

    threading.Thread(target=work, daemon=True).start()
