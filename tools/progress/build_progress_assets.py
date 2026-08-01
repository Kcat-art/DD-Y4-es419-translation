from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import ast
import json
import re

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "assets" / "progress"
HIDDEN_LINES_PATH = ROOT / "assets" / "companion" / "hidden_lines.json"
TEXTURE_ORIGINAL_ROOT = ROOT / "texturas" / "original"
TEXTURE_TRANSLATED_ROOT = ROOT / "texturas" / "traducidas"
TEXTURE_PROGRESS_PATH = ROOT / "texturas" / "progreso.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

LINE_STATUS_RE = re.compile(r'^#\.\s+(?:lineStatus\s*:\s*|y4:line_status\s*=\s*)(.+)$', re.MULTILINE | re.IGNORECASE)
FILE_STATUS_RE = re.compile(r'^#\.\s+(?:fileStatus\s*:\s*|y4:file_status\s*=\s*)(.+)$', re.MULTILINE | re.IGNORECASE)
REVIEWED_BY_RE = re.compile(r'^#\.\s+y4:reviewed_by\s*=\s*(.+)$', re.MULTILINE | re.IGNORECASE)
FIELD_START_RE = re.compile(r'^(msgctxt|msgid|msgstr)\s+(.+)$')


def format_pct(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def badge_color(pct: float) -> str:
    if pct >= 99.99: return "brightgreen"
    if pct >= 75.0: return "green"
    if pct >= 50.0: return "yellow"
    if pct >= 25.0: return "orange"
    return "red"


def normalize_status(value: str) -> str:
    return value.strip().strip('"').lower()


def normalize_texture_path(value: str) -> str:
    return value.replace("\\", "/").strip().lstrip("/").casefold()


def po_unquote(value: str) -> str:
    value = value.strip()
    if not value.startswith('"'): return ""
    try: return ast.literal_eval(value)
    except Exception: return value.strip('"')


def extract_po_field(block: str, field_name: str) -> str:
    output, collecting = [], False
    for line in block.splitlines():
        match = FIELD_START_RE.match(line)
        if match:
            collecting = match.group(1) == field_name
            if collecting: output.append(po_unquote(match.group(2)))
            continue
        if collecting and line.strip().startswith('"'):
            output.append(po_unquote(line.strip())); continue
        if collecting and (line.startswith('#') or not line.strip()): continue
        if collecting: break
    return "".join(output)


def iter_entries(text: str):
    for block in re.split(r'\n\s*\n', text):
        if not block.strip(): continue
        lines = block.splitlines()
        if any(line.startswith('msgid ""') for line in lines[:4]): continue
        if "msgid " in block and "msgstr " in block: yield block


def load_hidden_terms() -> list[str]:
    if not HIDDEN_LINES_PATH.exists(): return []
    try: data = json.loads(HIDDEN_LINES_PATH.read_text(encoding="utf-8"))
    except Exception: return []
    terms = data.get("blocked_terms", [])
    return sorted({str(term).strip().lower() for term in terms if str(term).strip()}) if isinstance(terms, list) else []


def parse_po(path: Path, hidden_terms: list[str]):
    text = path.read_text(encoding="utf-8", errors="replace")
    total = translated = reviewed = hidden = 0
    file_reviewed = any(normalize_status(status) == "reviewed" for status in FILE_STATUS_RE.findall(text))
    for block in iter_entries(text):
        haystack = "\n".join(extract_po_field(block, field) for field in ("msgctxt", "msgid", "msgstr")).lower()
        if any(term in haystack for term in hidden_terms): hidden += 1; continue
        total += 1
        if extract_po_field(block, "msgstr") != "": translated += 1
        statuses = LINE_STATUS_RE.findall(block)
        if (statuses and normalize_status(statuses[-1]) == "reviewed") or REVIEWED_BY_RE.search(block) or file_reviewed:
            reviewed += 1
    return total, translated, reviewed, hidden


def classify_area(repo_relative: str) -> str | None:
    path = repo_relative.replace("\\", "/").lower()
    if path.startswith("data/auth/subtitle/"): return "Cinemáticas"
    if "/msg/" in path: return "Diálogos"
    return None


def load_no_translation_needed() -> set[str]:
    if not TEXTURE_PROGRESS_PATH.exists(): return set()
    try: data = json.loads(TEXTURE_PROGRESS_PATH.read_text(encoding="utf-8"))
    except Exception: return set()
    paths = data.get("no_translation_needed_paths", [])
    return {normalize_texture_path(str(path)) for path in paths if str(path).strip()} if isinstance(paths, list) else set()


def collect_texture_progress() -> dict:
    originals = {
        normalize_texture_path(path.relative_to(TEXTURE_ORIGINAL_ROOT).as_posix())
        for path in TEXTURE_ORIGINAL_ROOT.rglob("*.dds")
        if path.is_file()
    } if TEXTURE_ORIGINAL_ROOT.exists() else set()
    translated = {
        normalize_texture_path(path.relative_to(TEXTURE_TRANSLATED_ROOT).as_posix())
        for path in TEXTURE_TRANSLATED_ROOT.rglob("*.dds")
        if path.is_file()
    } if TEXTURE_TRANSLATED_ROOT.exists() else set()
    translated &= originals
    no_translation_needed = load_no_translation_needed() & originals
    completed = translated | no_translation_needed
    total = len(originals)
    return {
        "total": total,
        "translated": len(translated),
        "no_translation_needed": len(no_translation_needed),
        "completed": len(completed),
        "pending": max(0, total - len(completed)),
        "pct": round(len(completed) * 100.0 / total, 2) if total else 0.0,
    }


def global_pct(translated: int, reviewed: int, entries_total: int, textures_completed: int, textures_total: int) -> float:
    total_units = (2 * entries_total) + textures_total
    return ((translated + reviewed + textures_completed) * 100.0 / total_units) if total_units else 0.0


def make_badge(label: str, pct: float) -> dict:
    return {"schemaVersion": 1, "label": label, "message": f"{format_pct(pct)}%", "color": badge_color(pct), "cacheSeconds": 300}


def build_readme(summary: dict, areas: dict) -> str:
    lines = [
        "## Progreso del proyecto", "",
        f"**Traducción global:** {summary['entries_translated']}/{summary['entries_total']} ({format_pct(summary['pct_translated'])}%)",
        f"**Revisión global:** {summary['entries_reviewed']}/{summary['entries_total']} ({format_pct(summary['pct_reviewed'])}%)",
        f"**Texturas:** {summary['textures_completed']}/{summary['textures_total']} ({format_pct(summary['pct_textures'])}%)",
        f"**Progreso global:** {format_pct(summary['pct_global'])}%", "",
        "| Área | Traducción | Revisión |", "|---|---:|---:|",
    ]
    for name in ("Diálogos", "Cinemáticas"):
        if name in areas:
            data = areas[name]
            lines.append(f"| {name} | {data['translated']}/{data['total']} ({format_pct(data['pct_translated'])}%) | {data['reviewed']}/{data['total']} ({format_pct(data['pct_reviewed'])}%) |")
    return "\n".join(lines) + "\n"


def main() -> None:
    hidden_terms = load_hidden_terms()
    po_files = [po for po in ROOT.rglob("*.po") if not any(part in {".git", "cache", "backups"} for part in po.parts)]
    files_total = files_translated = files_reviewed = 0
    entries_total = entries_translated = entries_reviewed = entries_hidden = 0
    areas = defaultdict(lambda: {"files_total": 0, "files_translated": 0, "files_reviewed": 0, "total": 0, "translated": 0, "reviewed": 0, "hidden": 0})

    for po in po_files:
        total, translated, reviewed, hidden = parse_po(po, hidden_terms)
        files_total += 1; entries_total += total; entries_translated += translated; entries_reviewed += reviewed; entries_hidden += hidden
        if total and reviewed == total: files_reviewed += 1
        elif total and translated == total: files_translated += 1
        area = classify_area(po.relative_to(ROOT).as_posix())
        if area:
            data = areas[area]
            data["files_total"] += 1; data["total"] += total; data["translated"] += translated; data["reviewed"] += reviewed; data["hidden"] += hidden
            if total and reviewed == total: data["files_reviewed"] += 1
            elif total and translated == total: data["files_translated"] += 1

    textures = collect_texture_progress()
    pct_translated = entries_translated * 100.0 / entries_total if entries_total else 0.0
    pct_reviewed = entries_reviewed * 100.0 / entries_total if entries_total else 0.0
    areas_out = {}
    for name, data in areas.items():
        areas_out[name] = {**data, "pct_translated": round(data["translated"] * 100.0 / data["total"], 2) if data["total"] else 0.0, "pct_reviewed": round(data["reviewed"] * 100.0 / data["total"], 2) if data["total"] else 0.0}

    summary = {
        "files_total": files_total, "files_translated": files_translated, "files_reviewed": files_reviewed,
        "entries_total": entries_total, "entries_translated": entries_translated, "entries_reviewed": entries_reviewed,
        "entries_hidden": entries_hidden, "hidden_terms_count": len(hidden_terms),
        "pct_translated": round(pct_translated, 2), "pct_reviewed": round(pct_reviewed, 2),
        "textures_total": textures["total"], "textures_translated": textures["translated"],
        "textures_no_translation_needed": textures["no_translation_needed"], "textures_completed": textures["completed"],
        "textures_pending": textures["pending"], "pct_textures": textures["pct"],
        "pct_global": round(global_pct(entries_translated, entries_reviewed, entries_total, textures["completed"], textures["total"]), 2),
        "areas": areas_out,
    }

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for filename, label, pct in (
        ("translation_badge.json", "traducción", summary["pct_translated"]),
        ("review_badge.json", "revisión", summary["pct_reviewed"]),
        ("texture_badge.json", "texturas", summary["pct_textures"]),
        ("global_badge.json", "progreso global", summary["pct_global"]),
    ):
        (OUT_DIR / filename).write_text(json.dumps(make_badge(label, pct), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT_DIR / "readme_progress.md").write_text(build_readme(summary, areas_out), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
