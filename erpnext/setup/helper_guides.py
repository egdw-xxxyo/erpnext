import json
import re
from hashlib import sha256
from math import isfinite
from pathlib import Path

import frappe
from frappe import _
from frappe.model import NO_VALUE_FIELDS
from frappe.model.workflow import get_workflow, get_workflow_name

GUIDE = "Helper Guide"
EMOTION = "Helper Emotion"
SETTINGS = "Helper Settings"
SCHEMA_VERSION = 1
KEY_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
STEP_TYPES = ("field", "action", "wait", "rule")
FORM_ACTIONS = ("save", "submit", "update")
VALUE_CHECKS = ("empty", "required_empty", "required_positive", "required_nonnegative")
FIELD_OPERATORS = ("equals", "not_equals", "in", "not_in", "empty", "filled")
PROCUREMENT_GUIDES = ("Material Request", "Consolidated Purchase Order")
BUILTIN_EMOTIONS = {
	"ready": "/assets/erpnext/images/illustrations/procurement-piksel.png",
	"waiting": "/assets/erpnext/images/illustrations/procurement-piksel-waiting.png",
	"complete": "/assets/erpnext/images/illustrations/procurement-piksel-complete.png",
}
PROCUREMENT_TARGETS = {
	"Material Request": ("request_create", "request_links"),
	"Consolidated Purchase Order": (
		"stock_warehouse", "initiator", "optional_invoice", "route", "complete", "review", "buyer_save",
		"buyer_actions", "buyer_route", "create_invoice", "missing_invoice", "attach_delivery_note",
		"payment_route", "wait_preparation", "wait_department", "wait_final", "wait_post", "wait_invoices",
		"wait_payment", "wait_warehouse", "wait_delivery_notes",
	),
}


def target_meta(doctype):
	if not isinstance(doctype, str) or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("Choose an existing target DocType."))
	meta = frappe.get_meta(doctype)
	if meta.istable:
		frappe.throw(_("Choose a DocType that opens as a form."))
	return meta


def form_fields(meta):
	"""Describe valid targets using the same paths as the guide runner."""
	for field in meta.fields:
		if field.hidden or field.fieldtype == "Password":
			continue
		if field.fieldtype in NO_VALUE_FIELDS and field.fieldtype != "Table":
			continue
		yield field.fieldname, field
		if field.fieldtype == "Table" and field.options:
			for child in frappe.get_meta(field.options).fields:
				if (
					not child.hidden
					and child.fieldtype not in NO_VALUE_FIELDS
					and child.fieldtype != "Password"
				):
					yield f"{field.fieldname}.{child.fieldname}", child


def workflow_actions(doctype):
	if not get_workflow_name(doctype):
		return []
	return sorted({f"workflow:{row.action}" for row in get_workflow(doctype).transitions if row.action})


def allowed_rules(doctype):
	return [f"procurement_{target}" for target in PROCUREMENT_TARGETS.get(doctype, ())]


def condition_fields(meta):
	return {
		df.fieldname
		for df in meta.fields
		if df.fieldtype != "Password" and (df.fieldtype not in NO_VALUE_FIELDS or df.fieldtype == "Table")
	}


def parse_conditions(raw):
	try:
		return json.loads(raw) if raw else []
	except (ValueError, RecursionError):
		frappe.throw(_("Field conditions must be a valid JSON array."))


def valid_conditions(conditions, fields):
	def scalar(value):
		return value is None or type(value) in (str, int, bool) or (type(value) is float and isfinite(value))

	if not isinstance(conditions, list) or len(conditions) > 20:
		return False
	for condition in conditions:
		if not isinstance(condition, dict) or set(condition) - {"field", "operator", "value"}:
			return False
		field = condition.get("field")
		operator = condition.get("operator")
		if not isinstance(field, str) or field not in fields or operator not in FIELD_OPERATORS:
			return False
		value = condition.get("value")
		if operator in ("empty", "filled"):
			if "value" in condition:
				return False
		elif "value" not in condition:
			return False
		elif operator in ("in", "not_in"):
			if not isinstance(value, list) or not 0 < len(value) <= 50 or not all(map(scalar, value)):
				return False
		elif not scalar(value):
			return False
	return True


