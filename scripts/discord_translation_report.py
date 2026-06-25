from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
HIDDEN_LINES_PATH = ROOT / "assets" / "companion" / "hidden_lines.json"
SUMMARY_PATH = ROOT / "assets" / "progress" / "summary.json"

FIELD_START_RE = re.compile(r'^(msgctxt|msgid|msgstr)\s+(.+)$')
LINE_STATUS_RE = re.compile(
    r'^#\.\s+(?:lineStatus\s*:\s*|y4:line_status\s*=\s*)(.+)$',
    re.MULTILINE | re.IGNORECASE,
)
FILE_STATUS_RE = re.compile(
    r'^#\.\s+(?:fileStatus\s*:\s*|y4:file_status\s*=\s*)(.+)$',
    re.MULTILINE | re.IGNORECASE,
)
REVIEWED_BY_RE = re.compile(
    r'^#\.\s+y4:reviewed_by\s*=\s*(.+)$',
    re.MULTILINE | re.IGNORECASE,
)


def git(*args: str, allow_fail: bool = False) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        if allow_fail:
            return ""
        raise RuntimeError(result.stderr.strip())

    return result.stdout


def po_unquote(value: str) -> str:
    value = value.strip()

    if not value.startswith('"'):
        return ""

    try:
        return ast.literal_eval(value)
    except Exception:
        return value.strip('"')


def normalize_status(value: str) -> str:
    return value.strip().strip('"').lower()


def extract_po_field(block: str, field_name: str) -> str:
    lines = block.splitlines()
    output: list[str] = []
    collecting = False

    for line in lines:
        match = FIELD_START_RE.match(line)

        if match:
            current_field = match.group(1)
            collecting = current_field == field_name

            if collecting:
                output.append(po_unquote(match.group(2)))

            continue

        if collecting and line.strip().startswith('"'):
            output.append(po_unquote(line.strip()))
            continue

        if collecting and (line.startswith("#") or line.strip() == ""):
            continue

        if collecting:
            break

    return "".join(output)


def iter_po_blocks(text: str):
    for block in re.split(r"\n\s*\n", text):
        if not block.strip():
            continue
        lines = block.splitlines()
        if any(line.startswith('msgid ""') for line in lines[:4]):
            continue
        if "msgid " not in block or "msgstr " not in block:
            continue
        yield block


