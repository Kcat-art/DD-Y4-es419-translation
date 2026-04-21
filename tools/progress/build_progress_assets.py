from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
PO_ROOT = ROOT / "data" / "wdr_par_en" / "wdr" / "msg"
OUT_DIR = ROOT / "assets" / "progress"


def decode_po_string(token: str) -> str:
    token = token.strip()
    if not token.startswith('"'):
        return ""
    try:
        return json.loads(token)
    except Exception:
        return token.strip('"')


def parse_po_entries(path: Path) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    current = {"msgid": None, "msgstr": "", "status": "todo"}
    active_field = None

    def flush() -> None:
        nonlocal current, active_field
        if current["msgid"] is None:
            active_field = None
            return
        if current["msgid"] == "":
            current = {"msgid": None, "msgstr": "", "status": "todo"}
            active_field = None
            return
        entries.append({
            "msgid": current["msgid"],
            "msgstr": current["msgstr"],
            "status": current["status"],
        })
        current = {"msgid": None, "msgstr": "", "status": "todo"}
        active_field = None

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("#. y4:status="):
            current["status"] = stripped.split("=", 1)[1].strip() or "todo"
            continue

        if stripped.startswith("msgid "):
            if current["msgid"] is not None:
                flush()
            current["msgid"] = decode_po_string(stripped[6:])
            active_field = "msgid"
            continue

        if stripped.startswith("msgstr "):
            current["msgstr"] = decode_po_string(stripped[7:])
            active_field = "msgstr"
            continue

        if stripped.startswith('"'):
            value = decode_po_string(stripped)
            if active_field == "msgid" and current["msgid"] is not None:
                current["msgid"] += value
            elif active_field == "msgstr":
                current["msgstr"] += value
            continue

        if not stripped:
            flush()

    flush()
    return entries


def percent_string(done: int, total: int) -> str:
    pct = (100.0 * done / total) if total else 0.0
    return f"{pct:.2f}".replace(".", ",") + "%"


def badge_color(pct: float) -> str:
    if pct >= 100.0:
        return "brightgreen"
    if pct >= 75.0:
        return "green"
    if pct >= 50.0:
        return "yellowgreen"
    if pct >= 25.0:
        return "yellow"
    if pct > 0.0:
        return "orange"
    return "red"


def main() -> None:
    files_total = 0
    files_translated = 0
    files_reviewed = 0
    entries_total = 0
    entries_translated = 0
    entries_reviewed = 0

    for po_path in sorted(PO_ROOT.rglob("*.po")):
        entries = parse_po_entries(po_path)
        files_total += 1
        file_total = len(entries)
        file_translated = 0
        file_reviewed = 0

        for entry in entries:
            entries_total += 1
            translated = bool(entry["msgstr"].strip())
            reviewed = entry["status"].strip().lower() == "reviewed"
            if translated:
                entries_translated += 1
                file_translated += 1
            if reviewed:
                entries_reviewed += 1
                file_reviewed += 1

        if file_total > 0 and file_translated == file_total:
            files_translated += 1
        if file_total > 0 and file_reviewed == file_total:
            files_reviewed += 1

    translation_pct_value = (100.0 * entries_translated / entries_total) if entries_total else 0.0
    review_pct_value = (100.0 * entries_reviewed / entries_total) if entries_total else 0.0
    translation_pct = percent_string(entries_translated, entries_total)
    review_pct = percent_string(entries_reviewed, entries_total)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summary = {
        "files_total": files_total,
        "files_translated": files_translated,
        "files_reviewed": files_reviewed,
        "entries_total": entries_total,
        "entries_translated": entries_translated,
        "entries_reviewed": entries_reviewed,
        "translation_percent": translation_pct,
        "review_percent": review_pct,
    }

    translation_badge = {
        "schemaVersion": 1,
        "label": "traducción",
        "message": translation_pct,
        "color": badge_color(translation_pct_value),
    }

    review_badge = {
        "schemaVersion": 1,
        "label": "revisión",
        "message": review_pct,
        "color": badge_color(review_pct_value),
    }

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT_DIR / "translation_badge.json").write_text(json.dumps(translation_badge, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT_DIR / "review_badge.json").write_text(json.dumps(review_badge, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
