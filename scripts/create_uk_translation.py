#!/usr/bin/env python3
"""
Create Ukrainian (uk) .po translation file for ERPNext.

Usage:
    python scripts/create_uk_translation.py
    python scripts/create_uk_translation.py --from-lang ru
    python scripts/create_uk_translation.py --csv translations.csv
    python scripts/create_uk_translation.py --enable-language

Options:
    --from-lang CODE    Copy translations from another .po file (e.g., "ru" for Russian)
    --csv FILE          CSV file with msgid,msgstr columns to pre-fill translations
    --enable-language   Download and patch frappe/geo/languages.csv to enable Ukrainian
"""

import argparse
import csv
import io
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERPNEXT_ROOT = os.path.dirname(SCRIPT_DIR)
LOCALE_DIR = os.path.join(ERPNEXT_ROOT, "erpnext", "locale")
POT_FILE = os.path.join(LOCALE_DIR, "main.pot")
UK_PO_FILE = os.path.join(LOCALE_DIR, "uk.po")

UK_HEADER = """\
msgid ""
msgstr ""
"Project-Id-Version: frappe\\n"
"Report-Msgid-Bugs-To: hello@frappe.io\\n"
"POT-Creation-Date: {pot_creation_date}\\n"
"PO-Revision-Date: {revision_date}\\n"
"Last-Translator: hello@frappe.io\\n"
"Language-Team: Ukrainian\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Generated-By: Babel 2.16.0\\n"
"Plural-Forms: nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);\\n"
"X-Crowdin-Project: frappe\\n"
"X-Crowdin-Project-ID: 639578\\n"
"X-Crowdin-Language: uk\\n"
"X-Crowdin-File: /[frappe.erpnext] develop/erpnext/locale/main.pot\\n"
"X-Crowdin-File-ID: 46\\n"
"Language: uk\\n"
"""


def extract_pot_creation_date(pot_content):
    match = re.search(r'"POT-Creation-Date:\s*(.+?)\\n"', pot_content)
    if match:
        return match.group(1)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M+0000")


def parse_po_entries(content):
    """Parse .pot/.po file and return (header_end_pos, list of entry blocks)."""
    header_match = re.match(
        r'(#[^\n]*\n)*msgid ""\nmsgstr ""\n(".*\\n"\n)+', content
    )
    header_end = header_match.end() if header_match else 0

    body = content[header_end:]
    entries = re.split(r"\n(?=#[.:]|\nmsgid )", body)
    entries = [e.strip() for e in entries if e.strip()]
    return entries


def extract_msgid(entry):
    """Extract the full msgid string from a PO entry (handles multiline)."""
    lines = entry.split("\n")
    msgid_parts = []
    in_msgid = False
    for line in lines:
        if line.startswith("msgid "):
            in_msgid = True
            val = line[len("msgid "):]
            msgid_parts.append(val.strip('"'))
        elif in_msgid:
            if line.startswith('"'):
                msgid_parts.append(line.strip('"'))
            else:
                break
    return "".join(msgid_parts)


def set_msgstr(entry, translation):
    """Replace the msgstr in an entry with the given translation."""
    escaped = translation.replace("\\", "\\\\").replace('"', '\\"')
    return re.sub(r'msgstr ".*"', f'msgstr "{escaped}"', entry, count=1)


def load_po_translations(po_path):
    """Load msgid->msgstr mappings from an existing .po file."""
    with open(po_path, "r", encoding="utf-8") as f:
        content = f.read()

    entries = parse_po_entries(content)
    translations = {}
    for entry in entries:
        msgid = extract_msgid(entry)
        msgstr = extract_msgstr(entry)
        if msgid and msgstr:
            translations[msgid] = msgstr
    return translations


def extract_msgstr(entry):
    """Extract the full msgstr string from a PO entry (handles multiline)."""
    lines = entry.split("\n")
    parts = []
    in_msgstr = False
    for line in lines:
        if line.startswith("msgstr "):
            in_msgstr = True
            val = line[len("msgstr "):]
            parts.append(val.strip('"'))
        elif in_msgstr:
            if line.startswith('"'):
                parts.append(line.strip('"'))
            else:
                break
    return "".join(parts)