def validate_guide(doc):
	doc.guide_title = (doc.guide_title or "").strip()
	if not doc.guide_title:
		frappe.throw(_("Enter a guide title."))
	if not 1 <= len(doc.steps) <= 200:
		frappe.throw(_("A guide must have between 1 and 200 steps."))
	meta = target_meta(doc.target_doctype)
	fields = dict(form_fields(meta))
	actions = set(FORM_ACTIONS).union(workflow_actions(meta.name))
	rules = allowed_rules(meta.name)
	filter_fields = condition_fields(meta)
	keys = set()

	for row in doc.steps:
		def invalid(message):
			frappe.throw(_("Step {0}: {1}").format(row.idx, message))

		if not KEY_PATTERN.fullmatch(row.step_key or "") or row.step_key in keys:
			invalid(_("Each step needs a unique lowercase step key."))
		keys.add(row.step_key)
		kind = (row.step_type or "").lower()
		row.target = (row.target or "").strip()
		row.hint = (row.hint or "").strip()
		if kind not in STEP_TYPES:
			invalid(_("Choose a valid step type."))
		if not row.hint:
			invalid(_("Enter the hint to show at this step."))
		if kind == "field" and (row.target not in fields or fields[row.target].read_only):
			invalid(_("Choose an editable form field or a table field."))
		if kind == "action" and row.target not in actions:
			invalid(_("Choose a supported form or workflow action."))
		if kind == "wait" and row.target and ("." in row.target or row.target not in fields):
			invalid(_("Choose a form field for the waiting hint or leave the target empty."))
		if kind == "rule" and row.target not in rules:
			invalid(_("This rule is unavailable for the target DocType."))
		if row.emotion and not frappe.db.exists(EMOTION, row.emotion):
			invalid(_("Choose an existing helper emotion."))
		if row.document_status not in (None, "", "0", "1", "2"):
			invalid(_("Use document status 0, 1, or 2."))
		if row.value_check and (kind != "field" or row.value_check not in VALUE_CHECKS):
			invalid(_("Choose a supported field value check."))
		if not valid_conditions(parse_conditions(row.field_conditions), filter_fields):
			invalid(_("Check field conditions, field names and operators."))

	doc.active_key = sha256(f"{meta.name}\0{doc.guide_title.casefold()}".encode()).hexdigest() if doc.enabled else None
	if doc.active_key and frappe.db.exists(
		GUIDE, {"active_key": doc.active_key, "name": ["!=", doc.name or ""]}
	):
		frappe.throw(_("An active guide named {0} already exists for this DocType.").format(doc.guide_title))


def mascot_settings():
	settings = frappe.get_cached_doc(SETTINGS)
	emotions = frappe.get_all(EMOTION, fields=["name", "image"], order_by="name")
	return {
		"name": settings.mascot_name or "Піксель",
		"default_emotion": settings.default_emotion or "ready",
		"emotions": {row.name: row.image for row in emotions},
	}


def serialize_steps(doc):
	steps = []
	for row in doc.steps:
		kind = row.step_type.lower()
		when = {}
		if row.document_status not in (None, ""):
			when["docstatus"] = int(row.document_status)
		if row.workflow_state:
			when["workflow_state"] = row.workflow_state
		if row.required_role:
			when["role"] = row.required_role
		if kind == "field":
			when["value"] = row.value_check or "empty"
		if row.field_conditions:
			when["fields"] = parse_conditions(row.field_conditions)
		step = {"id": row.step_key, "type": kind, "when": when, "hint": row.hint or "", "emotion": row.emotion or ""}
		if kind == "field":
			step["field"] = row.target
		elif row.target:
			step["target"] = row.target
		steps.append(step)
	return steps


def serialize_guide(doc):
	return {
		"schema_version": SCHEMA_VERSION,
		"target_doctype": doc.target_doctype,
		"title": doc.guide_title,
		"steps": serialize_steps(doc),
	}


def builtin_guide(meta):
	if meta.name not in PROCUREMENT_GUIDES:
		return
	path = Path(__file__).with_name("helper_guide_templates") / f"{frappe.scrub(meta.name)}.json"
	data = json.loads(path.read_text(encoding="utf-8"))
	editable = {path for path, field in form_fields(meta) if not field.read_only}
	fields = condition_fields(meta)
	data["steps"] = [
		step for step in data["steps"]
		if (step["type"] != "field" or step["field"] in editable)
		and valid_conditions(step.get("when", {}).get("fields", []), fields)
	]
	return data


