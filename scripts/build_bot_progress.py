from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.progress.build_progress_assets import (
    FILE_STATUS_RE,
    HOSTESS_PO_PATHS,
    LINE_STATUS_RE,
    REVIEWED_BY_RE,
    extract_po_field,
    iter_entries,
    load_hidden_terms,
    normalize_status,
    parse_po,
)


SUBSTORIES_PATH = ROOT / "assets" / "companion" / "substories.json"
FILE_TAGS_PATH = ROOT / "assets" / "companion" / "file_tags.json"
BOOT_SUBSTORY_PATH = ROOT / "data" / "bootpar" / "boot_en" / "boot_en" / "substory.po"
OUT_DIR = ROOT / "assets" / "bot"
OUT_PATH = OUT_DIR / "progress.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)


def pct(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value * 100.0 / total, 2)


def norm(value: str) -> str:
    return value.replace("\\", "/").strip().lstrip("/").casefold()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"No se pudo leer {path}: {exc}") from exc


def build_po_index() -> dict[str, list[Path]]:
    """Índice basename -> rutas .po del repositorio."""
    result: dict[str, list[Path]] = defaultdict(list)

    for path in ROOT.rglob("*.po"):
        if any(part in {".git", "cache", "backups"} for part in path.parts):
            continue
        result[path.name.casefold()].append(path)

    for paths in result.values():
        paths.sort(
            key=lambda p: (
                "/msg/" not in p.as_posix().casefold(),
                p.as_posix().casefold(),
            )
        )

    return dict(result)


def resolve_uid(po_index: dict[str, list[Path]], uid: str) -> Path | None:
    name = f"uid{str(uid).strip().casefold()}.po"
    paths = po_index.get(name, [])
    return paths[0] if paths else None


def resolve_basename(po_index: dict[str, list[Path]], basename: str) -> Path | None:
    paths = po_index.get(Path(basename).name.casefold(), [])
    return paths[0] if paths else None


def resolve_repo_path(repo_path: str) -> Path | None:
    path = ROOT / repo_path
    return path if path.is_file() else None


def parse_boot_contexts(
    contexts: set[int],
    hidden_terms: list[str],
) -> dict:
    """Cuenta solo los msgctxt de substory.po indicados por boot_contexts."""
    result = {
        "total": 0,
        "translated": 0,
        "reviewed": 0,
        "hidden": 0,
    }

    if not contexts or not BOOT_SUBSTORY_PATH.is_file():
        return result

    text = BOOT_SUBSTORY_PATH.read_text(encoding="utf-8", errors="replace")
    file_reviewed = any(
        normalize_status(status) == "reviewed"
        for status in FILE_STATUS_RE.findall(text)
    )

    for block in iter_entries(text):
        msgctxt = extract_po_field(block, "msgctxt")
        head = msgctxt.split("\t", 1)[0].strip()

        try:
            context_id = int(head)
        except ValueError:
            continue

        if context_id not in contexts:
            continue

        haystack = "\n".join(
            extract_po_field(block, field)
            for field in ("msgctxt", "msgid", "msgstr")
        ).lower()

        if any(term in haystack for term in hidden_terms):
            result["hidden"] += 1
            continue

        result["total"] += 1

        if extract_po_field(block, "msgstr") != "":
            result["translated"] += 1

        statuses = LINE_STATUS_RE.findall(block)
        reviewed = (
            (
                statuses
                and normalize_status(statuses[-1]) == "reviewed"
            )
            or REVIEWED_BY_RE.search(block)
            or file_reviewed
        )

        if reviewed:
            result["reviewed"] += 1

    return result


