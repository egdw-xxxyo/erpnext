#!/usr/bin/env python3
"""
Compare Ukrainian and Russian/English translations, show entries missing in Ukrainian.

Usage:
    python scripts/compare_translations.py                    # compare uk vs en (empty uk entries)
    python scripts/compare_translations.py --with-lang ru     # show entries where ru has translation but uk doesn't
    python scripts/compare_translations.py --with-lang ru --limit 100
    python scripts/compare_translations.py --with-lang ru --offset 40
"""

import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERPNEXT_ROOT = os.path.dirname(SCRIPT_DIR)
LOCALE_DIR = os.path.join(ERPNEXT_ROOT, "erpnext", "locale")
UK_PO_FILE = os.path.join(LOCALE_DIR, "uk.po")


def parse_entries(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    header_match = re.match(
        r'(#[^\n]*\n)*msgid ""\nmsgstr ""\n(".*\\n"\n)+', content
    )
    body = content[header_match.end():] if header_match else content

    raw_entries = re.split(r"\n(?=#[.:]|\nmsgid )", body)

    entries = []
    for raw in raw_entries:
        raw = raw.strip()
        if not raw:
            continue

        msgid = _extract_string(raw, "msgid")
        msgstr = _extract_string(raw, "msgstr")
        refs = re.findall(r"^#:\s*(.+)$", raw, re.MULTILINE)
        key = refs[0].strip() if refs else msgid[:60]

        if msgid:
            entries.append({"msgid": msgid, "msgstr": msgstr, "key": key})

    return entries


def _extract_string(block, field):
    lines = block.split("\n")
    parts = []
    capture = False
    for line in lines:
        if line.startswith(f"{field} "):
            capture = True
            val = line[len(field) + 1:]
            parts.append(val.strip('"'))
        elif capture:
            if line.startswith('"'):
                parts.append(line.strip('"'))
            else:
                break
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Compare UK vs RU/EN translations")
    parser.add_argument("--with-lang", help="Compare against another language (e.g., 'ru'). Shows entries translated in that language but missing in uk.")
    parser.add_argument("--limit", type=int, default=40, help="Number of results to show (default: 40)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N entries")
    args = parser.parse_args()

    if not os.path.exists(UK_PO_FILE):
        print(f"Error: {UK_PO_FILE} not found. Run create_uk_translation.py first.")
        sys.exit(1)

    uk_entries = parse_entries(UK_PO_FILE)
    uk_by_msgid = {e["msgid"]: e for e in uk_entries}

    uk_filled = [e for e in uk_entries if e["msgstr"]]
    uk_empty = [e for e in uk_entries if not e["msgstr"]]

    if args.with_lang:
        other_po = os.path.join(LOCALE_DIR, f"{args.with_lang}.po")
        if not os.path.exists(other_po):
            print(f"Error: {other_po} not found.")
            sys.exit(1)

        other_entries = parse_entries(other_po)
        other_by_msgid = {e["msgid"]: e for e in other_entries if e["msgstr"]}

        gaps = []
        for e in uk_entries:
            if not e["msgstr"] and e["msgid"] in other_by_msgid:
                gaps.append({
                    "msgid": e["msgid"],
                    "other_msgstr": other_by_msgid[e["msgid"]]["msgstr"],
                    "key": e["key"],
                })

        print(f"Ukrainian:   {len(uk_filled)} translated, {len(uk_empty)} empty")
        print(f"{args.with_lang.upper()}:          {len(other_by_msgid)} translated")
        print(f"Gaps:        {len(gaps)} entries have {args.with_lang.upper()} translation but no UK")
        print(f"\nShowing {args.limit} gaps (offset {args.offset}):\n")

        shown = gaps[args.offset: args.offset + args.limit]
        for i, g in enumerate(shown, start=args.offset + 1):
            print(f"  {i}. en: {g['msgid']!r}")
            print(f"     {args.with_lang}: {g['other_msgstr']!r}")
            print(f"     uk: ''")
            print(f"     key: {g['key']}")
            print()
    else:
        print(f"Total entries: {len(uk_entries)}")
        print(f"Translated:    {len(uk_filled)}")
        print(f"Empty:         {len(uk_empty)}")
        print(f"\nShowing {args.limit} empty entries (offset {args.offset}):\n")

        shown = uk_empty[args.offset: args.offset + args.limit]
        for i, e in enumerate(shown, start=args.offset + 1):
            print(f"  {i}. en: {e['msgid']!r}")
            print(f"     uk: ''")
            print(f"     key: {e['key']}")
            print()


if __name__ == "__main__":
    main()
