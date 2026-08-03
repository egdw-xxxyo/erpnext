"""Graphify extractor for Frappe DocType JSON.

Graphify's stock ``.json`` handling (``graphify/extractors/json_config.py``)
only recognizes config/manifest files — package.json, tsconfig.json, or any
JSON with a top-level ``dependencies``/``extends``/``$schema`` key. Everything
else is treated as data JSON and skipped, which drops every DocType schema in
this repo from the graph.

In Frappe the DocType JSON *is* the model: Link/Table fields are the foreign
keys of the whole system. This extractor emits one node per DocType plus the
edges those fields describe, and falls back to the stock extractor for any
other JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from graphify.extractors.base import _make_id

# Fieldtypes whose ``options`` names another DocType.
_LINK_FIELDTYPES = {"Link": "links", "Table": "contains", "Table MultiSelect": "contains"}


def _is_doctype_json(obj: dict) -> bool:
    return (
        obj.get("doctype") == "DocType"
        and isinstance(obj.get("name"), str)
        and ("fields" in obj or "field_order" in obj)
    )


def _fieldname_lines(source: str) -> dict[str, int]:
    """Map fieldname -> 1-based line, so edges point at the field that made them."""
    lines = {}
    for match in re.finditer(r'"fieldname"\s*:\s*"([^"]+)"', source):
        lines.setdefault(match.group(1), source.count("\n", 0, match.start()) + 1)
    return lines


def extract_doctype(path: Path, obj: dict, source: str) -> dict:
    name = obj["name"]
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()

    def add_node(nid: str, label: str, line: int, file_type: str = "code") -> None:
        if nid and nid not in seen:
            seen.add(nid)
            nodes.append({
                "id": nid, "label": label, "file_type": file_type,
                "source_file": str_path, "source_location": f"L{line}",
            })

    def add_edge(src: str, tgt: str, relation: str, line: int, context: str | None = None) -> None:
        if not src or not tgt or src == tgt:
            return
        edge = {
            "source": src, "target": tgt, "relation": relation,
            "confidence": "EXTRACTED", "source_file": str_path,
            "source_location": f"L{line}", "weight": 1.0,
        }
        if context:
            edge["context"] = context
        edges.append(edge)

    # Only this DocType's own node is emitted. Cross-DocType references are
    # edges to the target's ID with no stub node: graphify's dedup pass
    # (``dedup._defines_id``) only lets a node own an ID whose prefix derives
    # from its own source_file, so a stub minted by a *referencing* file loses
    # any collision and gets renamed to ``<referencing_file>_doctype_<name>``.
    # That forked one shared node into dozens of private copies. Emitting no
    # stub means the edge resolves against the node the target's own file
    # emits, and references to DocTypes outside the corpus simply drop.
    doctype_nid = _make_id("doctype", name)
    add_node(doctype_nid, name, 1)

    # No edge is emitted to the sibling .py/.js controller. Graphify's file-node
    # IDs are not a single stable form — a prefix-remap pass leaves some files
    # canonical (``erpnext_accounts_doctype_advance_tax_advance_tax``) and others
    # doubled (``..._workplace_py_erpnext_manufacturing_doctype_workplace_workplace``),
    # so no single computed target matches both and the edge silently dangles.
    # The link is redundant anyway: the controller class shares the DocType's
    # name and directory, so clustering already groups them.

    field_lines = _fieldname_lines(source)
    for field in obj.get("fields", []):
        if not isinstance(field, dict):
            continue
        relation = _LINK_FIELDTYPES.get(field.get("fieldtype"))
        target = field.get("options")
        if not relation or not isinstance(target, str) or not target.strip():
            continue
        fieldname = field.get("fieldname") or ""
        line = field_lines.get(fieldname, 1)
        add_edge(doctype_nid, _make_id("doctype", target.strip()), relation, line,
                 context=fieldname)

    for link in obj.get("links", []):
        if not isinstance(link, dict):
            continue
        target = link.get("link_doctype")
        if not isinstance(target, str) or not target.strip():
            continue
        add_edge(doctype_nid, _make_id("doctype", target.strip()), "dashboard_link", 1,
                 context=link.get("link_fieldname") or None)

    return {"nodes": nodes, "edges": edges}


def make_json_extractor(stock_extract_json):
    """Wrap graphify's stock .json extractor with DocType support."""

    def extract_json(path: Path) -> dict:
        try:
            source = Path(path).read_text(encoding="utf-8")
            obj = json.loads(source)
        except Exception:
            return stock_extract_json(path)
        if isinstance(obj, dict) and _is_doctype_json(obj):
            try:
                return extract_doctype(Path(path), obj, source)
            except Exception as exc:
                return {"nodes": [], "edges": [], "error": f"doctype extract failed: {exc}"}
        return stock_extract_json(path)

    return extract_json