def expand_legacy_steps(meta, steps):
	if not isinstance(steps, list):
		return steps
	legacy = [
		step for step in steps
		if isinstance(step, dict) and step.get("type") == "rule" and step.get("target") == "procurement_next"
	]
	if not legacy or not (builtin := builtin_guide(meta)):
		return steps
	ids = {step["step_key"] for step in load_steps(steps)}
	expanded = []
	for step in steps:
		if step not in legacy:
			expanded.append(step)
			continue
		for index, replacement in enumerate(builtin["steps"], 1):
			when = dict(replacement.get("when", {}))
			parent = step.get("when", {})
			if any(key in when and key in parent and when[key] != parent[key] for key in ("docstatus", "workflow_state", "role")):
				continue
			conditions = [*when.get("fields", []), *parent.get("fields", [])]
			when.update(parent)
			if conditions:
				when["fields"] = conditions
			key = replacement["id"]
			if key in ids:
				suffix = 1
				while f"{step['id'][:40]}_{index}_{suffix}" in ids:
					suffix += 1
				key = f"{step['id'][:40]}_{index}_{suffix}"
			ids.add(key)
			expanded.append({
				**replacement,
				"id": key,
				"when": when,
				"hint": step.get("hint") or replacement["hint"],
				"emotion": step.get("emotion") or replacement.get("emotion", ""),
			})
	return expanded


@frappe.whitelist(methods=["GET"])
def get_active_guides(target_doctype: str):
	names = frappe.get_all(
		GUIDE, filters={"target_doctype": target_doctype, "enabled": 1}, pluck="name", order_by="guide_title, name"
	)
	if not names or not frappe.has_permission(target_doctype, "read"):
		return
	docs = [frappe.get_cached_doc(GUIDE, name) for name in names]
	workflow = get_workflow(target_doctype) if get_workflow_name(target_doctype) else None
	return {
		"guides": [{"name": doc.name, "title": doc.guide_title, "steps": serialize_steps(doc)} for doc in docs],
		"mascot": mascot_settings(),
		"workflow_state_field": workflow.workflow_state_field if workflow else None,
	}


@frappe.whitelist(methods=["GET"])
def template(target_doctype: str):
	frappe.only_for("System Manager")
	meta = target_meta(target_doctype)
	fields = [
		{
			"field": path,
			"label": _(df.label or df.fieldname),
			"type": df.fieldtype,
			"required": bool(df.reqd),
			"read_only": bool(df.read_only),
		}
		for path, df in form_fields(meta)
	]
	examples = [
		{
			"id": f"fill_{index}",
			"type": "field",
			"field": df["field"],
			"when": {"docstatus": 0, "value": "empty"},
			"hint": _("Provide a value for {0}.").format(df["label"]),
			"emotion": "",
		}
		for index, df in enumerate([df for df in fields if not df["read_only"]][:2], 1)
	]
	examples.extend([
		{"id": "save", "type": "action", "target": "save", "when": {"docstatus": 0}, "hint": _("Save the document to continue.")},
		{"id": "status", "type": "wait", "hint": _("Check the document status.")},
	])
	mascot = mascot_settings()
	builtin = builtin_guide(meta)
	return {
		"schema_version": SCHEMA_VERSION,
		"target_doctype": meta.name,
		"title": _("{0} Guide").format(_(meta.name)),
		"steps": builtin["steps"] if builtin else examples,
		"_template": {
			"instructions": [
				_("Set title to the name the user sees when choosing a guide."),
				_("Adjust or replace the steps. The first matching step is shown. Each step is saved in the guide record."),
				_("Field steps highlight an empty editable field. Use table.fieldname for a field in a row."),
				_("Action steps highlight an available button. Wait steps highlight the status or a form field."),
				_("Use hint for the text shown to the user. The when object is optional."),
				_("Omit emotion or use an empty string to use the configured default emotion."),
				_("A registered rule checks one application-specific case. Its hint, position in the guide and emotion come from this JSON."),
				_("All entries in when.fields must match. Each entry uses a field, operator, and value when required."),
				_("Use required_empty for a mandatory empty field and required_positive or required_nonnegative for mandatory numbers."),
			],
			"step_types": STEP_TYPES,
			"when": {
				"docstatus": [0, 1, 2],
				"workflow_state": "string",
				"role": "Role",
				"value": VALUE_CHECKS,
				"fields": [{"field": "fieldname", "operator": FIELD_OPERATORS, "value": "scalar or array"}],
			},
			"fields": fields,
			"condition_fields": sorted(condition_fields(meta)),
			"actions": [*FORM_ACTIONS, *workflow_actions(meta.name)],
			"rules": allowed_rules(meta.name),
			"emotions": list(mascot["emotions"]),
			"default_emotion": mascot["default_emotion"],
		},
	}


@frappe.whitelist(methods=["GET"])
def export_guide(name: str):
	doc = frappe.get_doc(GUIDE, name)
	doc.check_permission("read")
	return serialize_guide(doc)


