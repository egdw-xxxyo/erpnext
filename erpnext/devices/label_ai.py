"""AI assistant for the Label Template designer.

The model gets the same tools as the MCP server (read the template, read the reference, edit it,
render the printer-exact preview and look at it, use the label image library). It never saves:
it edits an in-memory draft of the open form, and every change is pushed to the page over
realtime so the canvas updates live. The user reviews and saves (or undoes) the result.

A run takes several model round-trips plus renders, so it runs as a background job.
"""

import base64
import json

import anthropic
import frappe
from frappe import _

from erpnext.ai_helper import tools as erp_tools
from erpnext.ai_helper.client import (
	OAUTH_SYSTEM_PREFIX,
	build_client,
	is_oauth,
	model_id,
	resolve_credentials,
)

EVENT = "label_ai"
MAX_STEPS = 24
MAX_TURNS = 30
MAX_MESSAGE_CHARS = 8000
MAX_RESULT_CHARS = 20000
LT = "erpnext.devices.doctype.label_template.label_template"
DRAFT_FIELDS = (
	"editor_mode",
	"html_template",
	"layout_json",
	"label_size",
	"field_mapping",
	"preview_data",
	"reference_doctype",
	"template_type",
	"description",
	"padding_top_mm",
	"padding_right_mm",
	"padding_bottom_mm",
	"padding_left_mm",
	"inputs",
)
EDITABLE = (
	"editor_mode",
	"html_template",
	"layout_json",
	"label_size",
	"field_mapping",
	"preview_data",
	"description",
	"padding_top_mm",
	"padding_right_mm",
	"padding_bottom_mm",
	"padding_left_mm",
	"inputs",
)
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
MAX_IMAGES_PER_MESSAGE = 4
MAX_IMAGE_B64 = 5_000_000
KEEP_IMAGE_TURNS = 2
INPUT_FIELDS = ("fieldname", "label", "fieldtype", "options", "default_value", "reqd")

SYSTEM_PROMPT = """You are the label design assistant inside ERPNext's Label Template designer.
The user is looking at one label template and asks you to create or change it. Labels are printed on
thermal printers at 300 dpi in black and white (1 mm = 11.81 px).

How to work:
- Start with get_label_template (the open, possibly unsaved draft). Read get_label_template_reference before
  your first edit: it documents the visual layout JSON, elements, markup and the HTML mode.
- Prefer the visual editor (editor_mode "Visual" + layout_json). Coordinates and sizes are in mm inside the
  padded area. Keep element ids stable when you move or restyle an element.
- After every edit call render_label_preview and LOOK at the image: check clipping, wrapping, overlaps,
  alignment and that barcodes/QR codes are large enough to scan. Fix and render again until it is right.
- Images: use list_label_images and reference them by file_name in image elements.
- Prefer the small tools for small changes: add_label_elements / update_label_element / remove_label_elements,
  add_print_input. Use edit_label_template with a full layout_json only for a redesign.
- Data the label needs that is not a plain field of the document (linked documents, attributes, child rows,
  counts, formatting) goes into the Data setup: Jinja that runs before the elements. Put results on doc with
  {% set _ = doc.update({"key": value}) %} and show them with Field elements (field "key"). Use
  get_data_sources to see what doc has, write it with set_data_setup and read the result it returns: fix
  every error and check every computed value against a real document (reference_name) when one exists.
  People cannot read Jinja, so keep it short and add a {# comment #} line per value explaining it.
- The user may paste images. A photo or screenshot of a label means "make it look like this": copy the
  layout, sizes and texts as closely as the elements allow. A logo or icon meant for the label goes into the
  library with add_pasted_image_to_library and then into an image element. Labels print in black and white.
- Values the operator types at print time (quantity, batch, operator name) are Print Inputs: add_print_input
  and an element of type "input" bound to it.
- You change only the draft on the user's screen. Nothing is saved until the user presses Save, and they can
  undo your changes. Never claim you saved anything.
- Reply in Ukrainian unless the user writes in another language. Keep the final answer short: what you
  changed and anything the user must check or decide (Markdown allowed)."""

