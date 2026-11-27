"""Firmware flashing as a step of the production route.

A BOM operation names the `Firmware` the unit receives there. The Job Card of that operation
carries the frozen `Firmware Version`, and the bench works the cards like any other operation:
take the next open card, flash its serial and firmware onto the board, close the card. The serial
is the one the Job Card already holds, so what is written to the board, what is on the label and
what is in stock are the same number. On close the version is stored on the unit as the
«Прошивка» attribute of its `Serial No`.

The board is reached by the browser (see the `firmware-flashing` page); this module only builds
the image, keeps the audit trail (`Flash Attempt`) and closes the card.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from erpnext.manufacturing import uf2
from erpnext.manufacturing.doctype.firmware.firmware import latest_released
from erpnext.manufacturing.doctype.firmware_version.firmware_version import ATTRIBUTE, read_image_file
from erpnext.stock.additional_attributes import ROW_DOCTYPE, apply_attributes_to_serials

FREE_STATUS = "Open"
CLAIMED_STATUS = "Work In Progress"
LIVE_WORK_ORDER_STATUSES = ("Not Started", "In Process")
ROLES = ("Manufacturing User", "Manufacturing Manager", "System Manager")


# --- Job Card stamping ---------------------------------------------------------------------


def bom_firmware(bom_no, operation, sequence_id=None):
	"""The firmware a BOM operation flashes, if it is a flashing step."""
	if not bom_no or not operation:
		return None
	filters = {"parent": bom_no, "parenttype": "BOM", "operation": operation}
	if sequence_id:
		exact = frappe.db.get_value("BOM Operation", {**filters, "sequence_id": sequence_id}, "firmware")
		if exact:
			return exact
	return frappe.db.get_value("BOM Operation", filters, "firmware") or None


def stamp_job_card(doc, method=None):
	"""`Job Card.before_insert`: freeze the firmware version this card will flash.

	Later releases do not change a card that already exists; withdrawing the frozen version
	does (see `_usable_version`).
	"""
	if doc.get("firmware"):
		firmware = doc.firmware
	else:
		firmware = bom_firmware(doc.bom_no, doc.operation, doc.get("sequence_id"))
		if not firmware:
			return
		doc.firmware = firmware

	if not doc.get("firmware_version"):
		doc.firmware_version = latest_released(firmware)


def validate_bom_firmware(doc, method=None):
	"""`BOM.validate`: a firmware on an operation has to be usable."""
	for row in doc.get("operations") or []:
		firmware = row.get("firmware")
		if not firmware:
			continue
		if frappe.db.get_value("Firmware", firmware, "disabled"):
			frappe.throw(_("Row {0}: firmware {1} is disabled").format(row.idx, frappe.bold(firmware)))


# --- helpers -------------------------------------------------------------------------------


def _check_roles():
	frappe.only_for(ROLES)


def _employee():
	from erpnext.devices.otdr_measurement_api import _session_employee

	return _session_employee()


def _assert_workplace(workplace):
	if not workplace:
		return
	from erpnext.devices.otdr_measurement_api import _assert_workplace_allowed

	_assert_workplace_allowed(workplace, _employee())


def _first_serial(value):
	return (value or "").splitlines()[0].strip() if value else None


def _usable_version(card):
	"""The card's version, replaced by the newest release when the frozen one was withdrawn."""
	version = card.firmware_version
	if version and frappe.db.get_value("Firmware Version", version, "status") == "Released":
		return version

	version = latest_released(card.firmware)
	if not version:
		frappe.throw(
			_("Firmware {0} has no released version. Release one before flashing {1}").format(
				frappe.bold(card.firmware), card.name
			)
		)
	frappe.db.set_value("Job Card", card.name, "firmware_version", version, update_modified=False)
	return version


def _workstations(workplace):
	if not workplace:
		return []
	return [
		row.workstation
		for row in frappe.get_all(
			"Workplace Operation",
			filters={"parent": workplace, "parenttype": "Workplace"},
			fields=["workstation"],
		)
		if row.workstation
	]


def _free_cards(workplace=None, item_code=None, limit=50):
	filters = {
		"docstatus": 0,
		"status": FREE_STATUS,
		"firmware": ["is", "set"],
		"serial_no": ["is", "set"],
	}
	if item_code:
		filters["production_item"] = item_code
	workstations = _workstations(workplace)
	if workstations:
		filters["workstation"] = ["in", workstations]

	cards = frappe.get_all(
		"Job Card",
		filters=filters,
		fields=["name", "serial_no", "production_item", "firmware", "firmware_version", "work_order"],
		order_by="creation asc",
		limit=limit,
	)
	return [
		card
		for card in cards
		if frappe.db.get_value("Work Order", card.work_order, "status") in LIVE_WORK_ORDER_STATUSES
	]


