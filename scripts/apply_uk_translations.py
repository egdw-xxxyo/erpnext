#!/usr/bin/env python3
"""
Apply translated v2 chunks to uk.po file.
Reads all v2/chunk_NNN_uk.json files, builds an en->uk dictionary,
then fills in empty msgstr entries in uk.po.
"""
import json
import re
import os
import glob

CHUNKS_DIR = os.path.join(os.path.dirname(__file__), "translation_chunks", "v2")
PO_FILE = os.path.join(os.path.dirname(__file__), "..", "erpnext", "locale", "uk.po")


def load_translations():
    translations = {}
    chunk_files = sorted(glob.glob(os.path.join(CHUNKS_DIR, "chunk_*_uk.json")))
    print(f"Loading {len(chunk_files)} v2 chunk files...")
    for path in chunk_files:
        with open(path, encoding="utf-8") as f:
            try:
                data = json.load(f)
                translations.update(data)
            except json.JSONDecodeError as e:
                print(f"  WARNING: Failed to parse {path}: {e}")
    print(f"Loaded {len(translations)} translations total.")
    return translations


def unescape_po(s):
    """Unescape PO string content (between quotes)."""
    return s.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\x00", "\\")


def escape_po(s):
    """Escape a string for use in PO msgstr."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")


def parse_po_quoted_lines(lines):
    """Extract joined string value from a list of PO lines (msgid/msgstr/continuation)."""
    parts = []
    for line in lines:
        stripped = line.strip()
        # Match keyword "value" or just "value" continuation
        m = re.match(r'^(?:msgid|msgstr|msgctxt)\s+"(.*)"$', stripped)
        if m:
            parts.append(unescape_po(m.group(1)))
            continue
        m2 = re.match(r'^"(.*)"$', stripped)
        if m2:
            parts.append(unescape_po(m2.group(1)))
    return "".join(parts)


def apply_to_po(translations):
    with open(PO_FILE, encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    i = 0
    filled = 0
    already_filled = 0
    no_translation = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("msgid "):
            # Collect full msgid block (first line + continuations)
            msgid_lines = [line]
            i += 1
            while i < len(lines) and lines[i].startswith('"'):
                msgid_lines.append(lines[i])
                i += 1

            msgid_val = parse_po_quoted_lines(msgid_lines)

            # Collect optional msgctxt or comments that come between msgid and msgstr
            # (shouldn't normally happen, but be safe)
            inter_lines = []
            while i < len(lines) and not lines[i].startswith("msgstr ") and not lines[i].startswith("msgid "):
                inter_lines.append(lines[i])
                i += 1

            if i >= len(lines) or not lines[i].startswith("msgstr "):
                out.extend(msgid_lines)
                out.extend(inter_lines)
                continue

            # Collect full msgstr block
            msgstr_lines = [lines[i]]
            i += 1
            while i < len(lines) and lines[i].startswith('"'):
                msgstr_lines.append(lines[i])
                i += 1

            msgstr_val = parse_po_quoted_lines(msgstr_lines)

            out.extend(msgid_lines)
            out.extend(inter_lines)

            if msgstr_val == "" and msgid_val and msgid_val in translations:
                uk_val = translations[msgid_val]
                escaped = escape_po(uk_val)
                out.append(f'msgstr "{escaped}"\n')
                filled += 1
            else:
                if msgstr_val != "":
                    already_filled += 1
                else:
                    no_translation += 1
                out.extend(msgstr_lines)
        else:
            out.append(line)
            i += 1

    new_content = "".join(out)
    with open(PO_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"\nResults:")
    print(f"  Filled in:      {filled}")
    print(f"  Already filled: {already_filled}")
    print(f"  No translation: {no_translation}")
    print(f"\nDone! Updated {PO_FILE}")


if __name__ == "__main__":
    translations = load_translations()
    apply_to_po(translations)
