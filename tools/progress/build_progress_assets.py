from pathlib import Path
import json
import re
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "assets" / "progress"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STATUS_RE = re.compile(r'^#\.\s+lineStatus:\s*(.+)$', re.MULTILINE)
MSGSTR_RE = re.compile(r'^msgstr\s+"(.*)"\s*$', re.MULTILINE)


def format_pct(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


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


def combined_progress_pct(translated: int, reviewed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return ((translated + reviewed) * 100.0) / (2.0 * total)


def iter_entries(text: str):
    blocks = text.split("\n\n")
    for block in blocks:
        if not block.strip():
            continue
        lines = block.splitlines()
        if any(line.startswith('msgid ""') for line in lines[:4]):
            continue
        if "msgid " not in block or "msgstr " not in block:
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


def classify_area(repo_relative: str) -> str | None:
    p = repo_relative.replace("\\", "/").lower()

    if p.startswith("data/auth/subtitle/"):
        return "Cinemáticas"

    if "/msg/" in p:
        return "Diálogos"

    return None


def build_readme_progress_md(summary: dict, areas: dict) -> str:
    lines = []
    lines.append("## Progreso del proyecto")
    lines.append("")
    lines.append(f"**Progreso global:** {format_pct(summary['pct_global'])}%")
    lines.append("")
    lines.append(
        f"**Traducción global:** {summary['entries_translated']}/{summary['entries_total']} "
        f"({format_pct(summary['pct_translated'])}%)  "
    )
    lines.append(
        f"**Revisión global:** {summary['entries_reviewed']}/{summary['entries_total']} "
        f"({format_pct(summary['pct_reviewed'])}%)"
    )
    lines.append("")
    lines.append("| Área | Traducción | Revisión |")
    lines.append("|---|---:|---:|")

    order = ["Diálogos", "Cinemáticas"]
    for area_name in order:
        if area_name not in areas:
            continue
        data = areas[area_name]
        lines.append(
            f"| {area_name} | "
            f"{data['translated']}/{data['total']} ({format_pct(data['pct_translated'])}%) | "
            f"{data['reviewed']}/{data['total']} ({format_pct(data['pct_reviewed'])}%) |"
        )

    return "\n".join(lines) + "\n"


def main():
    print("[1/5] Buscando archivos .po...", flush=True)

    files_total = 0
    files_translated = 0
    files_reviewed = 0
    entries_total = 0
    entries_translated = 0
    entries_reviewed = 0

    areas = defaultdict(lambda: {
        "files_total": 0,
        "files_translated": 0,
        "files_reviewed": 0,
        "total": 0,
        "translated": 0,
        "reviewed": 0,
    })

    po_files = []
    for po in ROOT.rglob("*.po"):
        posix = po.as_posix()
        if "/.git/" in posix or "/cache/" in posix or "/backups/" in posix:
            continue
        po_files.append(po)

    print(f"[2/5] Encontrados: {len(po_files)}", flush=True)
    print("[3/5] Calculando progreso global y por categoría...", flush=True)

    for po in po_files:
        total, translated, reviewed = parse_po(po)
        repo_relative = po.relative_to(ROOT).as_posix()

        files_total += 1
        entries_total += total
        entries_translated += translated
        entries_reviewed += reviewed

        if total > 0 and reviewed == total:
            files_reviewed += 1
        elif total > 0 and translated == total:
            files_translated += 1

        area = classify_area(repo_relative)
        if area:
            areas[area]["files_total"] += 1
            areas[area]["total"] += total
            areas[area]["translated"] += translated
            areas[area]["reviewed"] += reviewed

            if total > 0 and reviewed == total:
                areas[area]["files_reviewed"] += 1
            elif total > 0 and translated == total:
                areas[area]["files_translated"] += 1

    pct_translated = (entries_translated * 100.0 / entries_total) if entries_total else 0.0
    pct_reviewed = (entries_reviewed * 100.0 / entries_total) if entries_total else 0.0
    pct_global = combined_progress_pct(entries_translated, entries_reviewed, entries_total)

    areas_out = {}
    for area_name, data in areas.items():
        pct_area_translated = (data["translated"] * 100.0 / data["total"]) if data["total"] else 0.0
        pct_area_reviewed = (data["reviewed"] * 100.0 / data["total"]) if data["total"] else 0.0
        areas_out[area_name] = {
            "files_total": data["files_total"],
            "files_translated": data["files_translated"],
            "files_reviewed": data["files_reviewed"],
            "total": data["total"],
            "translated": data["translated"],
            "reviewed": data["reviewed"],
            "pct_translated": round(pct_area_translated, 2),
            "pct_reviewed": round(pct_area_reviewed, 2),
        }

    summary = {
        "files_total": files_total,
        "files_translated": files_translated,
        "files_reviewed": files_reviewed,
        "entries_total": entries_total,
        "entries_translated": entries_translated,
        "entries_reviewed": entries_reviewed,
        "pct_translated": round(pct_translated, 2),
        "pct_reviewed": round(pct_reviewed, 2),
        "pct_global": round(pct_global, 2),
        "areas": areas_out,
    }

    print("[4/5] Escribiendo assets/progress/...", flush=True)

    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

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

    global_badge = {
        "schemaVersion": 1,
        "label": "progreso global",
        "message": f"{format_pct(pct_global)}%",
        "color": badge_color(pct_global),
    }

    (OUT_DIR / "translation_badge.json").write_text(
        json.dumps(translation_badge, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    (OUT_DIR / "review_badge.json").write_text(
        json.dumps(review_badge, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    (OUT_DIR / "global_badge.json").write_text(
        json.dumps(global_badge, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    readme_progress = build_readme_progress_md(summary, areas_out)
    (OUT_DIR / "readme_progress.md").write_text(readme_progress, encoding="utf-8")

    print("[5/5] Progreso generado correctamente.", flush=True)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
