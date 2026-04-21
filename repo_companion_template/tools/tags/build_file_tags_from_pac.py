from pathlib import Path
import json
import re
import struct
import sys


def pac_tags_from_name(name: str):
    stem = Path(name).stem
    core = stem
    if core.lower().startswith('pac_stid_'):
        core = core[9:]
    tags = []
    if core.startswith('MG_'):
        tags.append('Minijuegos')
        tags.append(core[3:].replace('_', ' ').title())
    elif core.startswith('ST_'):
        tags.append('Escenario')
        tags.append(core[3:].replace('_', ' ').title())
    elif core.startswith('TE_'):
        tags.append('Evento')
        tags.append(core[3:].replace('_', ' ').title())
    else:
        tags.append(core.replace('_', ' ').title())
    tags.append(f'PAC {core}')
    # unique preserving order
    out = []
    for tag in tags:
        if tag not in out:
            out.append(tag)
    return out


def scan_pac_for_uids(path: Path):
    data = path.read_bytes()
    found = set()
    for off in range(0, len(data) - 3, 4):
        value = struct.unpack('>I', data[off:off+4])[0]
        if 0x00010000 <= value <= 0x00FFFFFF:
            found.add(f'uid{value:08x}.po')
    return found


def main():
    if len(sys.argv) < 3:
        print('Usage: python build_file_tags_from_pac.py <pac_dir> <output_json>')
        raise SystemExit(1)
    pac_dir = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    result = {'files': {}}
    for pac in sorted(pac_dir.glob('*.bin')):
        tags = pac_tags_from_name(pac.name)
        for po_name in scan_pac_for_uids(pac):
            slot = result['files'].setdefault(po_name, [])
            for tag in tags:
                if tag not in slot:
                    slot.append(tag)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
