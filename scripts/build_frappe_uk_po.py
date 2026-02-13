#!/usr/bin/env python3
"""Build frappe/locale/uk.po from translated chunks and main.pot template."""
import json
import glob
import re
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNKS_DIR = os.path.join(SCRIPT_DIR, "frappe_chunks")
POT_FILE = os.path.join(SCRIPT_DIR, "frappe_main.pot")
OUTPUT = os.path.join(SCRIPT_DIR, "..", "frappe_locale_uk.po")


def load_translations():
    translations = {}
    for path in sorted(glob.glob(os.path.join(CHUNKS_DIR, "chunk_*_uk.json"))):
        with open(path, encoding="utf-8") as f:
            try:
                translations.update(json.load(f))
            except json.JSONDecodeError as e:
                print(f"  WARNING: {path}: {e}")
    return translations


def escape_po(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")


def unescape_po(s):
    return s.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\x00", "\\")


UK_HEADER = '''\
# Ukrainian translation for Frappe Framework.
# Copyright (C) 2026 Frappe Technologies
# This file is distributed under the same license as the Frappe Framework project.
#
msgid ""
msgstr ""
"Project-Id-Version: Frappe Framework VERSION\\n"
"Report-Msgid-Bugs-To: developers@frappe.io\\n"
"POT-Creation-Date: 2026-02-08 09:41+0000\\n"
"PO-Revision-Date: 2026-02-11 00:00+0000\\n"
"Last-Translator: developers@frappe.io\\n"
"Language-Team: Ukrainian\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Generated-By: Babel 2.16.0\\n"
"Plural-Forms: nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);\\n"
"X-Crowdin-Language: uk\\n"
"Language: uk\\n"

'''


def build():
    translations = load_translations()
    print(f"Loaded {len(translations)} translations from chunks")

    with open(POT_FILE, encoding="utf-8") as f:
        lines = f.readlines()

    out = [UK_HEADER]
    i = 0
    filled = 0
    total = 0

    # Skip the header block
    while i < len(lines):
        if lines[i].startswith("#:") or lines[i].startswith("#."):
            break
        i += 1

    while i < len(lines):
        line = lines[i]

        if line.startswith("#") or line.strip() == "":
            out.append(line)
            i += 1
            continue

        if line.startswith("msgid "):
            msgid_lines = [line]
            i += 1
            while i < len(lines) and lines[i].startswith('"'):
                msgid_lines.append(lines[i])
                i += 1

            # Parse msgid value
            parts = []
            for ml in msgid_lines:
                s = ml.strip()
                m = re.match(r'^(?:msgid)\s+"(.*)"$', s)
                if m:
                    parts.append(unescape_po(m.group(1)))
                    continue
                m2 = re.match(r'^"(.*)"$', s)
                if m2:
                    parts.append(unescape_po(m2.group(1)))
            msgid_val = "".join(parts)

            # Skip msgstr line from pot
            if i < len(lines) and lines[i].startswith("msgstr "):
                i += 1
                while i < len(lines) and lines[i].startswith('"'):
                    i += 1

            out.extend(msgid_lines)
            if msgid_val and msgid_val in translations:
                out.append(f'msgstr "{escape_po(translations[msgid_val])}"\n')
                filled += 1
            else:
                out.append('msgstr ""\n')

            if msgid_val:
                total += 1
        else:
            out.append(line)
            i += 1

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("".join(out))

    print(f"Total entries: {total}")
    print(f"Filled: {filled}")
    print(f"Empty: {total - filled}")
    print(f"Written to: {OUTPUT}")


if __name__ == "__main__":
    build()