LABEL_TOOLS = [
	{
		"name": "get_label_template",
		"description": "Read the open label template draft: editor_mode, layout_json, html_template, label size "
		"(with width/height in mm), padding, inputs (Print Inputs), preview_data, field_mapping.",
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "get_label_template_reference",
		"description": "Authoring reference for label templates (visual layout JSON, elements, markup, HTML mode, "
		"utility classes) plus published snippet examples. Read it before the first edit.",
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "edit_label_template",
		"description": "Change fields of the open draft (only the ones you pass). layout_json is the full visual "
		"layout (object or JSON string) and replaces the current one; it is validated and compiled. inputs replaces "
		"the whole Print Inputs list. In Visual mode html_template is generated, do not set it.",
		"input_schema": {
			"type": "object",
			"properties": {
				"editor_mode": {"type": "string", "enum": ["HTML", "Visual"]},
				"layout_json": {"description": "Visual layout object or JSON string"},
				"html_template": {"type": "string"},
				"label_size": {"type": "string", "description": "Label Size name"},
				"padding_top_mm": {"type": "number"},
				"padding_right_mm": {"type": "number"},
				"padding_bottom_mm": {"type": "number"},
				"padding_left_mm": {"type": "number"},
				"preview_data": {"description": "Sample doc used by previews (object or JSON string)"},
				"field_mapping": {"description": "Object or JSON string"},
				"description": {"type": "string"},
				"inputs": {
					"type": "array",
					"items": {
						"type": "object",
						"properties": {
							"fieldname": {"type": "string"},
							"label": {"type": "string"},
							"fieldtype": {
								"type": "string",
								"enum": ["Data", "Small Text", "Int", "Float", "Date", "Select", "Check"],
							},
							"options": {"type": "string"},
							"default_value": {"type": "string"},
							"reqd": {"type": "boolean"},
						},
						"required": ["fieldname", "label"],
					},
				},
			},
		},
	},
	{
		"name": "render_label_preview",
		"description": "Render the draft exactly as the printer gets it and return the image. Fills doc from "
		"preview_data (or a real document via reference_name) and Print Inputs from input_values.",
		"input_schema": {
			"type": "object",
			"properties": {
				"input_values": {"type": "object", "additionalProperties": True},
				"reference_name": {"type": "string"},
			},
		},
	},
	{
		"name": "get_data_sources",
		"description": "What the label can show: fields of the reference DocType (with child tables and links), "
		"preview_data keys, Print Inputs, keys made by the Data setup, and whether a real document exists to test with.",
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "set_data_setup",
		"description": "Replace the visual layout's Data setup (Jinja run before the elements) and test it at once. "
		"Returns the doc values and variables it produced, or the error. Pass reference_name to test on a real "
		"document of the reference DocType.",
		"input_schema": {
			"type": "object",
			"properties": {
				"setup": {"type": "string"},
				"reference_name": {"type": "string"},
				"input_values": {"type": "object", "additionalProperties": True},
			},
			"required": ["setup"],
		},
	},
	{
		"name": "test_data_setup",
		"description": "Run the current Data setup without changing it and show what it produces.",
		"input_schema": {
			"type": "object",
			"properties": {
				"reference_name": {"type": "string"},
				"input_values": {"type": "object", "additionalProperties": True},
			},
		},
	},
	{
		"name": "add_label_elements",
		"description": "Append elements to the visual layout (same element objects as in layout_json; id is "
		"generated when missing). Returns the ids.",
		"input_schema": {
			"type": "object",
			"properties": {"elements": {"type": "array", "items": {"type": "object"}}},
			"required": ["elements"],
		},
	},
	{
		"name": "update_label_element",
		"description": "Change properties of one element by id. style is merged key by key; other keys replace.",
		"input_schema": {
			"type": "object",
			"properties": {"id": {"type": "string"}, "changes": {"type": "object"}},
			"required": ["id", "changes"],
		},
	},
	{
		"name": "remove_label_elements",
		"description": "Remove elements by id.",
		"input_schema": {
			"type": "object",
			"properties": {"ids": {"type": "array", "items": {"type": "string"}}},
			"required": ["ids"],
		},
	},
	{
		"name": "add_print_input",
		"description": "Add (or replace by fieldname) a Print Input: a value asked in the Print dialog, available "
		'as doc.<fieldname>. Show it with an element {"type": "input", "input": fieldname}.',
		"input_schema": {
			"type": "object",
			"properties": {
				"fieldname": {"type": "string"},
				"label": {"type": "string"},
				"fieldtype": {
					"type": "string",
					"enum": ["Data", "Small Text", "Int", "Float", "Date", "Select", "Check"],
				},
				"options": {"type": "string"},
				"default_value": {"type": "string"},
				"reqd": {"type": "boolean"},
			},
			"required": ["fieldname", "label"],
		},
	},
	{
		"name": "add_pasted_image_to_library",
		"description": "Save an image the user pasted into the chat (numbered [Pasted image N]) to the shared "
		"label image library, so an image element can use it. Only for pictures that should be printed (logos, "
		"icons); not for screenshots or photos of a label to copy. Returns the stored file_name.",
		"input_schema": {
			"type": "object",
			"properties": {
				"image_number": {"type": "integer"},
				"file_name": {"type": "string", "description": "Name with extension, e.g. company-logo.png"},
			},
			"required": ["image_number", "file_name"],
		},
	},
	{
		"name": "list_label_images",
		"description": "List the shared label image library (file_name, file_url).",
		"input_schema": {"type": "object", "properties": {"search": {"type": "string"}}},
	},
	{
		"name": "get_label_image",
		"description": "Look at one image of the label image library.",
		"input_schema": {
			"type": "object",
			"properties": {"file_name": {"type": "string"}},
			"required": ["file_name"],
		},
	},
	{
		"name": "list_label_templates",
		"description": "List other label templates (name, label_size, editor_mode) to reuse their design.",
		"input_schema": {"type": "object", "properties": {"search": {"type": "string"}}},
	},
	{
		"name": "get_other_label_template",
		"description": "Read a saved label template by name (layout_json, html_template, size, padding).",
		"input_schema": {
			"type": "object",
			"properties": {"name": {"type": "string"}},
			"required": ["name"],
		},
	},
]
ERP_TOOL_NAMES = ("get_doctype_fields", "get_documents")
TOOLS = LABEL_TOOLS + [t for t in erp_tools.TOOL_SCHEMAS if t["name"] in ERP_TOOL_NAMES]


