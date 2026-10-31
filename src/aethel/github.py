"""GitHub through the user's own `gh` login.

Reads (repo, issues, pull requests, CI runs, diffs) run freely. The few
writes (create branch, push, open a pull request, comment) are separate
functions that the UI only calls after an explicit confirmation. Nothing
here force-pushes, deletes or rewrites history.
"""

import json
import os
import re
import shutil
import subprocess

TIMEOUT = 40


class GitHubError(Exception):
    pass


def _run(path: str, args: list[str], stdin: str | None = None, timeout: int = TIMEOUT) -> str:
    if shutil.which(args[0]) is None:
        raise GitHubError(f"{args[0]} is not installed. Install the GitHub CLI (sudo apt install gh) and run 'gh auth login'.")
    try:
        result = subprocess.run(args, cwd=path, capture_output=True, text=True, timeout=timeout,
                                input=stdin, env={**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1",
                                                  "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        raise GitHubError(f"{' '.join(args[:3])} took longer than {timeout} seconds. Check your connection and try again.") from None
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()
        detail = message[-1] if message else "no details"
        if "not logged" in detail.lower() or "auth login" in detail.lower():
            detail = "gh is not logged in. Run 'gh auth login' in a terminal."
        elif "no git remotes" in detail.lower() or "not a git repository" in detail.lower():
            detail = "This project has no GitHub remote."
        raise GitHubError(detail)
    return result.stdout


def _json(path: str, args: list[str]):
    out = _run(path, ["gh", *args])
    try:
        return json.loads(out or "null")
    except ValueError:
        raise GitHubError("gh returned output that could not be read.") from None


def status() -> str:
    """The logged-in account, or raises with how to log in."""
    out = _run(os.path.expanduser("~"), ["gh", "auth", "status"])
    match = re.search(r"account (\S+)", out)
    return match.group(1) if match else "logged in"


def repo(path: str) -> dict:
    return _json(path, ["repo", "view", "--json",
                        "nameWithOwner,description,url,defaultBranchRef,visibility,stargazerCount,forkCount,pushedAt"])


def issues(path: str, limit: int = 30) -> list[dict]:
    return _json(path, ["issue", "list", "--limit", str(limit), "--json",
                        "number,title,author,labels,updatedAt,comments,url"]) or []


def issue(path: str, number: int) -> dict:
    return _json(path, ["issue", "view", str(number), "--json", "number,title,body,author,labels,url,comments"])


def prs(path: str, limit: int = 30) -> list[dict]:
    return _json(path, ["pr", "list", "--limit", str(limit), "--json",
                        "number,title,author,headRefName,baseRefName,isDraft,updatedAt,reviewDecision,"
                        "statusCheckRollup,url,additions,deletions"]) or []


def pr(path: str, number: int) -> dict:
    return _json(path, ["pr", "view", str(number), "--json",
                        "number,title,body,headRefName,baseRefName,files,commits,statusCheckRollup,"
                        "reviewDecision,url,additions,deletions,state"])


def pr_diff(path: str, number: int) -> str:
    return _run(path, ["gh", "pr", "diff", str(number)])


def runs(path: str, limit: int = 15) -> list[dict]:
    return _json(path, ["run", "list", "--limit", str(limit), "--json",
                        "databaseId,displayTitle,status,conclusion,workflowName,headBranch,event,createdAt,url"]) or []


def checks_summary(rollup: list | None) -> tuple[str, str]:
    """(text, style) for a PR's status checks."""
    if not rollup:
        return "no checks", ""
    states = [(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in rollup]
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT") for s in states):
        return f"{sum(s in ('FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT') for s in states)} failing", "error"
    if any(s in ("PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", "") for s in states):
        return "checks running", "warning"
    return f"{len(states)} passing", "success"


# Writes: only called after the user confirms in the UI. ----------------

def git_current_branch(path: str) -> str:
    return _run(path, ["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()


def create_branch(path: str, name: str) -> None:
    # `git switch -c` refuses an existing name and carries uncommitted
    # changes over, so nothing is lost.
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", name) or ".." in name or name.startswith(("-", "/")):
        raise GitHubError("Branch names may use letters, digits, '.', '_', '-' and '/'.")
    _run(path, ["git", "switch", "-c", name])


def push(path: str) -> str:
    branch = git_current_branch(path)
    if branch == "HEAD":
        raise GitHubError("HEAD is detached; switch to a branch before pushing.")
    _run(path, ["git", "push", "-u", "origin", branch], timeout=120)
    return branch


def create_pr(path: str, title: str, body: str, base: str | None, draft: bool) -> str:
    args = ["gh", "pr", "create", "--title", title, "--body-file", "-"]
    if base:
        args += ["--base", base]
    if draft:
        args.append("--draft")
    out = _run(path, args, stdin=body, timeout=120)
    urls = re.findall(r"https://\S+", out)
    return urls[-1] if urls else out.strip()


def comment_pr(path: str, number: int, body: str) -> None:
    _run(path, ["gh", "pr", "comment", str(number), "--body-file", "-"], stdin=body, timeout=60)


def slug(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-").split("-")
    return "-".join(words[:6])[:48] or "work"
