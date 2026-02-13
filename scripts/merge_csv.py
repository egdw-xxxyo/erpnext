#!/usr/bin/env python3
"""Merge new CSV translations into existing ones. Used during Docker build."""
import csv
import io
import sys


def merge(existing_path, new_path):
    trans = {}
    with open(existing_path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0] and row[1]:
                trans[row[0]] = row[1]
    print(f"  Existing: {len(trans)}")

    added = 0
    with open(new_path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0] and row[1]:
                if row[0] not in trans:
                    added += 1
                trans[row[0]] = row[1]
    print(f"  After merge: {len(trans)} (+{added} new)")

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for k in sorted(trans.keys()):
        writer.writerow([k, trans[k]])
    with open(existing_path, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())


if __name__ == "__main__":
    existing = sys.argv[1]
    new = sys.argv[2]
    merge(existing, new)