def main() -> None:
    hidden_terms = load_hidden_terms()
    po_index = build_po_index()

    @lru_cache(maxsize=None)
    def stats_for(path_text: str) -> tuple[int, int, int, int]:
        return parse_po(Path(path_text), hidden_terms)

    def aggregate(paths: list[Path]) -> dict:
        unique: dict[str, Path] = {}

        for path in paths:
            if path and path.is_file():
                key = norm(path.relative_to(ROOT).as_posix())
                unique[key] = path

        total = translated = reviewed = hidden = 0

        for path in unique.values():
            t, tr, rv, hi = stats_for(str(path))
            total += t
            translated += tr
            reviewed += rv
            hidden += hi

        return {
            "files": len(unique),
            "total": total,
            "translated": translated,
            "reviewed": reviewed,
            "hidden": hidden,
            "pct_translated": pct(translated, total),
            "pct_reviewed": pct(reviewed, total),
        }

    # ------------------------------------------------------------------
    # SUBHISTORIAS
    # ------------------------------------------------------------------
    substories_data = load_json(SUBSTORIES_PATH)
    substories_out: list[dict] = []
    all_substory_basenames: set[str] = set()

    for substory in substories_data.get("substories", []):
        paths: list[Path] = []
        missing_uids: list[str] = []
        seen_uids: set[str] = set()

        for item in substory.get("files", []):
            uid = str(item.get("uid", "")).strip().casefold()
            if not uid or uid in seen_uids:
                continue

            seen_uids.add(uid)
            basename = f"uid{uid}.po"
            all_substory_basenames.add(basename.casefold())

            path = resolve_uid(po_index, uid)
            if path is None:
                missing_uids.append(uid)
            else:
                paths.append(path)

        data = aggregate(paths)

        boot_contexts = {
            int(value)
            for value in substory.get("boot_contexts", [])
            if str(value).strip().lstrip("-").isdigit()
        }
        boot = parse_boot_contexts(boot_contexts, hidden_terms)

        data["total"] += boot["total"]
        data["translated"] += boot["translated"]
        data["reviewed"] += boot["reviewed"]
        data["hidden"] += boot["hidden"]
        data["pct_translated"] = pct(data["translated"], data["total"])
        data["pct_reviewed"] = pct(data["reviewed"], data["total"])

        data.update(
            {
                "id": substory.get("id"),
                "name": substory.get("name", f"Subhistoria {substory.get('id', '?')}"),
                "protagonist": substory.get("protagonist", "Sin protagonista"),
                "boot_contexts_counted": boot["total"],
                "missing_uids": missing_uids,
            }
        )
        substories_out.append(data)

    substories_out.sort(
        key=lambda x: (
            str(x.get("protagonist", "")).casefold(),
            int(x.get("id") or 0),
        )
    )

    # ------------------------------------------------------------------
    # HOSTESS
    # ------------------------------------------------------------------
    hostess_paths: list[Path] = []
    hostess_missing: list[str] = []

    for repo_path in sorted(HOSTESS_PO_PATHS):
        path = resolve_repo_path(repo_path)
        if path is None:
            hostess_missing.append(repo_path)
        else:
            hostess_paths.append(path)

    hostess_out = aggregate(hostess_paths)
    hostess_out.update(
        {
            "name": "Hostess",
            "missing_files": hostess_missing,
        }
    )

    hostess_basenames = {
        Path(path).name.casefold()
        for path in HOSTESS_PO_PATHS
    }

    # ------------------------------------------------------------------
    # HISTORIA / ESCENARIO
    # ------------------------------------------------------------------
    file_tags_data = load_json(FILE_TAGS_PATH)
    tagged_files = file_tags_data.get("files", {})

    history_paths: list[Path] = []
    history_missing: list[str] = []

    for basename, tags in tagged_files.items():
        if not isinstance(tags, list):
            continue

        normalized_tags = {str(tag).strip().casefold() for tag in tags}
        if "escenario" not in normalized_tags:
            continue

        base_cf = Path(basename).name.casefold()
        if base_cf in all_substory_basenames:
            continue
        if base_cf in hostess_basenames:
            continue

        path = resolve_basename(po_index, basename)
        if path is None:
            history_missing.append(str(basename))
        else:
            history_paths.append(path)

    history_out = aggregate(history_paths)
    history_out.update(
        {
            "name": "Historia principal",
            "classification": "Escenario - Subhistorias - Hostess",
            "missing_files": history_missing,
        }
    )

    output = {
        "schema_version": 1,
        "repository": "Kcat-art/DD-Y4-es419-translation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subhistorias": substories_out,
        "hostess": hostess_out,
        "historia": history_out,
    }

    OUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Generado: {OUT_PATH.relative_to(ROOT)}")
    print(f"Subhistorias: {len(substories_out)}")
    print(
        "Hostess: "
        f"{hostess_out['pct_translated']:.2f}% traducido / "
        f"{hostess_out['pct_reviewed']:.2f}% revisado"
    )
    print(
        "Historia: "
        f"{history_out['pct_translated']:.2f}% traducido / "
        f"{history_out['pct_reviewed']:.2f}% revisado"
    )


if __name__ == "__main__":
    main()
