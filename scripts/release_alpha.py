"""Prepare and publish JoyBoy alpha releases.

The workflow is intentionally conservative:
- a scheduled/manual job opens a release PR only when enough meaningful changes
  landed since the last tag;
- merging that PR publishes the tag and GitHub prerelease.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[1]
VERSION_FILE = PROJECT_DIR / "VERSION"
RELEASE_NOTES_DIR = PROJECT_DIR / "docs" / "releases"
PLAN_FILE = PROJECT_DIR / "release_plan.json"


@dataclass
class CommitInfo:
    sha: str
    subject: str
    body: str = ""
    files: List[str] = field(default_factory=list)
    category: str = "maintenance"
    score: float = 0.0


def run_git(args: Sequence[str], *, check: bool = False) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def write_github_outputs(outputs: dict) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def read_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def write_version(version: str) -> None:
    VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")


def normalize_tag(version: str) -> str:
    value = str(version or "").strip()
    return value if value.startswith("v") else f"v{value}"


def next_alpha_version(current_version: str) -> str:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-alpha\.(\d+))?$", current_version.strip())
    if not match:
        raise ValueError(f"VERSION must look like 0.1.0-alpha.N or 0.1.0, got {current_version!r}")

    major, minor, patch, alpha = match.groups()
    if alpha is not None:
        return f"{major}.{minor}.{patch}-alpha.{int(alpha) + 1}"
    return f"{major}.{minor}.{int(patch) + 1}-alpha.1"


def latest_reachable_tag() -> str:
    return run_git(["describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"])


def tag_exists(tag: str) -> bool:
    return bool(run_git(["tag", "--list", tag]))


def commit_range(previous_tag: str) -> str:
    return f"{previous_tag}..HEAD" if previous_tag else "HEAD"


def parse_commits(range_spec: str) -> List[CommitInfo]:
    raw = run_git([
        "log",
        "--no-merges",
        "--format=%H%x1f%s%x1f%b%x1e",
        range_spec,
    ])
    commits: List[CommitInfo] = []
    for record in raw.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f", 2)
        if len(parts) < 2:
            continue
        sha = parts[0].strip()
        subject = parts[1].strip()
        body = parts[2].strip() if len(parts) > 2 else ""
        files = run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", sha]).splitlines()
        commit = CommitInfo(sha=sha, subject=subject, body=body, files=[item.strip() for item in files if item.strip()])
        commit.category, commit.score = classify_commit(commit)
        commits.append(commit)
    return commits


def only_docs(files: Iterable[str]) -> bool:
    file_list = list(files)
    return bool(file_list) and all(
        path.startswith("docs/")
        or path in {"README.md", "ROADMAP.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"}
        or path.endswith(".md")
        for path in file_list
    )


def classify_commit(commit: CommitInfo) -> tuple[str, float]:
    subject = commit.subject.lower()
    files = commit.files
    score = 0.0
    category = "maintenance"

    if any(path.startswith("core/generation/") or path.startswith("core/models/") for path in files):
        category = "runtime"
        score += 3.5
    elif any(path.startswith("core/") or path.startswith("web/routes/") for path in files):
        category = "runtime"
        score += 3.0

    if any(path.startswith("web/static/js/") or path.startswith("web/templates/") for path in files):
        if category == "maintenance":
            category = "features"
        score += 2.5

    if any(path.startswith("web/static/css/") for path in files):
        if category == "maintenance":
            category = "ui"
        score += 1.5

    if any(path.startswith(".github/") or path.startswith("scripts/") for path in files):
        if category == "maintenance":
            category = "maintenance"
        score += 2.0

    if any(path.startswith("tests/") for path in files):
        score += 1.0

    if only_docs(files):
        category = "docs"
        score = max(score, 0.5)

    if re.search(r"\b(fix|repair|resolve|bug|crash|cancel|mps|macos|windows)\b", subject):
        category = "fixes"
        score += 1.5
    elif re.search(r"\b(add|create|implement|enable|introduce|support)\b", subject):
        if category in {"maintenance", "docs"}:
            category = "features"
        score += 1.0
    elif re.search(r"\b(test|coverage)\b", subject):
        if category == "maintenance":
            category = "tests"
        score += 0.5

    return category, min(score, 6.0)


def clean_subject(subject: str) -> str:
    text = re.sub(r"^(feat|fix|docs|test|tests|chore|ci|ui|refactor)(\([^)]+\))?:\s*", "", subject.strip(), flags=re.I)
    text = text[:1].upper() + text[1:] if text else subject.strip()
    return text.rstrip(".")


def group_commits(commits: Sequence[CommitInfo]) -> dict:
    groups = {
        "features": [],
        "fixes": [],
        "runtime": [],
        "ui": [],
        "tests": [],
        "docs": [],
        "maintenance": [],
    }
    for commit in commits:
        groups.setdefault(commit.category, []).append(commit)
    return groups


def release_score(commits: Sequence[CommitInfo]) -> float:
    return round(sum(commit.score for commit in commits), 2)


def meaningful_commit_count(commits: Sequence[CommitInfo]) -> int:
    return sum(1 for commit in commits if commit.score >= 1.5 and commit.category != "docs")


def should_prepare_release(commits: Sequence[CommitInfo], min_score: float, min_commits: int, force: bool) -> tuple[bool, str]:
    if force and commits:
        return True, "forced"
    if not commits:
        return False, "no commits since last release"

    score = release_score(commits)
    meaningful = meaningful_commit_count(commits)
    if score >= min_score:
        return True, f"score {score} >= {min_score}"
    if meaningful >= min_commits:
        return True, f"{meaningful} meaningful commits >= {min_commits}"
    return False, f"not enough change yet: score {score}/{min_score}, meaningful commits {meaningful}/{min_commits}"


def render_release_notes(version: str, previous_tag: str, commits: Sequence[CommitInfo], reason: str) -> str:
    tag = normalize_tag(version)
    groups = group_commits(commits)
    lines = [
        f"# JoyBoy {tag}",
        "",
        "Automated alpha prerelease prepared from changes on `main`.",
        "",
        f"- Previous release: `{previous_tag or 'none'}`",
        f"- Included commits: {len(commits)}",
        f"- Release reason: {reason}",
        "",
        "This is an alpha prerelease. Expect fast iteration while install, runtime, and public-core polish continue.",
        "",
    ]

    section_titles = [
        ("features", "Highlights"),
        ("fixes", "Fixes"),
        ("runtime", "Runtime And Models"),
        ("ui", "UI"),
        ("tests", "Tests"),
        ("docs", "Docs"),
        ("maintenance", "Maintenance"),
    ]
    for key, title in section_titles:
        items = groups.get(key) or []
        if not items:
            continue
        lines.extend([f"## {title}", ""])
        for commit in items[:12]:
            lines.append(f"- {clean_subject(commit.subject)} (`{commit.sha[:7]}`)")
        if len(items) > 12:
            lines.append(f"- Plus {len(items) - 12} more change(s).")
        lines.append("")

    lines.extend(["## Commit List", ""])
    for commit in commits:
        lines.append(f"- `{commit.sha[:7]}` {commit.subject}")
    lines.append("")
    return "\n".join(lines)


def build_plan(min_score: float, min_commits: int, force: bool) -> dict:
    current_version = read_version()
    next_version = next_alpha_version(current_version)
    next_tag = normalize_tag(next_version)
    previous_tag = latest_reachable_tag()
    commits = parse_commits(commit_range(previous_tag))
    should_release, reason = should_prepare_release(commits, min_score, min_commits, force)

    return {
        "should_release": should_release,
        "reason": reason,
        "current_version": current_version,
        "next_version": next_version,
        "tag": next_tag,
        "branch": f"release/{next_tag}",
        "previous_tag": previous_tag,
        "score": release_score(commits),
        "meaningful_commits": meaningful_commit_count(commits),
        "commit_count": len(commits),
        "notes_path": str((RELEASE_NOTES_DIR / f"{next_tag}.md").relative_to(PROJECT_DIR)).replace("\\", "/"),
        "notes": render_release_notes(next_version, previous_tag, commits, reason),
        "commits": [
            {
                "sha": commit.sha,
                "subject": commit.subject,
                "category": commit.category,
                "score": commit.score,
                "files": commit.files,
            }
            for commit in commits
        ],
    }


def prepare(args: argparse.Namespace) -> int:
    plan = build_plan(args.min_score, args.min_commits, args.force)
    PLAN_FILE.write_text(json.dumps({key: value for key, value in plan.items() if key != "notes"}, indent=2), encoding="utf-8")

    if args.write and plan["should_release"]:
        RELEASE_NOTES_DIR.mkdir(parents=True, exist_ok=True)
        write_version(plan["next_version"])
        (PROJECT_DIR / plan["notes_path"]).write_text(plan["notes"], encoding="utf-8")

    write_github_outputs({
        "should_release": str(plan["should_release"]).lower(),
        "reason": plan["reason"],
        "tag": plan["tag"],
        "version": plan["next_version"],
        "branch": plan["branch"],
        "notes_path": plan["notes_path"],
        "score": plan["score"],
        "meaningful_commits": plan["meaningful_commits"],
        "commit_count": plan["commit_count"],
    })

    print(json.dumps({key: value for key, value in plan.items() if key != "notes" and key != "commits"}, indent=2))
    return 0


def publish_plan(_: argparse.Namespace) -> int:
    version = read_version()
    tag = normalize_tag(version)
    notes_path = RELEASE_NOTES_DIR / f"{tag}.md"
    if not notes_path.exists():
        previous_tag = latest_reachable_tag()
        commits = parse_commits(commit_range(previous_tag))
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text(render_release_notes(version, previous_tag, commits, "release notes regenerated"), encoding="utf-8")

    should_publish = not tag_exists(tag)
    prerelease = bool(re.search(r"-(alpha|beta|rc)\.", version))
    outputs = {
        "should_publish": str(should_publish).lower(),
        "tag": tag,
        "version": version,
        "title": f"JoyBoy {tag}",
        "notes_path": str(notes_path.relative_to(PROJECT_DIR)).replace("\\", "/"),
        "prerelease": str(prerelease).lower(),
    }
    write_github_outputs(outputs)
    print(json.dumps(outputs, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JoyBoy alpha release helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--min-score", type=float, default=8.0)
    prepare_parser.add_argument("--min-commits", type=int, default=4)
    prepare_parser.add_argument("--force", action="store_true")
    prepare_parser.add_argument("--write", action="store_true")
    prepare_parser.set_defaults(func=prepare)

    publish_parser = subparsers.add_parser("publish-plan")
    publish_parser.set_defaults(func=publish_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