def load_steps(steps):
	if not isinstance(steps, list) or not 1 <= len(steps) <= 200:
		frappe.throw(_("A guide must have between 1 and 200 steps."))
	for index, step in enumerate(steps, 1):
		if not isinstance(step, dict) or set(step) - {"id", "type", "field", "target", "hint", "emotion", "when"}:
			frappe.throw(_("Step {0}: invalid step keys or format.").format(index))
		kind = step.get("type")
		when = step.get("when", {})
		if kind not in STEP_TYPES or not isinstance(when, dict) or set(when) - {"docstatus", "workflow_state", "role", "value", "fields"}:
			frappe.throw(_("Step {0}: invalid type or condition.").format(index))
		docstatus = when.get("docstatus")
		if "docstatus" in when and (type(docstatus) is not int or docstatus not in (0, 1, 2)):
			frappe.throw(_("Step {0}: use document status 0, 1, or 2.").format(index))
		if "value" in when and (kind != "field" or when["value"] not in VALUE_CHECKS):
			frappe.throw(_("Step {0}: choose a supported field value check.").format(index))
		if "fields" in when and not isinstance(when["fields"], list):
			frappe.throw(_("Step {0}: field conditions must be an array.").format(index))
		if ("field" in step and kind != "field") or ("target" in step and kind == "field"):
			frappe.throw(_("Step {0}: use field for a field step and target for other steps.").format(index))
		target = step.get("field" if kind == "field" else "target", "")
		hint = step.get("hint", "")
		emotion = step.get("emotion")
		key = step.get("id")
		workflow_state = when.get("workflow_state", "")
		role = when.get("role", "")
		if not all(isinstance(value, str) for value in (target, hint, key, workflow_state, role)) or (
			emotion is not None and not isinstance(emotion, str)
		):
			frappe.throw(_("Step {0}: identifiers, hints, emotions and conditions must be text.").format(index))
		if role and not frappe.db.exists("Role", role):
			frappe.throw(_("Step {0}: the required role does not exist.").format(index))
		yield {
			"step_key": key,
			"step_type": kind.title(),
			"target": target,
			"hint": hint,
			"emotion": (emotion or "").strip() or None,
			"document_status": str(docstatus) if docstatus is not None else "",
			"workflow_state": workflow_state,
			"required_role": role or None,
			"value_check": when.get("value"),
			"field_conditions": json.dumps(when["fields"], ensure_ascii=False) if "fields" in when else None,
		}


@frappe.whitelist(methods=["POST"])
def import_guide(source: str):
	frappe.only_for("System Manager")
	if not isinstance(source, str) or len(source) > 512_000:
		frappe.throw(_("Choose a JSON file smaller than 512 KB."))
	try:
		data = json.loads(source.lstrip("\ufeff"))
	except (ValueError, RecursionError):
		frappe.throw(_("The file does not contain valid JSON."))
	if (
		not isinstance(data, dict)
		or type(data.get("schema_version")) is not int
		or data["schema_version"] != SCHEMA_VERSION
		or set(data) - {"schema_version", "target_doctype", "title", "steps", "_template"}
		or not isinstance(data.get("title"), str)
	):
		frappe.throw(_("Use the Helper Guide JSON template with schema version 1."))

	meta = target_meta(data.get("target_doctype"))
	doc = frappe.get_doc(
		doctype=GUIDE,
		guide_title=data["title"],
		target_doctype=meta.name,
		enabled=0,
		steps=list(load_steps(expand_legacy_steps(meta, data.get("steps")))),
	)
	doc.insert()
	return doc.name


def seed():
	for key, image in BUILTIN_EMOTIONS.items():
		if not frappe.db.exists(EMOTION, key):
			frappe.get_doc(doctype=EMOTION, emotion_key=key, image=image).insert(ignore_permissions=True)
	for doctype in PROCUREMENT_GUIDES:
		if frappe.db.exists("DocType", doctype) and not frappe.db.exists(GUIDE, {"target_doctype": doctype}):
			data = builtin_guide(frappe.get_meta(doctype))
			frappe.get_doc(
				doctype=GUIDE,
				guide_title=data["title"],
				target_doctype=doctype,
				enabled=1,
				steps=list(load_steps(data["steps"])),
			).insert(ignore_permissions=True)


def expand_procurement_guides():
	parents = frappe.get_all(
		"Helper Guide Step",
		filters={"parenttype": GUIDE, "step_type": "Rule", "target": "procurement_next"},
		distinct=True,
		pluck="parent",
	)
	for name in parents:
		doc = frappe.get_doc(GUIDE, name)
		meta = target_meta(doc.target_doctype)
		doc.set("steps", list(load_steps(expand_legacy_steps(meta, serialize_steps(doc)))))
		doc.save(ignore_permissions=True)
