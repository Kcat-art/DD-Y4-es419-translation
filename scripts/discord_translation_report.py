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
SUMMARY_PATH = ROOT / "assets" / "progress" / "summary.json"
HIDDEN_LINES_PATH = ROOT / "assets" / "companion" / "hidden_lines.json"
FIELD_START_RE = re.compile(r'^(msgctxt|msgid|msgstr(?:\[\d+\])?)\s+(.+)$')
LINE_STATUS_RE = re.compile(r'^#\.\s+(?:lineStatus\s*:\s*|line_status\s*=\s*|y4:line_status\s*=\s*)(.+)$', re.MULTILINE | re.IGNORECASE)
FILE_STATUS_RE = re.compile(r'^#\.\s+(?:fileStatus\s*:\s*|file_status\s*=\s*|y4:file_status\s*=\s*)(.+)$', re.MULTILINE | re.IGNORECASE)
REVIEWED_BY_RE = re.compile(r'^#\.\s+y4:reviewed_by\s*=\s*(.+)$', re.MULTILINE | re.IGNORECASE)


def git(*args: str, allow_fail: bool = False) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode and not allow_fail: raise RuntimeError(result.stderr.strip())
    return result.stdout if result.returncode == 0 else ""


def po_unquote(value: str) -> str:
    try: return ast.literal_eval(value.strip()) if value.strip().startswith('"') else ""
    except Exception: return value.strip().strip('"')


def extract_field(block: str, field: str) -> str:
    out, collecting = [], False
    for line in block.splitlines():
        match = FIELD_START_RE.match(line)
        if match:
            current = "msgstr" if match.group(1).startswith("msgstr") else match.group(1)
            collecting = current == field
            if collecting: out.append(po_unquote(match.group(2)))
            continue
        if collecting and line.strip().startswith('"'): out.append(po_unquote(line.strip())); continue
        if collecting and (line.startswith('#') or not line.strip()): continue
        if collecting: break
    return "".join(out)


def parse_po(text: str) -> dict[tuple[str, str], dict]:
    entries = {}
    file_reviewed = any(status.strip().strip('"').lower() == "reviewed" for status in FILE_STATUS_RE.findall(text))
    hidden = []
    if HIDDEN_LINES_PATH.exists():
        try: hidden = [str(x).lower() for x in json.loads(HIDDEN_LINES_PATH.read_text(encoding="utf-8")).get("blocked_terms", [])]
        except Exception: pass
    for block in re.split(r'\n\s*\n', text):
        if "msgid " not in block or "msgstr" not in block or ('msgid ""' in block and "Project-Id-Version" in block): continue
        msgctxt, msgid, msgstr = (extract_field(block, x) for x in ("msgctxt", "msgid", "msgstr"))
        if any(term in f"{msgctxt}\n{msgid}\n{msgstr}".lower() for term in hidden): continue
        statuses = LINE_STATUS_RE.findall(block)
        reviewed = bool((statuses and statuses[-1].strip().strip('"').lower() == "reviewed") or REVIEWED_BY_RE.search(block) or file_reviewed)
        entries[(msgctxt, msgid)] = {"msgstr": msgstr, "translated": bool(msgstr.strip()), "reviewed": reviewed}
    return entries


def file_at(commit: str, path: str) -> str:
    return git("show", f"{commit}:{path}", allow_fail=True) if commit else ""