def _check_access():
	if not frappe.has_permission("Label Template", "write"):
		frappe.throw(
			_("Only users who edit label templates can use the label assistant"), frappe.PermissionError
		)


def _clean_images(raw):
	images = []
	for img in (raw or [])[:MAX_IMAGES_PER_MESSAGE]:
		media, data = img.get("media_type"), img.get("data") or ""
		if media in IMAGE_TYPES and data and len(data) <= MAX_IMAGE_B64:
			images.append({"media_type": media, "data": data, "name": str(img.get("name") or "")[:80]})
	return images


def _clean_history(raw):
	"""Text turns plus pasted images; only the last KEEP_IMAGE_TURNS image turns keep their pixels.

	Returns (history for the model, pasted images of the whole conversation in order).
	"""
	if not isinstance(raw, list):
		frappe.throw(_("Nothing to send"))
	turns = []
	for m in raw[-MAX_TURNS:]:
		text = str(m.get("content") or "")[:MAX_MESSAGE_CHARS]
		images = _clean_images(m.get("images")) if m.get("role") == "user" else []
		if m.get("role") in ("user", "assistant") and (text or images):
			turns.append((m["role"], text, images))
	while turns and turns[0][0] != "user":
		turns.pop(0)
	if not turns or turns[-1][0] != "user":
		frappe.throw(_("Nothing to send"))

	image_turns = [i for i, t in enumerate(turns) if t[2]]
	keep = set(image_turns[-KEEP_IMAGE_TURNS:])
	pasted, history = [], []
	for i, (role, text, images) in enumerate(turns):
		if not images:
			history.append({"role": role, "content": text})
			continue
		blocks = []
		for img in images:
			pasted.append(img)
			number = len(pasted)
			if i in keep:
				blocks.append(
					{
						"type": "text",
						"text": f"[Pasted image {number}{': ' + img['name'] if img['name'] else ''}]",
					}
				)
				blocks.append(
					{
						"type": "image",
						"source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
					}
				)
			else:
				blocks.append({"type": "text", "text": f"[Pasted image {number} — no longer attached]"})
		blocks.append({"type": "text", "text": text or "(see the pasted image)"})
		history.append({"role": role, "content": blocks})
	return history, pasted


def _clean_draft(raw):
	draft = {k: raw.get(k) for k in DRAFT_FIELDS if k in raw}
	draft["inputs"] = [{k: r.get(k) for k in INPUT_FIELDS} for r in (raw.get("inputs") or [])]
	return draft


