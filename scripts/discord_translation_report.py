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
    output: list[str] = []
    collecting = False
    for line in block.splitlines():
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
    return sorted({str(term).strip().lower() for term in terms if str(term).strip()})


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
    return file_reviewed


def parse_po_text(text: str, hidden_terms: list[str]) -> dict[tuple[str, str], dict]:
    entries: dict[tuple[str, str], dict] = {}
    file_statuses = FILE_STATUS_RE.findall(text)
    file_reviewed = any(normalize_status(status) == "reviewed" for status in file_statuses)

    for block in iter_po_blocks(text):
        if is_hidden_entry(block, hidden_terms):
            continue
        msgctxt = extract_po_field(block, "msgctxt")
        msgid = extract_po_field(block, "msgid")
        msgstr = extract_po_field(block, "msgstr")
        entries[(msgctxt, msgid)] = {
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
        "diff", "--name-status", "-M", "--diff-filter=ACMR",
        old_commit, new_commit, "--", "*.po", allow_fail=True,
    )
    pairs: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") or status.startswith("C"):
            if len(parts) >= 3:
                pairs.append((parts[1], parts[2]))
        elif len(parts) >= 2:
            pairs.append((parts[1], parts[1]))
    return pairs


def changed_texture_files(old_commit: str, new_commit: str) -> set[str]:
    output = git(
        "diff", "--name-only", "--diff-filter=ACMR",
        old_commit, new_commit, "--", "texturas/traducidas",
        allow_fail=True,
    )
    return {
        path.strip()
        for path in output.splitlines()
        if path.strip().lower().endswith(".dds")
        and path.strip().replace("\\", "/").startswith("texturas/traducidas/")
    }


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
        "textures": 0,
        "texture_files": set(),
    }

    for old_path, new_path in changed_po_file_pairs(old_commit, new_commit):
        old_entries = parse_po_text(file_at_commit(old_commit, old_path), hidden_terms)
        new_entries = parse_po_text(file_at_commit(new_commit, new_path), hidden_terms)

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
                old_translated and new_translated and old_entry
                and old_entry.get("msgstr", "") != new_entry.get("msgstr", "")
            ):
                stats["edited"] += 1
                stats["edited_files"].add(new_path)

            if not old_reviewed and new_reviewed:
                stats["reviewed"] += 1
                stats["reviewed_files"].add(new_path)

    texture_files = changed_texture_files(old_commit, new_commit)
    stats["texture_files"].update(texture_files)
    stats["textures"] = len(texture_files)
    return stats


def get_commits(before: str, after: str) -> list[str]:
    rev_range = f"{before}..{after}" if before and not before.startswith("0000000") else f"{after}^..{after}"
    commits = [line.strip() for line in git("rev-list", "--reverse", rev_range, allow_fail=True).splitlines() if line.strip()]
    return commits or [after]


def load_github_username_map() -> dict[str, str]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: dict[str, str] = {}
    for commit in event.get("commits", []):
        sha = commit.get("id")
        username = (commit.get("author") or {}).get("username")
        if sha and username:
            result[sha] = username
    return result


GITHUB_USERNAME_MAP = load_github_username_map()


def commit_author(commit: str) -> str:
    username = GITHUB_USERNAME_MAP.get(commit)
    if username:
        return username
    actor = os.environ.get("GITHUB_ACTOR")
    if actor:
        return actor
    return git("show", "-s", "--format=%an", commit, allow_fail=True).strip() or "Usuario desconocido"


def load_summary() -> dict:
    if not SUMMARY_PATH.exists():
        return {}
    try:
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def pct_gain(amount: int, total: int) -> float:
    return amount * 100.0 / total if total > 0 else 0.0


def load_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            pass
    return ImageFont.load_default()


# Mantener sin cambios la tarjeta visual de cuatro filas.
def create_progress_card(summary: dict, output_path: Path) -> None:
    width, height = 760, 262
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    title_font, label_font, value_font = load_font(26), load_font(23), load_font(17, True)
    draw.text((310, 8), "Progreso:", font=title_font, fill=(242, 242, 242))
    rows = [
        ("Traducción", as_float(summary.get("pct_translated", 0)), (65, 145, 255)),
        ("Revisión", as_float(summary.get("pct_reviewed", 0)), (72, 210, 105)),
        ("Texturas", as_float(summary.get("pct_textures", 0)), (218, 22, 205)),
        ("Progreso global", as_float(summary.get("pct_global", 0)), (238, 238, 238)),
    ]
    for index, (label, value, color) in enumerate(rows):
        y = 65 + index * 48
        draw.text((34, y), label, font=label_font, fill=(242, 242, 242))
        draw.rounded_rectangle([300, y + 7, 620, y + 25], radius=9, fill=(48, 49, 56))
        filled = int(320 * max(0, min(100, value)) / 100)
        if filled:
            draw.rounded_rectangle([300, y + 7, 300 + max(18, filled), y + 25], radius=9, fill=color)
        draw.text((635, y + 1), f"{format_pct(value)}%", font=value_font, fill=(242, 242, 242))
    image.save(output_path, "PNG")