def _payload(attempt):
	"""What the page needs to show the operator and to flash the board."""
	profile = frappe.get_doc("Flashing Profile", attempt.flashing_profile)
	version = frappe.db.get_value(
		"Firmware Version",
		attempt.firmware_version,
		["version", "sha256", "image_size", "release_notes"],
		as_dict=True,
	)
	card = frappe.db.get_value(
		"Job Card", attempt.job_card, ["production_item", "item_name", "work_order"], as_dict=True
	)
	return {
		"attempt": attempt.name,
		"job_card": attempt.job_card,
		"work_order": card.work_order,
		"serial_no": attempt.serial_no,
		"item_code": card.production_item,
		"item_name": card.item_name,
		"firmware": attempt.firmware,
		"firmware_version": attempt.firmware_version,
		"version": version.version,
		"sha256": version.sha256,
		"image_size": version.image_size,
		"release_notes": version.release_notes,
		"file_name": f"{attempt.serial_no}.uf2",
		"instructions": profile.instructions,
		"verify_mode": profile.verify_mode,
		"verify_baud": profile.verify_baud,
		"verify_timeout": profile.verify_timeout,
		"verify_pattern": (profile.verify_pattern or "").replace("{serial}", attempt.serial_no),
	}


def _own_attempt(name, statuses=("In Progress",)):
	attempt = frappe.get_doc("Flash Attempt", name)
	if attempt.status not in statuses:
		frappe.throw(_("Flash attempt {0} is {1}").format(name, _(attempt.status)))
	if attempt.owner != frappe.session.user and "Manufacturing Manager" not in frappe.get_roles():
		frappe.throw(_("Flash attempt {0} belongs to another operator").format(name), frappe.PermissionError)
	return attempt


# --- endpoints -----------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_overview(workplace=None):
	"""Boards waiting per firmware, the operator's open attempt and the latest attempts."""
	_check_roles()
	_assert_workplace(workplace)

	waiting = {}
	for card in _free_cards(workplace, limit=500):
		row = waiting.setdefault(
			(card.production_item, card.firmware),
			{
				"item_code": card.production_item,
				"firmware": card.firmware,
				"version": latest_released(card.firmware),
				"count": 0,
			},
		)
		row["count"] += 1

	open_attempt = frappe.db.get_value(
		"Flash Attempt", {"status": "In Progress", "owner": frappe.session.user}, "name"
	)
	recent = frappe.get_all(
		"Flash Attempt",
		fields=[
			"name",
			"serial_no",
			"job_card",
			"status",
			"firmware_version",
			"verified_by",
			"finished_on",
			"owner",
		],
		order_by="modified desc",
		limit=15,
	)
	return {
		"waiting": list(waiting.values()),
		"open_attempt": _payload(frappe.get_doc("Flash Attempt", open_attempt)) if open_attempt else None,
		"recent": recent,
	}


