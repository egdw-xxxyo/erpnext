"""Optical spool QC: turn an uploaded SOR measurement into a Quality Inspection + a label.

Fired from a Reflectometer Device Script on the `SOR Uploaded` trigger, which passes the
OTDR document and the parsed measurement payload straight through:

    from erpnext.devices.spool_qc import handle_sor_uploaded

    def on_event(ctx):
        handle_sor_uploaded(ctx.otdr, ctx.payload, log=ctx.log)

The logic lives here rather than in the DB-stored script so it is versioned, linted and
identical on every site; the script stays a three-line call.

### Which spool was measured

Nothing in the upload path carries a serial number: the client is told only `qc_items`
(item codes) and sends back `selected_item`, an opaque item code. The spool identity
therefore travels in the SOR file itself — the operator types the spool serial into the
OTDR's **Fiber ID** field, and `_parse_sor_file` already extracts it as
`sor.General.fiber_id`. `cable_id` is accepted as a fallback.

### Grading

Pass/fail is **not** reimplemented here. Readings are filled from the measurement and the
stock `Quality Inspection.inspect_and_set_status()` applies the template's min/max,
acceptance values and formulas. `Serial No.inspection_status` is then set by the existing
`Quality Inspection.on_submit` hook (see `erpnext/stock/doctype/serial_no/inspection.py`).

Two stock behaviours shape the code below:

* `min_max_criteria_passed` returns `has_reading`, so a numeric reading left **empty is
  rejected**, not ignored. Any reading this module cannot fill is therefore marked
  `manual_inspection` so it neither auto-passes nor auto-fails.
* `validate` overwrites every reading from the item's template when `inspection_type` is
  `In Process` **and** `reference_type` is `Job Card`, which would discard the per-spool
  length limits computed here. So the Job Card is linked the other way round — by setting
  `Job Card.quality_inspection` — and `reference_type` is left unset.
"""

import json
import re

import frappe
from frappe.utils import cint, flt

from erpnext.devices.label_resolution import PURPOSE_FAILED, PURPOSE_PASSED, resolve_label_template

# Specification name -> where to read it from in the measurement payload.
# `limits: "length"` marks the reading whose min/max are derived per spool from the
# variant's winding-length attribute instead of being taken from the template.
DEFAULT_READINGS = {
	"Загасання волокна (дБ)": {"path": "loss_db"},
	"Довжина волокна (км)": {"path": "distance_km", "limits": "length"},
	"Зворотні втрати ORL (дБ)": {"path": "sor.Summary.optical_return_loss_db"},
	"Довжина хвилі (нм)": {"path": "wavelength_nm"},
}

DEFAULT_CONFIG = {
	"readings": DEFAULT_READINGS,
	"serial_fields": ["sor.General.fiber_id", "sor.General.cable_id"],
	"length_attribute": "Довжина намотки",
	"length_tolerance_pct": 1.0,
	"print_label": True,
}


def _noop(message, level="INFO", **extra):
	pass


def _get_config(otdr):
	"""Defaults overlaid with `OTDR Configuration.extra_config.spool_qc`, so the reading
	map and tolerances can be retuned per site without a deploy."""
	cfg = dict(DEFAULT_CONFIG)
	config_name = getattr(otdr, "otdr_configuration", None)
	if not config_name:
		return cfg, None

	extra = frappe.db.get_value("OTDR Configuration", config_name, "extra_config")
	if not extra:
		return cfg, config_name

	try:
		parsed = json.loads(extra)
	except Exception:
		return cfg, config_name

	overrides = (parsed or {}).get("spool_qc") or {}
	if isinstance(overrides, dict):
		cfg.update(overrides)

	return cfg, config_name


def _dig(payload, path):
	"""Value at a dotted path, or None if any hop is missing."""
	node = payload
	for key in path.split("."):
		if not isinstance(node, dict):
			return None
		node = node.get(key)
		if node is None:
			return None
	return node


def resolve_serial_no(payload, cfg):
	"""The Serial No named by the SOR's Fiber ID, or None.

	Returns (serial_no, raw_value) so the caller can report a value that looked like an
	identifier but matched no Serial No — the common operator typo.
	"""
	for path in cfg.get("serial_fields") or []:
		raw = _dig(payload, path)
		if raw is None:
			continue
		candidate = str(raw).strip()
		if not candidate:
			continue
		if frappe.db.exists("Serial No", candidate):
			return candidate, candidate
		return None, candidate
	return None, None


