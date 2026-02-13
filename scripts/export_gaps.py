#!/usr/bin/env python3
"""Export UK vs RU translation gaps as JSON chunks for parallel translation."""

import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERPNEXT_ROOT = os.path.dirname(SCRIPT_DIR)
LOCALE_DIR = os.path.join(ERPNEXT_ROOT, "erpnext", "locale")


def parse_entries(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    header_match = re.match(r'(#[^\n]*\n)*msgid ""\nmsgstr ""\n(".*\\n"\n)+', content)
    body = content[header_match.end():] if header_match else content
    raw_entries = re.split(r"\n(?=#[.:]|\nmsgid )", body)
    entries = []
    for raw in raw_entries:
        raw = raw.strip()
        if not raw:
            continue
        msgid = _extract(raw, "msgid")
        msgstr = _extract(raw, "msgstr")
        if msgid:
            entries.append({"msgid": msgid, "msgstr": msgstr})
    return entries


def _extract(block, field):
    lines = block.split("\n")
    parts = []
    capture = False
    for line in lines:
        if line.startswith(f"{field} "):
            capture = True
            parts.append(line[len(field) + 1:].strip('"'))
        elif capture:
            if line.startswith('"'):
                parts.append(line.strip('"'))
            else:
                break
    return "".join(parts)


def main():
    chunk_size = int(sys.argv[1]) if len(sys.argv) > 1 else 40

    uk_entries = parse_entries(os.path.join(LOCALE_DIR, "uk.po"))
    ru_entries = parse_entries(os.path.join(LOCALE_DIR, "ru.po"))

    ru_map = {e["msgid"]: e["msgstr"] for e in ru_entries if e["msgstr"]}
    gaps = []
    for e in uk_entries:
        if not e["msgstr"] and e["msgid"] in ru_map:
            gaps.append({"en": e["msgid"], "ru": ru_map[e["msgid"]]})

    print(f"Total gaps: {len(gaps)}")

    out_dir = os.path.join(SCRIPT_DIR, "translation_chunks")
    os.makedirs(out_dir, exist_ok=True)

    for i in range(0, len(gaps), chunk_size):
        chunk = gaps[i:i + chunk_size]
        chunk_file = os.path.join(out_dir, f"chunk_{i // chunk_size:03d}.json")
        with open(chunk_file, "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)

    num_chunks = (len(gaps) + chunk_size - 1) // chunk_size
    print(f"Created {num_chunks} chunks of {chunk_size} in {out_dir}/")


if __name__ == "__main__":
    main()
