from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "assets" / "progress"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ENTRY_RE = re.compile(r'^msgid\s+"', re.MULTILINE)
STATUS_RE = re.compile(r'^#\.\s+lineStatus:\s*(.+)$', re.MULTILINE)
MSGSTR_EMPTY_RE = re.compile(r'^msgstr\s+""\s*$', re.MULTILINE)
MSGSTR_RE = re.compile(r'^msgstr\s+"(.*)"\s*$', re.MULTILINE)


def format_pct(value: float) -> str:
    return f"{value:.2f}".replace('.', ',')


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


def iter_entries(text: str):
    blocks = text.split("\n\n")
    for block in blocks:
        if not block.strip() or 'msgid ""' in block.splitlines()[:4]:
            continue
        if 'msgid ' not in block or 'msgstr ' not in block:
            continue
        yield block


def parse_po(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    total = translated = reviewed = 0
    for block in iter_entries(text):
        total += 1
        msgstr_match = MSGSTR_RE.search(block)
        if msgstr_match and msgstr_match.group(1) != "":
            translated += 1
        statuses = STATUS_RE.findall(block)
        if statuses and statuses[-1].strip().lower() == "reviewed":
            reviewed += 1
    return total, translated, reviewed


def main():
    files_total = files_translated = files_reviewed = 0
    entries_total = entries_translated = entries_reviewed = 0
    for po in ROOT.rglob('*.po'):
        if '.git/' in po.as_posix() or '/cache/' in po.as_posix() or '/backups/' in po.as_posix():
            continue
        total, translated, reviewed = parse_po(po)
        files_total += 1
        entries_total += total
        entries_translated += translated
        entries_reviewed += reviewed
        if total > 0 and reviewed == total:
            files_reviewed += 1
        elif total > 0 and translated == total:
            files_translated += 1

    pct_translated = (entries_translated * 100.0 / entries_total) if entries_total else 0.0
    pct_reviewed = (entries_reviewed * 100.0 / entries_total) if entries_total else 0.0

    summary = {
        "files_total": files_total,
        "files_translated": files_translated,
        "files_reviewed": files_reviewed,
        "entries_total": entries_total,
        "entries_translated": entries_translated,
        "entries_reviewed": entries_reviewed,
        "pct_translated": round(pct_translated, 2),
        "pct_reviewed": round(pct_reviewed, 2),
    }
    (OUT_DIR / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding='utf-8')

    translation_badge = {
        "schemaVersion": 1,
        "label": "traducción",
        "message": f"{format_pct(pct_translated)}%",
        "color": badge_color(pct_translated),
    }
    review_badge = {
        "schemaVersion": 1,
        "label": "revisión",
        "message": f"{format_pct(pct_reviewed)}%",
        "color": badge_color(pct_reviewed),
    }
    (OUT_DIR / 'translation_badge.json').write_text(json.dumps(translation_badge, indent=2, ensure_ascii=False) + "\n", encoding='utf-8')
    (OUT_DIR / 'review_badge.json').write_text(json.dumps(review_badge, indent=2, ensure_ascii=False) + "\n", encoding='utf-8')


if __name__ == '__main__':
    main()