def load_hidden_terms() -> list[str]:
    if not HIDDEN_LINES_PATH.exists():
        return []

    try:
        data = json.loads(HIDDEN_LINES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    terms = data.get("blocked_terms", [])

    if not isinstance(terms, list):
        return []

    return sorted({
        str(term).strip().lower()
        for term in terms
        if str(term).strip()
    })


def is_hidden_entry(block: str, hidden_terms: list[str]) -> bool:
    if not hidden_terms:
        return False

    haystack = "\n".join([
        extract_po_field(block, "msgctxt"),
        extract_po_field(block, "msgid"),
        extract_po_field(block, "msgstr"),
    ]).lower()

    return any(term in haystack for term in hidden_terms)


def is_entry_reviewed(block: str, file_reviewed: bool) -> bool:
    line_statuses = LINE_STATUS_RE.findall(block)

    if line_statuses and normalize_status(line_statuses[-1]) == "reviewed":
        return True

    if REVIEWED_BY_RE.search(block):
        return True

    if file_reviewed:
        return True

    return False


def parse_po_text(text: str, hidden_terms: list[str]) -> dict[tuple[str, str], dict]:
    entries: dict[tuple[str, str], dict] = {}

    file_statuses = FILE_STATUS_RE.findall(text)
    file_reviewed = any(
        normalize_status(status) == "reviewed"
        for status in file_statuses
    )

    for block in iter_po_blocks(text):
        if is_hidden_entry(block, hidden_terms):
            continue

        msgctxt = extract_po_field(block, "msgctxt")
        msgid = extract_po_field(block, "msgid")
        msgstr = extract_po_field(block, "msgstr")

        key = (msgctxt, msgid)

        entries[key] = {
            "msgstr": msgstr,
            "translated": msgstr.strip() != "",
            "reviewed": is_entry_reviewed(block, file_reviewed),
        }

    return entries


def file_at_commit(commit: str, path: str) -> str:
    if not commit:
        return ""

    return git("show", f"{commit}:{path}", allow_fail=True)


def changed_po_file_pairs(old_commit: str, new_commit: str) -> list[tuple[str, str]]:
    output = git(
        "diff",
        "--name-status",
        "-M",
        "--diff-filter=ACMR",
        old_commit,
        new_commit,
        "--",
        "*.po",
        allow_fail=True,
    )

    pairs: list[tuple[str, str]] = []

    for line in output.splitlines():
        if not line.strip():
            continue

        parts = line.split("\t")
        status = parts[0]

        if status.startswith("R") or status.startswith("C"):
            if len(parts) >= 3:
                old_path = parts[1]
                new_path = parts[2]
                pairs.append((old_path, new_path))
        else:
            if len(parts) >= 2:
                path = parts[1]
                pairs.append((path, path))

    return pairs


def is_translated(entry: dict | None) -> bool:
    return bool(entry and entry.get("translated"))


def is_reviewed(entry: dict | None) -> bool:
    return bool(entry and entry.get("reviewed"))


def count_commit_progress(old_commit: str, new_commit: str, hidden_terms: list[str]) -> dict:
    stats = {
        "translated": 0,
        "translated_files": set(),
        "reviewed": 0,
        "reviewed_files": set(),
        "edited": 0,
        "edited_files": set(),
    }

    for old_path, new_path in changed_po_file_pairs(old_commit, new_commit):
        old_text = file_at_commit(old_commit, old_path)
        new_text = file_at_commit(new_commit, new_path)

        old_entries = parse_po_text(old_text, hidden_terms)
        new_entries = parse_po_text(new_text, hidden_terms)

        for key, new_entry in new_entries.items():
            old_entry = old_entries.get(key)

            old_translated = is_translated(old_entry)
            new_translated = is_translated(new_entry)

            old_reviewed = is_reviewed(old_entry)
            new_reviewed = is_reviewed(new_entry)

            if not old_translated and new_translated:
                stats["translated"] += 1
                stats["translated_files"].add(new_path)

            elif (
                old_translated
                and new_translated
                and old_entry
                and old_entry.get("msgstr", "") != new_entry.get("msgstr", "")
            ):
                stats["edited"] += 1
                stats["edited_files"].add(new_path)

            if not old_reviewed and new_reviewed:
                stats["reviewed"] += 1
                stats["reviewed_files"].add(new_path)

    return stats


def get_commits(before: str, after: str) -> list[str]:
    if before and not before.startswith("0000000"):
        rev_range = f"{before}..{after}"
    else:
        rev_range = f"{after}^..{after}"

    output = git("rev-list", "--reverse", rev_range, allow_fail=True)

    commits = [
        line.strip()
        for line in output.splitlines()
        if line.strip()
    ]

    if not commits:
        commits = [after]

    return commits


def load_github_username_map() -> dict[str, str]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")

    if not event_path:
        return {}

    try:
        with open(event_path, "r", encoding="utf-8") as f:
            event = json.load(f)
    except Exception:
        return {}

    username_map = {}

    for commit in event.get("commits", []):
        sha = commit.get("id")
        author = commit.get("author") or {}
        username = author.get("username")

        if sha and username:
            username_map[sha] = username
    return username_map


GITHUB_USERNAME_MAP = load_github_username_map()


def commit_author(commit: str) -> str:
    username = GITHUB_USERNAME_MAP.get(commit)

    if username:
        return username

    actor = os.environ.get("GITHUB_ACTOR")

    if actor:
        return actor

    author = git("show", "-s", "--format=%an", commit, allow_fail=True).strip()
    return author or "Usuario desconocido"


def load_summary() -> dict:
    if not SUMMARY_PATH.exists():
        return {}

    try:
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def format_pct(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def pct_gain(lines: int, total: int) -> float:
    if total <= 0:
        return 0.0

    return (lines * 100.0) / total


def progress_bar(pct: float, size: int = 20) -> str:
    filled = round((pct / 100.0) * size)
    filled = max(0, min(size, filled))
    return "█" * filled + "░" * (size - filled)


def badge_color(pct: float) -> str:
    if pct >= 99.99:
        return "brightgreen"
    if pct >= 75.0:
        return "green"
    if pct >= 50.0:
        return "yellow"
    if pct >= 25.0:
        return "orange"
    return "red"


def shield_part(value: str) -> str:
    value = str(value).replace("-", "--")
    return quote(value, safe="")


def static_badge_url(label: str, message: str, color: str, version: str) -> str:
    return (
        "https://raster.shields.io/badge/"
        f"{shield_part(label)}-{shield_part(message)}-{shield_part(color)}"
        "?style=for-the-badge"
        "&cacheSeconds=60"
        f"&v={quote(version, safe='')}"
    )


def make_compare_url(server: str, repo: str, before: str, after: str) -> str:
    if before and not before.startswith("0000000"):
        return f"{server}/{repo}/compare/{before}...{after}"

    return f"{server}/{repo}/commit/{after}"


def send_to_discord(payload: dict) -> None:
    webhook = os.environ["DISCORD_WEBHOOK_URL"]

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        webhook,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "dd-y4-translation-progress",
        },
        method="POST",
    )

    with urllib.request.urlopen(request) as response:
        response.read()


