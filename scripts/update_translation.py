#!/usr/bin/env python3
"""
Update Ukrainian translation entries — single or batch.

Usage:
    Single entry (by source ref key):
        python scripts/update_translation.py "erpnext/selling/doctype/quotation/quotation.js:82" "Адреса"

    Single entry (by English msgid):
        python scripts/update_translation.py --msgid "Address" "Адреса"

    Batch from CSV (msgid,msgstr columns):
        python scripts/update_translation.py --batch translations.csv

    Batch from JSON ({"msgid": "translation"} mapping):
        python scripts/update_translation.py --batch translations.json

    Options:
        --force     Overwrite existing translations (default: skip with error)
"""

import argparse
import csv
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERPNEXT_ROOT = os.path.dirname(SCRIPT_DIR)
LOCALE_DIR = os.path.join(ERPNEXT_ROOT, "erpnext", "locale")
UK_PO_FILE = os.path.join(LOCALE_DIR, "uk.po")


def _find_next_msgid(lines, start):
    for j in range(start, min(start + 5, len(lines))):
        if lines[j].startswith("msgid "):
            return j
    return None


def _find_next_field(lines, start, field):
    for j in range(start, min(start + 10, len(lines))):
        if lines[j].startswith(f"{field} "):
            return j
    return None


def _read_multiline_string(lines, start, field):
    parts = []
    val = lines[start][len(field) + 1:]
    parts.append(val.strip('"'))
    j = start + 1
    while j < len(lines) and lines[j].startswith('"'):
        parts.append(lines[j].strip('"'))
        j += 1
    return "".join(parts)


def _update_msgstr_at(lines, msgstr_line, translation):
    escaped = translation.replace("\\", "\\\\").replace('"', '\\"')
    end = msgstr_line + 1
    while end < len(lines) and lines[end].startswith('"'):
        end += 1
    lines[msgstr_line] = f'msgstr "{escaped}"'
    del lines[msgstr_line + 1: end]


def update_single(content, key, msgid_match, translation, force=False):
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        if key and not msgid_match:
            if lines[i].startswith("#:") and key in lines[i]:
                msgid_line = _find_next_msgid(lines, i)
                if msgid_line is not None:
                    i = msgid_line
                else:
                    i += 1
                    continue
            else:
                i += 1
                continue
        elif msgid_match:
            if lines[i].startswith("msgid "):
                current_msgid = _read_multiline_string(lines, i, "msgid")
                if current_msgid != msgid_match:
                    i += 1
                    continue
            else:
                i += 1
                continue
        else:
            i += 1
            continue

        msgstr_line = _find_next_field(lines, i, "msgstr")
        if msgstr_line is None:
            i += 1
            continue

        current_msgstr = _read_multiline_string(lines, msgstr_line, "msgstr")
        if current_msgstr and not force:
            raise ValueError(
                f"Translation already exists!\n"
                f"  msgid:  {_read_multiline_string(lines, i, 'msgid')!r}\n"
                f"  msgstr: {current_msgstr!r}\n"
                f"Use --force to overwrite."
            )

        _update_msgstr_at(lines, msgstr_line, translation)
        return "\n".join(lines)

    return None


def update_batch(content, translations, force=False):
    lines = content.split("\n")
    remaining = dict(translations)
    updated = 0
    skipped = 0
    errors = []
    i = 0

    while i < len(lines) and remaining:
        if not lines[i].startswith("msgid "):
            i += 1
            continue

        current_msgid = _read_multiline_string(lines, i, "msgid")
        if current_msgid not in remaining:
            i += 1
            continue

        msgstr_line = _find_next_field(lines, i, "msgstr")
        if msgstr_line is None:
            i += 1
            continue

        current_msgstr = _read_multiline_string(lines, msgstr_line, "msgstr")
        translation = remaining.pop(current_msgid)

        if current_msgstr and not force:
            skipped += 1
            errors.append(f"  Already translated: {current_msgid!r} -> {current_msgstr!r}")
            i = msgstr_line + 1
            continue

        _update_msgstr_at(lines, msgstr_line, translation)
        updated += 1
        i = msgstr_line + 1

    return "\n".join(lines), updated, skipped, errors, list(remaining.keys())


def load_batch_file(filepath):
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".json":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print("Error: JSON must be a {\"msgid\": \"translation\"} object.")
            sys.exit(1)
        return {k: v for k, v in data.items() if k and v}

    with open(filepath, "r", encoding="utf-8") as f:
        sample = f.read(1024)
        f.seek(0)

        has_header = sample.startswith("msgid,") or sample.startswith("source")
        reader = csv.reader(f)
        if has_header:
            next(reader)

        translations = {}
        for row in reader:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                translations[row[0].strip()] = row[1].strip()
        return translations


def main():
    parser = argparse.ArgumentParser(description="Update Ukrainian translation entries")
    parser.add_argument("key", nargs="?", help="Source ref key or msgid text (for single update)")
    parser.add_argument("translation", nargs="?", help="Ukrainian translation text (for single update)")
    parser.add_argument("--msgid", action="store_true", help="Treat 'key' as English msgid text")
    parser.add_argument("--batch", help="CSV or JSON file for batch update")
    parser.add_argument("--force", action="store_true", help="Overwrite existing translations")
    args = parser.parse_args()

    if not args.batch and not args.key:
        parser.error("Provide either a key+translation or --batch FILE")

    if not os.path.exists(UK_PO_FILE):
        print(f"Error: {UK_PO_FILE} not found. Run create_uk_translation.py first.")
        sys.exit(1)

    with open(UK_PO_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    if args.batch:
        if not os.path.exists(args.batch):
            print(f"Error: File not found: {args.batch}")
            sys.exit(1)

        translations = load_batch_file(args.batch)
        print(f"Loaded {len(translations)} entries from {args.batch}")

        result, updated, skipped, errors, not_found = update_batch(
            content, translations, force=args.force
        )

        with open(UK_PO_FILE, "w", encoding="utf-8") as f:
            f.write(result)

        print(f"Updated:   {updated}")
        print(f"Skipped:   {skipped} (already translated)")
        print(f"Not found: {len(not_found)} (msgid not in .po file)")

        if errors:
            print(f"\nSkipped entries (use --force to overwrite):")
            for e in errors[:10]:
                print(e)
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more")

        if not_found:
            print(f"\nNot found in .po (first 10):")
            for nf in not_found[:10]:
                print(f"  {nf!r}")
            if len(not_found) > 10:
                print(f"  ... and {len(not_found) - 10} more")
    else:
        if not args.translation:
            parser.error("Translation text is required for single update")

        key = None if args.msgid else args.key
        msgid_match = args.key if args.msgid else None

        try:
            result = update_single(content, key, msgid_match, args.translation, force=args.force)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

        if result is None:
            target = f"msgid '{args.key}'" if args.msgid else f"key '{args.key}'"
            print(f"Error: Entry not found for {target}")
            sys.exit(1)

        with open(UK_PO_FILE, "w", encoding="utf-8") as f:
            f.write(result)

        target = args.key if args.msgid else f"[{args.key}]"
        print(f"Updated: {target} -> '{args.translation}'")


if __name__ == "__main__":
    main()