def _format_reading(value):
	"""Reading as a string in the site's number format.

	`Quality Inspection Reading.reading_#` is a Data field parsed with the user's number
	format, and `validate_reading_number_format` refuses anything else — so a locale using
	a comma decimal separator needs the comma here.
	"""
	from erpnext.stock.doctype.quality_inspection.quality_inspection import (
		get_reading_number_format,
		get_reading_separators,
	)

	decimal_str, _comma_str = get_reading_separators(get_reading_number_format())
	text = f"{flt(value):g}"
	return text.replace(".", decimal_str) if decimal_str != "." else text


def _nominal_length_km(item_code, attribute_name):
	"""Winding length declared by the variant's attribute.

	Attribute values carry their unit — "25 км", not "25" — so only the leading number is
	read.
	"""
	value = frappe.db.get_value(
		"Item Variant Attribute",
		{"parent": item_code, "attribute": attribute_name},
		"attribute_value",
	)
	if not value:
		return None

	match = re.match(r"\s*([-+]?\d+(?:[.,]\d+)?)", str(value))
	if not match:
		return None
	return float(match.group(1).replace(",", "."))


def _apply_length_limits(reading, item_code, cfg, log):
	"""Set this reading's min/max from the spool's nominal length ± tolerance.

	One template serves every length variant this way; without it each of the ten
	variants would need its own Quality Inspection Template.
	"""
	nominal = _nominal_length_km(item_code, cfg.get("length_attribute"))
	if nominal is None:
		log(
			"Nominal winding length not found, keeping template limits",
			level="WARN",
			item_code=item_code,
			attribute=cfg.get("length_attribute"),
		)
		return

	tolerance = flt(cfg.get("length_tolerance_pct")) / 100.0
	reading.min_value = nominal * (1 - tolerance)
	reading.max_value = nominal * (1 + tolerance)
	log(
		"Length limits set from nominal",
		nominal_km=nominal,
		min_km=reading.min_value,
		max_km=reading.max_value,
	)


def _resolve_qi_template(otdr, item_code):
	"""OTDR QC Item override for this item, else the item's own template."""
	for row in getattr(otdr, "qc_items", None) or []:
		if row.item_code == item_code and row.quality_inspection_template:
			return row.quality_inspection_template

	return frappe.db.get_value("Item", item_code, "quality_inspection_template")


def _source_batch(serial_no):
	"""Fiber reel this spool was wound from, if lineage has been stamped."""
	return frappe.db.get_value("Serial No", serial_no, "source_batch_no")


def _link_job_card(qi_name, serial_no, log):
	"""Point the spool's Job Card at this inspection so completion is gated by it.

	Done from this side on purpose: setting `Quality Inspection.reference_type` to
	`Job Card` makes stock `validate` reload every reading from the item template and
	discard the per-spool length limits.
	"""
	job_cards = frappe.get_all(
		"Job Card",
		filters=[["serial_no", "like", f"%{serial_no}%"], ["docstatus", "<", 2]],
		fields=["name", "quality_inspection"],
		order_by="creation desc",
		limit=1,
	)
	if not job_cards:
		return None

	job_card = job_cards[0]
	if job_card.quality_inspection:
		return job_card.name

	frappe.db.set_value("Job Card", job_card.name, "quality_inspection", qi_name)
	log("Job Card linked to inspection", job_card=job_card.name)
	return job_card.name


def make_quality_inspection(serial_no, item_code, payload, otdr, cfg, log):
	"""Create and submit the Quality Inspection for one measured spool."""
	template = _resolve_qi_template(otdr, item_code)
	if not template:
		log(
			"No Quality Inspection Template for item, skipping inspection",
			level="WARN",
			item_code=item_code,
		)
		return None

	qi = frappe.new_doc("Quality Inspection")
	qi.inspection_type = "In Process"
	qi.report_date = frappe.utils.nowdate()
	qi.item_code = item_code
	qi.item_serial_no = serial_no
	qi.quality_inspection_template = template
	# `inspected_by` defaults to the literal string "user", which is not a User and fails
	# link validation outside a desk session. The measurement arrives over the API, so the
	# inspector is whoever the device authenticated as.
	qi.inspected_by = frappe.session.user

	batch_no = _source_batch(serial_no)
	if batch_no:
		qi.batch_no = batch_no

	qi.get_item_specification_details()
	if not qi.readings:
		log("Template has no readings, skipping inspection", level="WARN", template=template)
		return None

	readings_cfg = cfg.get("readings") or {}
	filled = {}
	for reading in qi.readings:
		spec = readings_cfg.get(reading.specification)
		value = _dig(payload, spec["path"]) if spec else None

		if value is None:
			# An empty numeric reading is treated as a failure by
			# `min_max_criteria_passed`, so anything unmeasured must opt out of grading.
			if cint(reading.numeric):
				reading.manual_inspection = 1
			continue

		reading.reading_1 = _format_reading(value)
		reading.manual_inspection = 0
		if spec.get("limits") == "length":
			_apply_length_limits(reading, item_code, cfg, log)
		filled[reading.specification] = reading.reading_1

	if not filled:
		log(
			"Measurement matched no template reading, skipping inspection",
			level="WARN",
			template=template,
			known_specifications=list(readings_cfg),
		)
		return None

	qi.flags.ignore_permissions = True
	qi.insert()
	qi.submit()
	log("Quality Inspection submitted", quality_inspection=qi.name, status=qi.status, readings=filled)

	_link_job_card(qi.name, serial_no, log)
	return qi