@frappe.whitelist(methods=["POST"])
def next_board(workplace=None, item_code=None):
	"""Hand the operator the next board to flash, claiming its Job Card.

	An attempt this operator left open comes back first, so a reloaded page picks up where it
	stopped instead of burning a second serial.
	"""
	_check_roles()
	_assert_workplace(workplace)

	open_attempt = frappe.db.get_value(
		"Flash Attempt", {"status": "In Progress", "owner": frappe.session.user}, "name"
	)
	if open_attempt:
		return {**_payload(frappe.get_doc("Flash Attempt", open_attempt)), "resumed": True}

	for candidate in _free_cards(workplace, item_code, limit=20):
		card = frappe.get_doc("Job Card", candidate.name)
		# Another bench may have taken it between the list and now.
		if (
			frappe.db.get_value("Job Card", card.name, "status", for_update=True) != FREE_STATUS
			or card.docstatus != 0
		):
			continue

		serial = _first_serial(card.serial_no)
		firmware = frappe.get_doc("Firmware", card.firmware)
		if firmware.disabled:
			continue

		version = _usable_version(card)
		profile = frappe.get_doc("Flashing Profile", firmware.flashing_profile)
		if profile.disabled:
			frappe.throw(_("Flashing profile {0} is disabled").format(profile.name))
		uf2.normalize_serial(serial, profile.serial_max_length, profile.serial_magic.encode("ascii"))

		attempt = frappe.get_doc(
			{
				"doctype": "Flash Attempt",
				"job_card": card.name,
				"serial_no": serial,
				"status": "In Progress",
				"workplace": workplace,
				"employee": _employee(),
				"firmware": firmware.name,
				"firmware_version": version,
				"flashing_profile": profile.name,
				"image_sha256": frappe.db.get_value("Firmware Version", version, "sha256"),
				"started_on": now_datetime(),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Job Card", card.name, {"status": CLAIMED_STATUS, "actual_start_date": now_datetime()}
		)
		frappe.db.commit()
		return {
			**_payload(attempt),
			"resumed": False,
			"remaining": len(_free_cards(workplace, item_code, 500)),
		}

	frappe.throw(_("No board is waiting for flashing at this workplace"))


@frappe.whitelist(methods=["GET"])
def get_image(attempt):
	"""The UF2 for this board: the frozen firmware version plus the serial record."""
	_check_roles()
	attempt = _own_attempt(attempt)
	profile = frappe.get_doc("Flashing Profile", attempt.flashing_profile)
	file_url = frappe.db.get_value("Firmware Version", attempt.firmware_version, "file")
	data = read_image_file(file_url)

	if uf2.sha256(data) != attempt.image_sha256:
		frappe.throw(_("Firmware file of {0} changed after release").format(attempt.firmware_version))

	layout = profile.layout()
	image = uf2.build_image(
		data,
		attempt.serial_no,
		layout["family_id"],
		layout["record_address"],
		layout["magic"],
		layout["max_length"],
	)
	frappe.response["type"] = "download"
	frappe.response["filename"] = f"{attempt.serial_no}.uf2"
	frappe.response["filecontent"] = image


@frappe.whitelist(methods=["POST"])
def confirm(attempt, console_line=None, verified_by="Operator"):
	"""The board is flashed: record how it was checked and close the Job Card."""
	_check_roles()
	attempt = _own_attempt(attempt)
	profile = frappe.get_doc("Flashing Profile", attempt.flashing_profile)

	if verified_by == "Console":
		expected = (profile.verify_pattern or "").replace("{serial}", attempt.serial_no)
		if not console_line or expected not in console_line:
			frappe.throw(
				_("The board did not report {0}. It said: {1}").format(
					frappe.bold(expected), frappe.bold(console_line or "-")
				)
			)
	elif verified_by != "Operator":
		frappe.throw(_("Unknown verification {0}").format(verified_by))

	card = frappe.get_doc("Job Card", attempt.job_card)
	if card.docstatus == 0:
		from erpnext.manufacturing.doctype.production_line.production_line import _complete_job_card

		_complete_job_card(card)

	record_version(attempt.serial_no, attempt.firmware_version)

	attempt.db_set(
		{
			"status": "Done",
			"finished_on": now_datetime(),
			"verified_by": verified_by,
			"console_line": (console_line or "")[:500],
		}
	)
	frappe.db.commit()
	return {
		"serial_no": attempt.serial_no,
		"job_card": card.name,
		"firmware_version": attempt.firmware_version,
	}


@frappe.whitelist(methods=["POST"])
def fail(attempt, reason=None):
	"""The board did not take the firmware: log it and put the card back for another try."""
	_check_roles()
	return _give_back(attempt, "Failed", reason)


@frappe.whitelist(methods=["POST"])
def release(attempt):
	"""The operator walked away from the board: return its card to the pool."""
	_check_roles()
	return _give_back(attempt, "Released")


def _give_back(attempt, status, reason=None):
	attempt = _own_attempt(attempt)
	frappe.db.set_value("Job Card", attempt.job_card, {"status": FREE_STATUS, "actual_start_date": None})
	attempt.db_set({"status": status, "finished_on": now_datetime(), "failure_reason": (reason or "")[:500]})
	frappe.db.commit()
	return {"attempt": attempt.name, "status": status}


# --- the unit remembers its firmware -------------------------------------------------------


def record_version(serial_no, firmware_version):
	"""Write the «Прошивка» attribute of the serial, replacing an older value on a reflash."""
	value = frappe.db.get_value("Firmware Version", firmware_version, "attribute_value")
	if not value:
		frappe.throw(_("Firmware version {0} has no serial attribute value").format(firmware_version))

	existing = frappe.db.get_value(
		ROW_DOCTYPE,
		{"parenttype": "Serial No", "parent": serial_no, "attribute": ATTRIBUTE},
		"name",
	)
	if existing:
		frappe.db.set_value(ROW_DOCTYPE, existing, "value", value)
		return

	apply_attributes_to_serials([serial_no], [frappe._dict(attribute=ATTRIBUTE, value=value, notes=None)])
