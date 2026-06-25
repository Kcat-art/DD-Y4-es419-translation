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


def draw_bar(draw, x: int, y: int, width: int, height: int, pct: float, fill, bg, border) -> None:
    pct = max(0.0, min(100.0, float(pct)))
    radius = height // 2

    draw.rounded_rectangle(
        [x, y, x + width, y + height],
        radius=radius,
        fill=bg,
        outline=border,
        width=1,
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
    width = 980
    height = 360

    bg = (15, 17, 21)
    panel = (25, 27, 34)
    border = (55, 59, 70)

    text_main = (242, 243, 245)
    text_soft = (176, 181, 191)
    text_dim = (135, 141, 154)

    translation_color = (76, 163, 255)
    review_color = (88, 201, 116)
    global_color = (238, 238, 238)

    track_color = (56, 60, 70)

    entries_total = as_int(summary.get("entries_total", 0))
    entries_translated = as_int(summary.get("entries_translated", 0))
    entries_reviewed = as_int(summary.get("entries_reviewed", 0))

    pct_translated = as_float(summary.get("pct_translated", 0.0))
    pct_reviewed = as_float(summary.get("pct_reviewed", 0.0))
    pct_global = as_float(summary.get("pct_global", 0.0))

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    title_font = load_font(34, bold=True)
    subtitle_font = load_font(18)
    label_font = load_font(24, bold=True)
    value_font = load_font(24, bold=True)
    detail_font = load_font(17)

    draw.rounded_rectangle(
        [20, 20, width - 20, height - 20],
        radius=24,
        fill=panel,
        outline=border,
        width=1,
    )

    draw.text((46, 42), "Yakuza 4 es-419", font=title_font, fill=text_main)
    draw.text(
        (46, 84),
        "Progreso actual de traducción",
        font=subtitle_font,
        fill=text_soft,
    )

    rows = [
        (
            "Traducción",
            pct_translated,
            f"{entries_translated}/{entries_total}",
            translation_color,
        ),
        (
            "Revisión",
            pct_reviewed,
            f"{entries_reviewed}/{entries_total}",
            review_color,
        ),
        (
            "Progreso global",
            pct_global,
            "",
            global_color,
        ),
    ]

    start_y = 140
    row_gap = 72

    label_x = 46
    bar_x = 300
    bar_w = 500
    bar_h = 20

    pct_x = 835
    detail_x = 835

    for index, (label, pct, detail, color) in enumerate(rows):
        y = start_y + index * row_gap

        draw.text((label_x, y), label, font=label_font, fill=text_main)

        draw_bar(
            draw=draw,
            x=bar_x,
            y=y + 8,
            width=bar_w,
            height=bar_h,
            pct=pct,
            fill=color,
            bg=track_color,
            border=track_color,
        )

        pct_text = f"{format_pct(pct)}%"
        draw.text((pct_x, y), pct_text, font=value_font, fill=text_main)

        if detail:
            draw.text((detail_x, y + 30), detail, font=detail_font, fill=text_dim)

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


def build_payload(
    per_user: dict,
    summary: dict,
    branch: str,
) -> dict | None:
    entries_total = as_int(summary.get("entries_total", 0))
    entries_translated = as_int(summary.get("entries_translated", 0))
    entries_reviewed = as_int(summary.get("entries_reviewed", 0))

    pct_translated = as_float(summary.get("pct_translated", 0.0))
    pct_reviewed = as_float(summary.get("pct_reviewed", 0.0))
    pct_global = as_float(summary.get("pct_global", 0.0))

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

        translated_files = len(stats["translated_files"])
        reviewed_files = len(stats["reviewed_files"])

        value = (
            f"Tradujo **{translated}** {plural(translated, 'línea')} "
            f"en **{translated_files}** {plural(translated_files, 'archivo')}\n"
            f"Traducción global: **{format_pct(pct_translated)}%** "
            f"(**+{format_pct(translated_gain)}%**)\n\n"
            f"Revisó **{reviewed}** {plural(reviewed, 'línea')} "
            f"en **{reviewed_files}** {plural(reviewed_files, 'archivo')}\n"
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
        f"**Traducción:** **{format_pct(pct_translated)}%** "
        f"({entries_translated}/{entries_total})\n"
        f"**Revisión:** **{format_pct(pct_reviewed)}%** "
        f"({entries_reviewed}/{entries_total})\n"
        f"**Progreso global:** **{format_pct(pct_global)}%**"
    )

    summary_value = (
        f"Traducidas: **{total_translated_now}** "
        f"{plural(total_translated_now, 'línea')}\n"
        f"Revisadas: **{total_reviewed_now}** "
        f"{plural(total_reviewed_now, 'línea')}\n"
        f"Ajustadas: **{total_edited_now}** traducciones existentes"
    )

    payload = {
        "username": "Dragones de Dojima",
        "embeds": [
            {
                "title": "Progreso de traducción actualizado",
                "description": description,
                "color": 10165305,
                "fields": user_fields[:20] + [
                    {
                        "name": "Resumen de este envío",
                        "value": summary_value,
                        "inline": False,
                    }
                ],
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
    )

    if payload is None:
        print("No hubo líneas traducidas, revisadas ni ajustadas para reportar.")
        return

    card_path = ROOT / "progress_card.png"
    create_progress_card(summary, card_path)

    send_to_discord(payload, card_path)
    print("Reporte enviado a Discord.")


if __name__ == "__main__":
    main()