@frappe.whitelist(methods=["POST"])
def start(label_template, messages, draft, run_id):
	_check_access()
	credentials = resolve_credentials()
	if not credentials:
		return {
			"ok": False,
			"error": _("No AI key is set up. Add one in My Settings or ask an administrator."),
		}
	history, pasted = _clean_history(frappe.parse_json(messages))
	draft = _clean_draft(frappe.parse_json(draft) or {})
	frappe.enqueue(
		"erpnext.devices.label_ai.run",
		queue="long",
		timeout=900,
		label_template=label_template,
		history=history,
		pasted=pasted,
		draft=draft,
		run_id=str(run_id)[:40],
		user=frappe.session.user,
	)
	return {"ok": True}


def _publish(user, run_id, **payload):
	frappe.publish_realtime(EVENT, {"run_id": run_id, **payload}, user=user, after_commit=False)


def run(label_template, history, draft, run_id, user, pasted=None):
	frappe.set_user(user)
	credentials = resolve_credentials(user)
	try:
		session = Session(label_template, draft, lambda **p: _publish(user, run_id, **p), pasted)
		reply = session.chat(credentials, history)
		_publish(user, run_id, type="done", reply=reply, draft=session.draft if session.changed else None)
	except anthropic.AuthenticationError:
		_publish(user, run_id, type="error", error=_("The AI key was rejected. Check it in My Settings."))
	except anthropic.RateLimitError:
		_publish(user, run_id, type="error", error=_("AI rate limit reached, try again in a minute."))
	except anthropic.APIConnectionError:
		_publish(user, run_id, type="error", error=_("Cannot reach the AI service."))
	except Exception as e:
		frappe.log_error(title="Label AI")
		_publish(user, run_id, type="error", error=str(e)[:500] or _("The label assistant failed."))


