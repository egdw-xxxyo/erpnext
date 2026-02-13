#!/usr/bin/env python3
"""Apply remaining non-v2 chunk translations to fill empty entries in uk.po."""
import json
import re
import glob

PO_FILE = "erpnext/locale/uk.po"

def load_translations():
    translations = {}
    for path in sorted(glob.glob("scripts/translation_chunks/chunk_*_uk.json")):
        with open(path, encoding="utf-8") as f:
            try:
                translations.update(json.load(f))
            except json.JSONDecodeError:
                pass
    return translations


def unescape_po(s):
    return s.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\x00", "\\")


def escape_po(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")


def apply(translations):
    with open(PO_FILE, encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    filled = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.startswith("msgid "):
            msgid_lines = [line]
            i += 1
            while i < len(lines) and lines[i].startswith('"'):
                msgid_lines.append(lines[i])
                i += 1

            # Only handle simple single-line msgid
            m = re.match(r'^msgid "(.+)"$', msgid_lines[0].strip())
            if m and len(msgid_lines) == 1:
                msgid_val = unescape_po(m.group(1))
            else:
                msgid_val = None

            inter = []
            while i < len(lines) and not lines[i].startswith("msgstr ") and not lines[i].startswith("msgid "):
                inter.append(lines[i])
                i += 1

            if i < len(lines) and lines[i].startswith("msgstr "):
                msgstr_line = lines[i]
                i += 1
                msgstr_cont = []
                while i < len(lines) and lines[i].startswith('"'):
                    msgstr_cont.append(lines[i])
                    i += 1

                is_empty = msgstr_line.strip() == 'msgstr ""' and not msgstr_cont
                if is_empty and msgid_val and msgid_val in translations:
                    uk_val = translations[msgid_val]
                    out.extend(msgid_lines)
                    out.extend(inter)
                    out.append(f'msgstr "{escape_po(uk_val)}"\n')
                    filled += 1
                else:
                    out.extend(msgid_lines)
                    out.extend(inter)
                    out.append(msgstr_line)
                    out.extend(msgstr_cont)
            else:
                out.extend(msgid_lines)
                out.extend(inter)
        else:
            out.append(line)
            i += 1

    with open(PO_FILE, "w", encoding="utf-8") as f:
        f.write("".join(out))
    print(f"Filled {filled} entries from non-v2 chunks")


if __name__ == "__main__":
    t = load_translations()
    print(f"Loaded {len(t)} non-v2 translations")
    apply(t)