def send_to_discord(payload: dict, image_path: Path) -> None:
    webhook = os.environ["DISCORD_WEBHOOK_URL"]
    boundary = f"----dd-y4-boundary-{uuid.uuid4().hex}"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(b'Content-Disposition: form-data; name="payload_json"\r\n')
    body.extend(b"Content-Type: application/json; charset=utf-8\r\n\r\n")
    body.extend(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(b'Content-Disposition: form-data; name="files[0]"; filename="progress_card.png"\r\n')
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(image_path.read_bytes())
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
    return repo_full.split("/")[-1] if repo_full else "el repositorio"


def build_title(users: list[str], repo_name: str) -> str:
    if len(users) == 1:
        return f"{users[0]} hizo cambios en {repo_name}"
    if len(users) == 2:
        return f"{users[0]} y {users[1]} hicieron cambios en {repo_name}"
    return f"{len(users)} usuarios hicieron cambios en {repo_name}"


def build_user_value(stats: dict, summary: dict) -> str:
    parts: list[str] = []
    entries_total = as_int(summary.get("entries_total", 0))
    pct_translated = as_float(summary.get("pct_translated", 0))
    pct_reviewed = as_float(summary.get("pct_reviewed", 0))

    translated = stats["translated"]
    reviewed = stats["reviewed"]
    textures = stats["textures"]
    edited = stats["edited"]

    if translated > 0:
        translated_files = len(stats["translated_files"])
        parts.append(
            f"Tradujo **{translated}** {plural(translated, 'línea')} "
            f"en **{translated_files}** {plural(translated_files, 'archivo')}\n"
            f"Traducción global: **{format_pct(pct_translated)}%** "
            f"(**+{format_pct(pct_gain(translated, entries_total))}%**)"
        )

    if reviewed > 0:
        reviewed_files = len(stats["reviewed_files"])
        parts.append(
            f"Revisó **{reviewed}** {plural(reviewed, 'línea')} "
            f"en **{reviewed_files}** {plural(reviewed_files, 'archivo')}\n"
            f"Revisión global: **{format_pct(pct_reviewed)}%** "
            f"(**+{format_pct(pct_gain(reviewed, entries_total))}%**)"
        )

    if textures > 0:
        parts.append(f"Subió **{textures}** {plural(textures, 'textura')}")

    if edited > 0:
        edited_files = len(stats["edited_files"])
        parts.append(
            f"Ajustó **{edited}** traducciones existentes "
            f"en **{edited_files}** {plural(edited_files, 'archivo')}"
        )

    return "\n\n".join(parts)


def build_payload(per_user: dict, summary: dict, branch: str, repo_full: str) -> dict | None:
    entries_total = as_int(summary.get("entries_total", 0))
    entries_translated = as_int(summary.get("entries_translated", 0))
    entries_reviewed = as_int(summary.get("entries_reviewed", 0))
    textures_total = as_int(summary.get("textures_total", 0))
    textures_completed = as_int(summary.get("textures_completed", 0))

    pct_translated = as_float(summary.get("pct_translated", 0))
    pct_reviewed = as_float(summary.get("pct_reviewed", 0))
    pct_textures = as_float(summary.get("pct_textures", 0))
    pct_global = as_float(summary.get("pct_global", 0))

    fields = []
    active_users = []
    for user, stats in sorted(per_user.items()):
        if not any(stats[key] for key in ("translated", "reviewed", "textures", "edited")):
            continue
        value = build_user_value(stats, summary)
        if not value.strip():
            continue
        active_users.append(user)
        fields.append({"name": user, "value": value, "inline": False})

    if not fields:
        return None

    description = (
        f"**Traducción:** **{format_pct(pct_translated)}%** "
        f"({entries_translated}/{entries_total})\n"
        f"**Revisión:** **{format_pct(pct_reviewed)}%** "
        f"({entries_reviewed}/{entries_total})\n"
        f"**Texturas:** **{format_pct(pct_textures)}%** "
        f"({textures_completed}/{textures_total})\n"
        f"**Progreso global:** **{format_pct(pct_global)}%**"
    )

    return {
        "username": "Dragones de Dojima",
        "embeds": [{
            "title": build_title(active_users, repo_display_name(repo_full)),
            "description": description,
            "color": 10165305,
            "fields": fields[:20],
            "image": {"url": "attachment://progress_card.png"},
            "footer": {"text": f"Rama: {branch} · Yakuza 4 es-419"},
        }],
    }


def main() -> None:
    before = os.environ.get("BEFORE_SHA", "")
    after = os.environ.get("AFTER_SHA", "HEAD")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    repo_full = os.environ.get("GITHUB_REPOSITORY", "Kcat-art/DD-Y4-es419-translation")
    hidden_terms = load_hidden_terms()

    per_user = defaultdict(lambda: {
        "translated": 0,
        "translated_files": set(),
        "reviewed": 0,
        "reviewed_files": set(),
        "edited": 0,
        "edited_files": set(),
        "textures": 0,
        "texture_files": set(),
    })

    for commit in get_commits(before, after):
        parent = git("rev-parse", f"{commit}^", allow_fail=True).strip()
        if not parent:
            continue
        user = commit_author(commit)
        stats = count_commit_progress(parent, commit, hidden_terms)
        for key in ("translated", "reviewed", "edited", "textures"):
            per_user[user][key] += stats[key]
        for key in ("translated_files", "reviewed_files", "edited_files", "texture_files"):
            per_user[user][key].update(stats[key])

    summary = load_summary()
    payload = build_payload(per_user, summary, branch, repo_full)
    if payload is None:
        print("No hubo líneas traducidas, revisadas, ajustadas ni texturas para reportar.")
        return

    card_path = ROOT / "progress_card.png"
    create_progress_card(summary, card_path)
    send_to_discord(payload, card_path)


if __name__ == "__main__":
    main()