def load_csv_translations(csv_path):
    """Load translations from a CSV file with msgid,msgstr columns."""
    translations = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = [fn.lower().strip() for fn in reader.fieldnames or []]
        if "msgid" not in fieldnames or "msgstr" not in fieldnames:
            first_col = (reader.fieldnames or [""])[0]
            second_col = (reader.fieldnames or ["", ""])[1] if len(reader.fieldnames or []) > 1 else ""
            print(f"Warning: CSV columns are '{first_col}', '{second_col}'. Expected 'msgid', 'msgstr'.")
            print("Trying positional mapping (first column = source, second = translation).")
            f.seek(0)
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                if len(row) >= 2 and row[0].strip() and row[1].strip():
                    translations[row[0].strip()] = row[1].strip()
        else:
            for row in reader:
                src = row.get("msgid", "").strip()
                tgt = row.get("msgstr", "").strip()
                if src and tgt:
                    translations[src] = tgt
    return translations


def create_uk_po(csv_path=None, from_lang=None):
    if not os.path.exists(POT_FILE):
        print(f"Error: Template file not found: {POT_FILE}")
        sys.exit(1)

    with open(POT_FILE, "r", encoding="utf-8") as f:
        pot_content = f.read()

    pot_creation_date = extract_pot_creation_date(pot_content)
    revision_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    header = UK_HEADER.format(
        pot_creation_date=pot_creation_date,
        revision_date=revision_date,
    )

    entries = parse_po_entries(pot_content)

    translations = {}
    if from_lang:
        source_po = os.path.join(LOCALE_DIR, f"{from_lang}.po")
        if not os.path.exists(source_po):
            print(f"Error: Source .po file not found: {source_po}")
            sys.exit(1)
        translations = load_po_translations(source_po)
        print(f"Loaded {len(translations)} translations from {from_lang}.po")

    if csv_path:
        if not os.path.exists(csv_path):
            print(f"Error: CSV file not found: {csv_path}")
            sys.exit(1)
        csv_translations = load_csv_translations(csv_path)
        print(f"Loaded {len(csv_translations)} translations from {csv_path}")
        translations.update(csv_translations)

    filled_count = 0
    output_entries = []
    for entry in entries:
        msgid = extract_msgid(entry)
        if msgid in translations:
            entry = set_msgstr(entry, translations[msgid])
            filled_count += 1
        output_entries.append(entry)

    output = header + "\n" + "\n\n".join(output_entries) + "\n"

    with open(UK_PO_FILE, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Created {UK_PO_FILE}")
    print(f"  Total entries: {len(entries)}")
    print(f"  Filled translations: {filled_count}")
    print(f"  Empty (to translate): {len(entries) - filled_count}")


def enable_language():
    """Download frappe languages.csv and enable Ukrainian."""
    downloads_dir = os.path.expanduser("~/Downloads")

    print("Downloading frappe/geo/languages.csv from GitHub...")
    try:
        result = subprocess.run(
            [
                "gh", "api",
                "repos/frappe/frappe/contents/frappe/geo/languages.csv",
                "-H", "Accept: application/vnd.github.raw+json",
            ],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error downloading languages.csv: {e}")
        print("Make sure 'gh' (GitHub CLI) is installed and authenticated.")
        sys.exit(1)

    content = result.stdout
    patched = content.replace("uk,Українська,0", "uk,Українська,1")

    if patched == content:
        print("Ukrainian is already enabled (or not found in the file).")
    else:
        print("Patched: uk,Українська,0 -> uk,Українська,1")

    output_path = os.path.join(downloads_dir, "languages.csv")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(patched)

    print(f"\nSaved patched file to: {output_path}")
    print("\nTo apply, copy it to your Frappe installation:")
    print("  cp ~/Downloads/languages.csv <frappe-bench>/apps/frappe/frappe/geo/languages.csv")
    print("\nThen run in bench console:")
    print("  bench --site <site> execute frappe.core.doctype.language.language.sync_languages")
    print("  bench --site <site> clear-cache")


def main():
    parser = argparse.ArgumentParser(description="Create Ukrainian .po file for ERPNext")
    parser.add_argument("--from-lang", help="Copy translations from another .po file (e.g., 'ru' for Russian)")
    parser.add_argument("--csv", help="CSV file with msgid,msgstr columns to pre-fill translations")
    parser.add_argument("--enable-language", action="store_true", help="Download and patch languages.csv to enable Ukrainian")
    args = parser.parse_args()

    create_uk_po(csv_path=args.csv, from_lang=args.from_lang)

    if args.enable_language:
        print()
        enable_language()


if __name__ == "__main__":
    main()
