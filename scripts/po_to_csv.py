#!/usr/bin/env python3
"""Convert PO files to CSV format for Frappe translation system."""
import csv
import io
import re
import sys
import os


def unescape_po(s):
    return s.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\x00", "\\")


def parse_po(path):
    """Parse a PO file and return {msgid: msgstr} dict."""
    translations = {}
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("msgid "):
            # Collect msgid
            msgid_parts = []
            m = re.match(r'^msgid\s+"(.*)"$', line.strip())
            if m:
                msgid_parts.append(m.group(1))
            i += 1
            while i < len(lines) and lines[i].startswith('"'):
                m2 = re.match(r'^"(.*)"$', lines[i].strip())
                if m2:
                    msgid_parts.append(m2.group(1))
                i += 1

            msgid_val = unescape_po("".join(msgid_parts))

            # Collect msgstr
            msgstr_parts = []
            if i < len(lines) and lines[i].startswith("msgstr "):
                m = re.match(r'^msgstr\s+"(.*)"$', lines[i].strip())
                if m:
                    msgstr_parts.append(m.group(1))
                i += 1
                while i < len(lines) and lines[i].startswith('"'):
                    m2 = re.match(r'^"(.*)"$', lines[i].strip())
                    if m2:
                        msgstr_parts.append(m2.group(1))
                    i += 1

            msgstr_val = unescape_po("".join(msgstr_parts))

            if msgid_val and msgstr_val:
                translations[msgid_val] = msgstr_val
        else:
            i += 1

    return translations


def read_csv_translations(path):
    """Read existing CSV translation file."""
    translations = {}
    if not os.path.exists(path):
        return translations
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2 and row[0] and row[1]:
                translations[row[0]] = row[1]
    return translations


def write_csv(translations, path):
    """Write translations as CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for msgid in sorted(translations.keys()):
        writer.writerow([msgid, translations[msgid]])
    with open(path, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.join(script_dir, "..")

    # ERPNext PO -> CSV
    erpnext_po = os.path.join(repo_dir, "erpnext", "locale", "uk.po")
    erpnext_csv_out = os.path.join(repo_dir, "erpnext_translations_uk.csv")

    if os.path.exists(erpnext_po):
        po_trans = parse_po(erpnext_po)
        print(f"ERPNext PO: {len(po_trans)} translations")
        write_csv(po_trans, erpnext_csv_out)
        print(f"Written to: {erpnext_csv_out}")

    # Frappe PO -> CSV
    frappe_po = os.path.join(repo_dir, "frappe_locale_uk.po")
    frappe_csv_out = os.path.join(repo_dir, "frappe_translations_uk.csv")

    if os.path.exists(frappe_po):
        po_trans = parse_po(frappe_po)
        print(f"Frappe PO: {len(po_trans)} translations")
        write_csv(po_trans, frappe_csv_out)
        print(f"Written to: {frappe_csv_out}")


if __name__ == "__main__":
    main()