class Session:
	def __init__(self, label_template, draft, publish, pasted=None):
		self.name = label_template
		self.pasted = pasted or []
		self.draft = draft
		self.publish = publish
		self.changed = False

	def chat(self, credentials, history):
		client = build_client(credentials["token"])
		system = []
		if is_oauth(credentials["token"]):
			system.append({"type": "text", "text": OAUTH_SYSTEM_PREFIX})
		system.append({"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}})
		system.append({"type": "text", "text": f"Template: {self.name}\nUser: {frappe.session.user}"})
		conversation = list(history)

		for _step in range(MAX_STEPS):
			response = client.messages.create(
				model=model_id(credentials["model"]),
				max_tokens=8192,
				system=system,
				tools=TOOLS,
				messages=conversation,
			)
			text = "".join(b.text for b in response.content if b.type == "text").strip()
			if response.stop_reason == "refusal":
				return _("The AI declined to answer this request.")
			if response.stop_reason != "tool_use":
				return text or _("Done.")
			if text:
				self.publish(type="status", text=text[:500])
			conversation.append({"role": "assistant", "content": response.content})
			results = []
			for block in response.content:
				if block.type != "tool_use":
					continue
				self.publish(type="tool", tool=block.name)
				content, is_error = self.execute(block.name, block.input or {})
				results.append(
					{"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
				)
			conversation.append({"role": "user", "content": results})
		return _("Stopped after too many steps. Look at the label and ask again for what is still missing.")

	def execute(self, name, args):
		try:
			if name in ERP_TOOL_NAMES:
				out, err = erp_tools.execute(name, args)
				return out, err
			result = getattr(self, f"tool_{name}")(**args)
		except Exception as e:
			frappe.clear_messages()
			return f"{type(e).__name__}: {e}"[:2000], True
		if isinstance(result, list):
			return result, False
		return json.dumps(result, ensure_ascii=False, default=str)[:MAX_RESULT_CHARS], False

	def _size(self):
		size = self.draft.get("label_size")
		if not size:
			return None
		return frappe.db.get_value("Label Size", size, ["width_mm", "height_mm"], as_dict=True)

	def tool_get_label_template(self):
		return {"name": self.name, **self.draft, "label_size_mm": self._size()}

	def tool_get_label_template_reference(self):
		from erpnext.devices.doctype.label_template.label_template import get_template_reference

		ref = get_template_reference()
		return {"reference_md": ref.get("reference_md"), "examples": ref.get("examples")}

	def tool_edit_label_template(self, **fields):
		from erpnext.devices.label_layout import compile_layout, parse_layout

		unknown = set(fields) - set(EDITABLE)
		if unknown:
			frappe.throw(_("Cannot edit: {0}").format(", ".join(sorted(unknown))))
		for key in ("layout_json", "preview_data", "field_mapping"):
			if key in fields and fields[key] is not None and not isinstance(fields[key], str):
				fields[key] = json.dumps(fields[key], ensure_ascii=False)
		if "layout_json" in fields:
			compile_layout(parse_layout(fields["layout_json"]))
		if "inputs" in fields:
			rows = []
			for r in fields["inputs"] or []:
				if not str(r.get("fieldname") or "").isidentifier():
					frappe.throw(_("Invalid input fieldname {0}").format(r.get("fieldname")))
				rows.append({k: (1 if r.get(k) else 0) if k == "reqd" else r.get(k) for k in INPUT_FIELDS})
			fields["inputs"] = rows
		if fields.get("label_size") and not frappe.db.exists("Label Size", fields["label_size"]):
			frappe.throw(_("Label Size {0} does not exist").format(fields["label_size"]))
		self.draft.update(fields)
		self.changed = True
		self.publish(type="draft", draft=self.draft)
		return {"ok": True, "changed": sorted(fields)}

	def tool_render_label_preview(self, input_values=None, reference_name=None):
		from erpnext.devices.doctype.label_template.label_template import render_template_preview

		r = render_template_preview(
			doc=json.dumps(self.draft, ensure_ascii=False, default=str),
			inputs=json.dumps(input_values or {}),
			reference_name=reference_name,
			sample=1,
		)
		if not r:
			return "Nothing to render: set label_size and a layout or HTML first."
		return [
			{
				"type": "image",
				"source": {"type": "base64", "media_type": "image/png", "data": r["image_base64"]},
			},
			{
				"type": "text",
				"text": f"{r['width_mm']} x {r['height_mm']} mm, {r['width_dots']} x {r['height_dots']} dots "
				f"@ {r['dpi']} dpi (1 mm = {r['dpi'] / 25.4:.2f} px).",
			},
		]

	def _layout(self):
		from erpnext.devices.label_layout import parse_layout

		if self.draft.get("editor_mode") != "Visual" and not self.draft.get("layout_json"):
			frappe.throw(
				_("The template is in HTML mode. Switch it to Visual with edit_label_template first.")
			)
		return parse_layout(self.draft.get("layout_json"))

	def _save_layout(self, layout):
		self.tool_edit_label_template(layout_json=layout, editor_mode="Visual")

	def _test_setup(self, setup, reference_name=None, input_values=None):
		from erpnext.devices.doctype.label_template.label_template import run_data_setup

		tpl = frappe._dict(self.draft)
		tpl.inputs = [frappe._dict(r) for r in self.draft.get("inputs") or []]
		return run_data_setup(tpl, setup, json.dumps(input_values or {}), reference_name, sample=1)

	def tool_get_data_sources(self):
		import re

		dt = self.draft.get("reference_doctype")
		out = {"reference_doctype": dt, "fields": [], "child_tables": {}, "links": {}}
		if dt:
			meta = frappe.get_meta(dt)
			for f in meta.fields:
				if f.fieldtype in (
					"Section Break",
					"Column Break",
					"Tab Break",
					"HTML",
					"Button",
					"Password",
				):
					continue
				if f.fieldtype == "Table":
					cm = frappe.get_meta(f.options)
					out["child_tables"][f.fieldname] = {
						"doctype": f.options,
						"fields": [
							c.fieldname
							for c in cm.fields
							if c.fieldtype not in ("Section Break", "Column Break")
						],
					}
				else:
					out["fields"].append(
						f"{f.fieldname} ({f.fieldtype}{': ' + f.options if f.options and f.fieldtype == 'Link' else ''}) {f.label or ''}".strip()
					)
				if f.fieldtype == "Link":
					out["links"][f.fieldname] = f.options
			out["sample_documents"] = frappe.get_list(dt, fields=["name"], order_by="modified desc", limit=3)
		try:
			out["preview_data_keys"] = sorted(json.loads(self.draft.get("preview_data") or "{}"))
		except ValueError:
			out["preview_data_keys"] = "preview_data is not valid JSON"
		out["print_inputs"] = [r.get("fieldname") for r in self.draft.get("inputs") or []]
		setup = ""
		try:
			setup = self._layout().get("setup") or ""
		except Exception:
			frappe.clear_messages()
		out["data_setup_keys"] = sorted(
			set(
				re.findall(
					r"[\"']([A-Za-z_]\w*)[\"']\s*:",
					" ".join(re.findall(r"doc\.update\((.*?)\)", setup, re.S)),
				)
			)
		)
		return out

	def tool_set_data_setup(self, setup, reference_name=None, input_values=None):
		layout = self._layout()
		layout["setup"] = (setup or "").strip()
		self._save_layout(layout)
		return {
			"saved_to_draft": True,
			"test": self._test_setup(layout["setup"], reference_name, input_values),
		}

	def tool_test_data_setup(self, reference_name=None, input_values=None):
		return self._test_setup(self._layout().get("setup") or "", reference_name, input_values)

	def tool_add_label_elements(self, elements):
		layout = self._layout()
		ids = []
		for el in elements or []:
			el = dict(el)
			el.setdefault("id", frappe.generate_hash(length=8))
			el.setdefault("rotate", 0)
			layout.setdefault("elements", []).append(el)
			ids.append(el["id"])
		self._save_layout(layout)
		return {"added": ids}

	def tool_update_label_element(self, id, changes):
		layout = self._layout()
		el = next((e for e in layout.get("elements") or [] if e.get("id") == id), None)
		if not el:
			frappe.throw(_("No element with id {0}").format(id))
		changes = dict(changes or {})
		changes.pop("id", None)
		if isinstance(changes.get("style"), dict):
			el["style"] = {**(el.get("style") or {}), **changes.pop("style")}
		el.update(changes)
		self._save_layout(layout)
		return {"updated": id, "element": el}

	def tool_remove_label_elements(self, ids):
		layout = self._layout()
		keep = [e for e in layout.get("elements") or [] if e.get("id") not in set(ids or [])]
		removed = len(layout.get("elements") or []) - len(keep)
		layout["elements"] = keep
		self._save_layout(layout)
		return {"removed": removed}

	def tool_add_print_input(self, fieldname, label, **row):
		rows = [r for r in self.draft.get("inputs") or [] if r.get("fieldname") != fieldname]
		rows.append(
			{"fieldname": fieldname, "label": label, "fieldtype": row.get("fieldtype") or "Data", **row}
		)
		self.tool_edit_label_template(inputs=rows)
		return {"print_inputs": [r["fieldname"] for r in self.draft["inputs"]]}

	def tool_add_pasted_image_to_library(self, image_number, file_name):
		import os

		from erpnext.devices.label_images import _save_image

		if not 1 <= int(image_number) <= len(self.pasted):
			frappe.throw(_("There is no pasted image {0}").format(image_number))
		img = self.pasted[int(image_number) - 1]
		ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}[
			img["media_type"]
		]
		base = os.path.splitext(os.path.basename(file_name or "pasted"))[0] or "pasted"
		return _save_image(base + ext, base64.b64decode(img["data"]))

	def tool_list_label_images(self, search=None):
		from erpnext.devices.label_images import get_label_images

		q = (search or "").lower()
		return [
			{"file_name": f.file_name, "file_url": f.file_url}
			for f in get_label_images()
			if not q or q in f.file_name.lower()
		]

	def tool_get_label_image(self, file_name):
		import os

		from erpnext.devices.label_images import FOLDER, file_path

		row = frappe.db.get_value(
			"File", {"folder": FOLDER, "file_name": file_name}, ["file_url", "is_private"], as_dict=True
		)
		path = row and file_path(row)
		if not path or not os.path.exists(path):
			return f"No image {file_name} in the label image library."
		data = open(path, "rb").read()
		if file_name.lower().endswith(".svg"):
			return f"{file_name} (SVG):\n{data.decode('utf-8', 'replace')[:MAX_RESULT_CHARS]}"
		mime = {
			"jpg": "image/jpeg",
			"jpeg": "image/jpeg",
			"png": "image/png",
			"gif": "image/gif",
			"webp": "image/webp",
		}
		media = mime.get(file_name.rsplit(".", 1)[-1].lower())
		if not media:
			return f"{file_name}: format not viewable here."
		return [
			{
				"type": "image",
				"source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()},
			},
			{"type": "text", "text": file_name},
		]

	def tool_list_label_templates(self, search=None):
		filters = {"name": ["like", f"%{search}%"]} if search else {}
		return frappe.get_list(
			"Label Template",
			filters=filters,
			fields=["name", "label_size", "editor_mode", "template_type"],
			limit=100,
		)

	def tool_get_other_label_template(self, name):
		doc = frappe.get_doc("Label Template", name)
		doc.check_permission("read")
		return {
			k: doc.get(k)
			for k in (
				"name",
				"editor_mode",
				"layout_json",
				"html_template",
				"label_size",
				"padding_top_mm",
				"padding_right_mm",
				"padding_bottom_mm",
				"padding_left_mm",
				"preview_data",
			)
		}
