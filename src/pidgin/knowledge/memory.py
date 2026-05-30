from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pidgin.workspace.manager import WorkspacePaths


def remember(paths: WorkspacePaths, handle: str, text: str) -> Path:
    journal = paths.agent_journal(handle)
    journal.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"\n## {timestamp}\n{text.strip()}\n"
    with journal.open("a", encoding="utf-8") as f:
        f.write(entry)
    return journal


def recall_tail(paths: WorkspacePaths, handle: str, max_lines: int = 80) -> str:
    journal = paths.agent_journal(handle)
    if not journal.exists():
        return ""
    lines = journal.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-max_lines:])


def recall_grep(paths: WorkspacePaths, handle: str, query: str, max_matches: int = 20) -> list[str]:
    journal = paths.agent_journal(handle)
    if not journal.exists():
        return []
    matches: list[str] = []
    for line in journal.read_text(encoding="utf-8").splitlines():
        if query.lower() in line.lower():
            matches.append(line)
            if len(matches) >= max_matches:
                break
    return matches