def print_qc_label(serial_no, item_code, qi, payload, otdr_configuration, cfg, log):
	"""Queue the Passed or Failed label for the inspected spool."""
	if not cfg.get("print_label"):
		log("Label printing disabled by configuration")
		return None

	purpose = PURPOSE_PASSED if qi.status == "Accepted" else PURPOSE_FAILED
	resolved = resolve_label_template(item_code, purpose, otdr_configuration=otdr_configuration)
	if not resolved:
		log(
			"No label template configured for purpose, nothing printed",
			level="WARN",
			item_code=item_code,
			purpose=purpose,
		)
		return None

	printer = resolved.get("label_printer") or _any_printer_for(item_code)
	if not printer:
		log(
			"Label template has no printer, nothing printed",
			level="WARN",
			label_template=resolved["label_template"],
			purpose=purpose,
		)
		return None

	raw_data = {
		"serial_no": serial_no,
		"coil_code": serial_no,
		"item_code": item_code,
		"item_name": frappe.db.get_value("Item", item_code, "item_name"),
		"quality_inspection": qi.name,
		"qi_status": qi.status,
		"purpose": purpose,
		"fiber_length": _dig(payload, "distance_km"),
		"loss_db": _dig(payload, "loss_db"),
		"wavelength": _dig(payload, "wavelength_nm"),
		"source_batch_no": _source_batch(serial_no),
		"label_date": frappe.utils.nowdate(),
	}

	from erpnext.devices.doctype.label_printer.label_printer import create_print_job

	result = create_print_job(
		label_template=resolved["label_template"],
		printer_name=printer,
		reference_name=serial_no,
		raw_data=raw_data,
	)
	log(
		"Label queued",
		print_job=result.get("print_job"),
		label_template=resolved["label_template"],
		printer=printer,
		purpose=purpose,
		template_source=resolved.get("source"),
	)
	return result.get("print_job")


def _any_printer_for(item_code):
	"""Printer from any of the item's label rows, when the matching row names none."""
	return frappe.db.get_value(
		"Item Label Template",
		{"parent": item_code, "parenttype": "Item", "label_printer": ["is", "set"]},
		"label_printer",
	)


def handle_sor_uploaded(otdr, payload, log=None):
	"""Entry point for the Reflectometer `SOR Uploaded` Device Script.

	Returns a summary dict. Warnings are logged rather than raised: the caller collects
	WARN/ERROR lines into `script_results`, which `parse_and_submit_measurement` returns
	to the operator's sync app, so a misidentified spool shows up at the workbench.
	"""
	log = log or _noop
	if not isinstance(payload, dict):
		log("Measurement payload is not a dict, nothing to do", level="WARN")
		return {"status": "skipped", "reason": "bad_payload"}

	cfg, otdr_configuration = _get_config(otdr)

	serial_no, raw_identifier = resolve_serial_no(payload, cfg)
	if not serial_no:
		if raw_identifier:
			log(
				"SOR Fiber ID does not match any Serial No",
				level="WARN",
				fiber_id=raw_identifier,
			)
			return {"status": "skipped", "reason": "unknown_serial", "fiber_id": raw_identifier}
		log(
			"SOR carries no Fiber ID — type the spool serial into the OTDR before measuring",
			level="WARN",
		)
		return {"status": "skipped", "reason": "no_serial"}

	item_code = frappe.db.get_value("Serial No", serial_no, "item_code")
	log("Spool identified", serial_no=serial_no, item_code=item_code)

	qi = make_quality_inspection(serial_no, item_code, payload, otdr, cfg, log)
	if not qi:
		return {"status": "skipped", "reason": "no_inspection", "serial_no": serial_no}

	print_job = print_qc_label(serial_no, item_code, qi, payload, otdr_configuration, cfg, log)

	return {
		"status": "ok",
		"serial_no": serial_no,
		"item_code": item_code,
		"quality_inspection": qi.name,
		"qi_status": qi.status,
		"print_job": print_job,
	}
