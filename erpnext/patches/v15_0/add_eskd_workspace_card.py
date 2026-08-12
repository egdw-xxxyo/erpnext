import json

import frappe

WORKSPACE = "Stock"
CARD = "ESKD Documentation"
BLOCK_ID = "eskdDocsCard"

CARD_LINKS = [
	("ESKD Document", "DocType"),
	("ESKD Document Type", "DocType"),
	("ESKD Product", "DocType"),
	("Specification Component Role", "DocType"),
	("Specification", "DocType"),
	("Specification Number Template", "DocType"),
	("Item Specification", "DocType"),
	("ESKD BpAK Matrix", "Page"),
]
PAGE_ROUTES = {"ESKD BpAK Matrix": "eskd-bpak-matrix"}


def execute():
	"""Append the ЄСКД card to the Stock workspace.

	The workspace is edited in the desk on our sites, so its DB copy no longer syncs from
	the repo JSON — appending here keeps those edits and stays idempotent.
	"""
	if not frappe.db.exists("Workspace", WORKSPACE):
		return

	workspace = frappe.get_doc("Workspace", WORKSPACE)
	if any(link.type == "Card Break" and link.label == CARD for link in workspace.links):
		return

	workspace.append("links", {"type": "Card Break", "label": CARD, "link_count": 0, "hidden": 0})
	for label, link_type in CARD_LINKS:
		workspace.append(
			"links",
			{
				"type": "Link",
				"label": label,
				"link_type": link_type,
				"link_to": PAGE_ROUTES.get(label, label),
				"link_count": 0,
				"hidden": 0,
				"onboard": 0,
			},
		)

	content = json.loads(workspace.content or "[]")
	if not any(block.get("id") == BLOCK_ID for block in content):
		content.append({"id": BLOCK_ID, "type": "card", "data": {"card_name": CARD, "col": 4}})
		workspace.content = json.dumps(content, separators=(",", ":"), ensure_ascii=False)

	workspace.save(ignore_permissions=True)