def changed_files(old: str, new: str, patterns: list[str]) -> list[str]:
    output = git("diff", "--name-only", "--diff-filter=ACMR", old, new, "--", *patterns, allow_fail=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def count_commit(old: str, new: str) -> dict:
    stats = {"translated": 0, "reviewed": 0, "edited": 0, "translated_files": set(), "reviewed_files": set(), "edited_files": set(), "textures": 0, "texture_files": set()}
    for path in changed_files(old, new, ["*.po"]):
        before, after = parse_po(file_at(old, path)), parse_po(file_at(new, path))
        for key, current in after.items():
            previous = before.get(key)
            if not (previous and previous["translated"]) and current["translated"]:
                stats["translated"] += 1; stats["translated_files"].add(path)
            elif previous and previous["translated"] and current["translated"] and previous["msgstr"] != current["msgstr"]:
                stats["edited"] += 1; stats["edited_files"].add(path)
            if not (previous and previous["reviewed"]) and current["reviewed"]:
                stats["reviewed"] += 1; stats["reviewed_files"].add(path)
    textures = changed_files(old, new, ["texturas/traducidas/**/*.dds", "texturas/traducidas/*.dds"])
    stats["texture_files"].update(textures)
    stats["textures"] = len(stats["texture_files"])
    return stats


def commits_between(before: str, after: str) -> list[str]:
    range_spec = f"{before}..{after}" if before and not before.startswith("0000000") else f"{after}^..{after}"
    commits = [line for line in git("rev-list", "--reverse", range_spec, allow_fail=True).splitlines() if line]
    return commits or [after]


def author(commit: str) -> str:
    return os.environ.get("GITHUB_ACTOR") or git("show", "-s", "--format=%an", commit, allow_fail=True).strip() or "Usuario desconocido"


def number(summary: dict, key: str) -> int:
    try: return int(summary.get(key, 0))
    except Exception: return 0


def pct(summary: dict, key: str) -> float:
    try: return float(str(summary.get(key, 0)).replace(",", ".").replace("%", ""))
    except Exception: return 0.0


def fmt(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def load_font(size: int, bold: bool = False):
    candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for candidate in candidates:
        try: return ImageFont.truetype(candidate, size)
        except Exception: pass
    return ImageFont.load_default()


def create_card(summary: dict, path: Path) -> None:
    width, height = 760, 262
    image = Image.new("RGB", (width, height), (0, 0, 0)); draw = ImageDraw.Draw(image)
    title_font, label_font, value_font = load_font(26), load_font(23), load_font(17, True)
    draw.text((310, 8), "Progreso:", font=title_font, fill=(242, 242, 242))
    rows = [
        ("Traducción", pct(summary, "pct_translated"), (65,145,255)),
        ("Revisión", pct(summary, "pct_reviewed"), (72,210,105)),
        ("Texturas", pct(summary, "pct_textures"), (218,22,205)),
        ("Progreso global", pct(summary, "pct_global"), (238,238,238)),
    ]
    for index, (label, value, color) in enumerate(rows):
        y = 65 + index * 48
        draw.text((34, y), label, font=label_font, fill=(242,242,242))
        draw.rounded_rectangle([300, y+7, 620, y+25], radius=9, fill=(48,49,56))
        filled = int(320 * max(0, min(100, value)) / 100)
        if filled: draw.rounded_rectangle([300, y+7, 300+max(18, filled), y+25], radius=9, fill=color)
        draw.text((635, y+1), f"{fmt(value)}%", font=value_font, fill=(242,242,242))
    image.save(path, "PNG")


def send(payload: dict, image_path: Path) -> None:
    webhook = os.environ["DISCORD_WEBHOOK_URL"]
    boundary = f"----dd-y4-{uuid.uuid4().hex}"
    body = bytearray()
    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n".encode())
    body.extend(json.dumps(payload, ensure_ascii=False).encode()); body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"progress_card.png\"\r\nContent-Type: image/png\r\n\r\n".encode())
    body.extend(image_path.read_bytes()); body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(webhook, data=bytes(body), headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "dd-y4-progress"}, method="POST")
    with urllib.request.urlopen(request) as response: response.read()


def main() -> None:
    before, after = os.environ.get("BEFORE_SHA", ""), os.environ.get("AFTER_SHA", "HEAD")
    per_user = defaultdict(lambda: {"translated":0,"reviewed":0,"edited":0,"textures":0,"translated_files":set(),"reviewed_files":set(),"edited_files":set(),"texture_files":set()})
    for commit in commits_between(before, after):
        parent = git("rev-parse", f"{commit}^", allow_fail=True).strip()
        if not parent: continue
        stats = count_commit(parent, commit); user = author(commit)
        for key in ("translated", "reviewed", "edited", "textures"): per_user[user][key] += stats[key]
        for key in ("translated_files", "reviewed_files", "edited_files", "texture_files"): per_user[user][key].update(stats[key])

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8")) if SUMMARY_PATH.exists() else {}
    fields, active = [], []
    for user, stats in sorted(per_user.items()):
        parts = []
        if stats["translated"]: parts.append(f"Tradujo **{stats['translated']}** línea(s) en **{len(stats['translated_files'])}** archivo(s)")
        if stats["reviewed"]: parts.append(f"Revisó **{stats['reviewed']}** línea(s) en **{len(stats['reviewed_files'])}** archivo(s)")
        if stats["textures"]: parts.append(f"Subió **{stats['textures']}** textura(s)")
        if stats["edited"]: parts.append(f"Ajustó **{stats['edited']}** traducción(es) existente(s)")
        if parts: active.append(user); fields.append({"name": user, "value": "\n\n".join(parts), "inline": False})
    if not fields:
        print("No hubo traducciones, revisiones ni texturas para reportar."); return

    title = f"{active[0]} hizo cambios" if len(active) == 1 else f"{len(active)} usuarios hicieron cambios"
    description = (
        f"**Traducción:** **{fmt(pct(summary,'pct_translated'))}%** ({number(summary,'entries_translated')}/{number(summary,'entries_total')})\n"
        f"**Revisión:** **{fmt(pct(summary,'pct_reviewed'))}%** ({number(summary,'entries_reviewed')}/{number(summary,'entries_total')})\n"
        f"**Texturas:** **{fmt(pct(summary,'pct_textures'))}%** ({number(summary,'textures_completed')}/{number(summary,'textures_total')})\n"
        f"**Progreso global:** **{fmt(pct(summary,'pct_global'))}%**"
    )
    payload = {"username":"Dragones de Dojima","embeds":[{"title":title,"description":description,"color":10165305,"fields":fields[:20],"image":{"url":"attachment://progress_card.png"},"footer":{"text":f"Rama: {os.environ.get('GITHUB_REF_NAME','main')} · Yakuza 4 es-419"}}]}
    card = ROOT / "progress_card.png"; create_card(summary, card); send(payload, card)


if __name__ == "__main__":
    main()
