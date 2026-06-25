from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import urllib.request
import uuid
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
HIDDEN_LINES_PATH = ROOT / "assets" / "companion" / "hidden_lines.json"
SUMMARY_PATH = ROOT / "assets" / "progress" / "summary.json"

FIELD_START_RE = re.compile(r'^(msgctxt|msgid|msgstr(?:\[\d+\])?)\s+(.+)$')

LINE_STATUS_RE = re.compile(
    r'^#\.\s+(?:lineStatus\s*:\s*|line_status\s*=\s*|y4:line_status\s*=\s*)(.+)$',
    re.MULTILINE | re.IGNORECASE,
)

FILE_STATUS_RE = re.compile(
    r'^#\.\s+(?:fileStatus\s*:\s*|file_status\s*=\s*|y4:file_status\s*=\s*)(.+)$',
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


def as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def as_float(value, default: float = 0.0) -> float:
    try:
        return float(str(value).strip().replace("%", "").replace(",", "."))
    except Exception:
        return default


def format_pct(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    if n == 1:
        return singular
    return plural_form or f"{singular}s"


def extract_po_field(block: str, field_name: str) -> str:
    lines = block.splitlines()
    output: list[str] = []
    collecting = False

    for line in lines:
        match = FIELD_START_RE.match(line)

        if match:
            current_field = match.group(1)

            if current_field.startswith("msgstr"):
                current_field = "msgstr"

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

        if 'msgid ""' in block and "Project-Id-Version" in block:
            continue

        if "msgid " not in block or "msgstr" not in block:
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

    username_map: dict[str, str] = {}

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


def pct_gain(lines: int, total: int) -> float:
    if total <= 0:
        return 0.0

    return (lines * 100.0) / total


def load_font(size: int, bold: bool = False):
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass

    return ImageFont.load_default()


def draw_bar(draw, x: int, y: int, width: int, height: int, pct: float, fill, bg) -> None:
    pct = max(0.0, min(100.0, float(pct)))
    radius = height // 2

    draw.rounded_rectangle(
        [x, y, x + width, y + height],
        radius=radius,
        fill=bg,
    )

    filled = int(round(width * (pct / 100.0)))

    if filled > 0:
        filled = max(filled, height)

        draw.rounded_rectangle(
            [x, y, x + filled, y + height],
            radius=radius,
            fill=fill,
        )


def create_progress_card(summary: dict, output_path: Path) -> None:
    width = 760
    height = 210

    bg = (0, 0, 0)
    line = (28, 28, 30)

    text = (242, 242, 242)
    muted = (165, 165, 165)

    translation_color = (65, 145, 255)
    review_color = (72, 210, 105)
    global_color = (238, 238, 238)

    marker_color = (218, 22, 205)
    track_color = (48, 49, 56)

    entries_total = as_int(summary.get("entries_total", 0))
    entries_translated = as_int(summary.get("entries_translated", 0))
    entries_reviewed = as_int(summary.get("entries_reviewed", 0))

    pct_translated = as_float(summary.get("pct_translated", 0.0))
    pct_reviewed = as_float(summary.get("pct_reviewed", 0.0))
    pct_global = as_float(summary.get("pct_global", 0.0))

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    title_font = load_font(26, bold=False)
    label_font = load_font(25, bold=False)
    value_font = load_font(18, bold=True)
    count_font = load_font(12, bold=False)

    title = "Progreso:"
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]

    draw.text(((width - title_w) // 2, 8), title, font=title_font, fill=text)
    draw.line([0, 45, width, 45], fill=line, width=2)

    rows = [
        ("Traducción", pct_translated, f"{entries_translated}/{entries_total}", translation_color),
        ("Revisión", pct_reviewed, f"{entries_reviewed}/{entries_total}", review_color),
        ("Progreso global", pct_global, "", global_color),
    ]

    start_y = 72
    row_gap = 52

    marker_x = 18
    label_x = 34

    bar_x = 310
    bar_y_offset = 10
    bar_w = 310
    bar_h = 18

    value_x = 635

    for index, (label, pct, detail, color) in enumerate(rows):
        y = start_y + index * row_gap

        draw.line([0, y - 13, width, y - 13], fill=line, width=2)

        draw.rounded_rectangle(
            [marker_x, y + 1, marker_x + 8, y + 29],
            radius=4,
            fill=marker_color,
        )

        draw.text((label_x, y - 2), label, font=label_font, fill=text)

        draw_bar(
            draw=draw,
            x=bar_x,
            y=y + bar_y_offset,
            width=bar_w,
            height=bar_h,
            pct=pct,
            fill=color,
            bg=track_color,
        )

        draw.text(
            (value_x, y + 2),
            f"{format_pct(pct)}%",
            font=value_font,
            fill=text,
        )

        if detail:
            draw.text((value_x, y + 24), detail, font=count_font, fill=muted)

    img.save(output_path, "PNG")


def send_to_discord(payload: dict, image_path: Path | None = None) -> None:
    webhook = os.environ["DISCORD_WEBHOOK_URL"]

    if image_path is None:
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

        return

    boundary = f"----dd-y4-boundary-{uuid.uuid4().hex}"
    payload_json = json.dumps(payload, ensure_ascii=False)

    file_bytes = image_path.read_bytes()
    file_name = image_path.name

    body = bytearray()

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(b'Content-Disposition: form-data; name="payload_json"\r\n')
    body.extend(b"Content-Type: application/json; charset=utf-8\r\n\r\n")
    body.extend(payload_json.encode("utf-8"))
    body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        f'Content-Disposition: form-data; name="files[0]"; filename="{file_name}"\r\n'.encode("utf-8")
    )
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(file_bytes)
    body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    request = urllib.request.Request(
        webhook,
        data=bytes(body),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "dd-y4-translation-progress",
        },
        method="POST",
    )

    with urllib.request.urlopen(request) as response:
        response.read()


def repo_display_name(repo_full: str) -> str:
    if not repo_full:
        return "el repositorio"

    return repo_full.split("/")[-1]


def build_title(users: list[str], repo_name: str) -> str:
    if len(users) == 1:
        return f"{users[0]} hizo cambios en {repo_name}"

    if len(users) == 2:
        return f"{users[0]} y {users[1]} hicieron cambios en {repo_name}"

    return f"{len(users)} usuarios hicieron cambios en {repo_name}"


def build_user_value(stats: dict, entries_total: int, pct_translated: float, pct_reviewed: float) -> str:
    parts = []

    translated = stats["translated"]
    reviewed = stats["reviewed"]
    edited = stats["edited"]

    translated_files = len(stats["translated_files"])
    reviewed_files = len(stats["reviewed_files"])
    edited_files = len(stats["edited_files"])

    if translated > 0:
        translated_gain = pct_gain(translated, entries_total)

        parts.append(
            f"Tradujo **{translated}** {plural(translated, 'línea')} "
            f"en **{translated_files}** {plural(translated_files, 'archivo')}\n"
            f"Traducción global: **{format_pct(pct_translated)}%** "
            f"(**+{format_pct(translated_gain)}%**)"
        )

    if reviewed > 0:
        reviewed_gain = pct_gain(reviewed, entries_total)

        parts.append(
            f"Revisó **{reviewed}** {plural(reviewed, 'línea')} "
            f"en **{reviewed_files}** {plural(reviewed_files, 'archivo')}\n"
            f"Revisión global: **{format_pct(pct_reviewed)}%** "
            f"(**+{format_pct(reviewed_gain)}%**)"
        )

    if edited > 0:
        parts.append(
            f"Ajustó **{edited}** traducciones existentes "
            f"en **{edited_files}** {plural(edited_files, 'archivo')}"
        )

    return "\n\n".join(parts)


def build_payload(
    per_user: dict,
    summary: dict,
    branch: str,
    repo_full: str,
) -> dict | None:
    entries_total = as_int(summary.get("entries_total", 0))
    entries_translated = as_int(summary.get("entries_translated", 0))
    entries_reviewed = as_int(summary.get("entries_reviewed", 0))

    pct_translated = as_float(summary.get("pct_translated", 0.0))
    pct_reviewed = as_float(summary.get("pct_reviewed", 0.0))
    pct_global = as_float(summary.get("pct_global", 0.0))

    user_fields = []
    active_users = []

    for user, stats in sorted(per_user.items()):
        translated = stats["translated"]
        reviewed = stats["reviewed"]
        edited = stats["edited"]

        if translated == 0 and reviewed == 0 and edited == 0:
            continue

        value = build_user_value(
            stats=stats,
            entries_total=entries_total,
            pct_translated=pct_translated,
            pct_reviewed=pct_reviewed,
        )

        if not value.strip():
            continue

        active_users.append(user)

        user_fields.append({
            "name": user,
            "value": value,
            "inline": False,
        })

    if not user_fields:
        return None

    repo_name = repo_display_name(repo_full)

    description = (
        f"**Traducción:** **{format_pct(pct_translated)}%** "
        f"({entries_translated}/{entries_total})\n"
        f"**Revisión:** **{format_pct(pct_reviewed)}%** "
        f"({entries_reviewed}/{entries_total})\n"
        f"**Progreso global:** **{format_pct(pct_global)}%**"
    )

    payload = {
        "username": "Dragones de Dojima",
        "embeds": [
            {
                "title": build_title(active_users, repo_name),
                "description": description,
                "color": 10165305,
                "fields": user_fields[:20],
                "image": {
                    "url": "attachment://progress_card.png",
                },
                "footer": {
                    "text": f"Rama: {branch} · Yakuza 4 es-419",
                },
            }
        ],
    }

    return payload


def main() -> None:
    before = os.environ.get("BEFORE_SHA", "")
    after = os.environ.get("AFTER_SHA", "HEAD")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    repo_full = os.environ.get("GITHUB_REPOSITORY", "Kcat-art/DD-Y4-es419-translation")

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
        branch=branch,
        repo_full=repo_full,
    )

    if payload is None:
        print("No hubo líneas traducidas, revisadas ni ajustadas para reportar.")
        return

    card_path = ROOT / "progress_card.png"
    create_progress_card(summary, card_path)

    send_to_discord(payload, card_path)


if __name__ == "__main__":
    main()