def build_payload(
    per_user: dict,
    summary: dict,
    before: str,
    after: str,
    repo: str,
    server: str,
    branch: str,
    run_id: str,
) -> dict | None:
    entries_total = int(summary.get("entries_total", 0))
    entries_translated = int(summary.get("entries_translated", 0))
    entries_reviewed = int(summary.get("entries_reviewed", 0))

    pct_translated = float(summary.get("pct_translated", 0.0))
    pct_reviewed = float(summary.get("pct_reviewed", 0.0))
    pct_global = float(summary.get("pct_global", 0.0))

    compare_url = make_compare_url(server, repo, before, after)
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id else compare_url

    user_fields = []

    total_translated_now = 0
    total_reviewed_now = 0
    total_edited_now = 0

    for user, stats in sorted(per_user.items()):
        translated = stats["translated"]
        reviewed = stats["reviewed"]
        edited = stats["edited"]

        if translated == 0 and reviewed == 0 and edited == 0:
            continue

        total_translated_now += translated
        total_reviewed_now += reviewed
        total_edited_now += edited

        translated_gain = pct_gain(translated, entries_total)
        reviewed_gain = pct_gain(reviewed, entries_total)

        value = (
            f"Tradujo **{translated}** líneas en "
            f"**{len(stats['translated_files'])}** archivos\n"
            f"Traducción global: **{format_pct(pct_translated)}%** "
            f"(**+{format_pct(translated_gain)}%**)\n\n"
            f"Revisó **{reviewed}** líneas en "
            f"**{len(stats['reviewed_files'])}** archivos\n"
            f"Revisión global: **{format_pct(pct_reviewed)}%** "
            f"(**+{format_pct(reviewed_gain)}%**)\n\n"
            f"Ajustó **{edited}** traducciones existentes"
        )

        user_fields.append({
            "name": user,
            "value": value,
            "inline": False,
        })

    if not user_fields:
        return None

    description = (
        f"**Progreso global:** `{progress_bar(pct_global)}` "
        f"**{format_pct(pct_global)}%**\n"
        f"**Traducción:** `{progress_bar(pct_translated)}` "
        f"**{format_pct(pct_translated)}%** "
        f"({entries_translated}/{entries_total})\n"
        f"**Revisión:** `{progress_bar(pct_reviewed)}` "
        f"**{format_pct(pct_reviewed)}%** "
        f"({entries_reviewed}/{entries_total})"
    )

    version = after[:12]

    badge_global = static_badge_url(
        "progreso global",
        f"{format_pct(pct_global)}%",
        badge_color(pct_global),
        version,
    )

    badge_translation = static_badge_url(
        "traducción",
        f"{format_pct(pct_translated)}%",
        badge_color(pct_translated),
        version,
    )

    badge_review = static_badge_url(
        "revisión",
        f"{format_pct(pct_reviewed)}%",
        badge_color(pct_reviewed),
        version,
    )

    main_embed = {
        "title": "Progreso de traducción actualizado",
        "description": description,
        "url": compare_url,
        "color": 10165305,
        "fields": user_fields[:20] + [
            {
                "name": "Resumen de este envío",
                "value": (
                    f"Traducidas: **{total_translated_now}** líneas\n"
                    f"Revisadas: **{total_reviewed_now}** líneas\n"
                    f"Ajustadas: **{total_edited_now}** traducciones existentes\n"
                    f"[Ver cambios]({compare_url})\n"
                    f"[Ver workflow]({run_url})"
                ),
                "inline": False,
            }
        ],
        "footer": {
            "text": f"Rama: {branch} · Yakuza 4 es-419"
        },
    }

    payload = {
        "username": "Progreso de traducción",
        "embeds": [
            main_embed,
            {
                "url": compare_url,
                "image": {
                    "url": badge_global,
                },
            },
            {
                "url": compare_url,
                "image": {
                    "url": badge_translation,
                },
            },
            {
                "url": compare_url,
                "image": {
                    "url": badge_review,
                },
            },
        ],
    }

    return payload


def main() -> None:
    before = os.environ.get("BEFORE_SHA", "")
    after = os.environ.get("AFTER_SHA", "HEAD")

    repo = os.environ.get("GITHUB_REPOSITORY", "Kcat-art/DD-Y4-es419-translation")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    run_id = os.environ.get("GITHUB_RUN_ID", "")

    hidden_terms = load_hidden_terms()
    commits = get_commits(before, after)

    per_user = defaultdict(lambda: {
        "translated": 0,
        "translated_files": set(),
        "reviewed": 0,
        "reviewed_files": set(),
        "edited": 0,
        "edited_files": set(),
    })

    for commit in commits:
        parent = git("rev-parse", f"{commit}^", allow_fail=True).strip()

        if not parent:
            continue

        author = commit_author(commit)
        stats = count_commit_progress(parent, commit, hidden_terms)

        per_user[author]["translated"] += stats["translated"]
        per_user[author]["reviewed"] += stats["reviewed"]
        per_user[author]["edited"] += stats["edited"]

        per_user[author]["translated_files"].update(stats["translated_files"])
        per_user[author]["reviewed_files"].update(stats["reviewed_files"])
        per_user[author]["edited_files"].update(stats["edited_files"])

    summary = load_summary()

    payload = build_payload(
        per_user=per_user,
        summary=summary,
        before=before,
        after=after,
        repo=repo,
        server=server,
        branch=branch,
        run_id=run_id,
    )

    if payload is None:
        print("No hubo líneas traducidas, revisadas ni ajustadas para reportar.")
        return

    send_to_discord(payload)
    print("enviado a discord.")


if __name__ == "__main__":
    main()
