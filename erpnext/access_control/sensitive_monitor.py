import hashlib
import time

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from erpnext.access_control import sensitive
from erpnext.access_control import sensitive_rules as rules
from erpnext.access_control.permissions_engine import _require_manager

ROW_LIMIT = 200


def _session_id(sid: str) -> str:
	return hashlib.sha256(sid.encode()).hexdigest()[:16]


def _unlock_sessions() -> list[tuple[str, dict]]:
	prefix = f"{sensitive.UNLOCK_KEY}|"
	sids = {
		(key.decode() if isinstance(key, bytes) else key).rsplit("|", 1)[-1]
		for key in frappe.cache.get_keys(prefix)
	}
	states = ((sid, frappe.cache.get_value(f"{prefix}{sid}")) for sid in sids)
	return [(sid, state) for sid, state in states if state]


def expire_unlocks():
	settings = sensitive.config()
	minutes = rules.longest_minutes(settings)
	now = time.time()
	for sid, state in _unlock_sessions():
		if rules.unlocked_until(state, now, minutes, settings["idle_minutes"]):
			continue
		ended, reason = rules.unlock_end(state, minutes, settings["idle_minutes"])
		frappe.cache.delete_value(f"{sensitive.UNLOCK_KEY}|{sid}")
		sensitive.log(
			"Expired",
			state.get("user"),
			state.get("actor"),
			expires_on=add_to_date(now_datetime(), seconds=int(ended - now)),
			details=reason,
		)


def _active_unlocks(settings: dict) -> list[dict]:
	now = time.time()
	rows = [
		{
			"id": _session_id(sid),
			"user": state.get("user"),
			"actor": state.get("actor"),
			"since": state["since"],
			"until": rules.unlocked_until(state, now, settings["unlock_minutes"], settings["idle_minutes"]),
		}
		for sid, state in _unlock_sessions()
	]
	return sorted((row for row in rows if row["until"]), key=lambda row: -row["since"])


def _views(doctypes: list[str]) -> list[dict]:
	if not doctypes:
		return []
	return frappe.get_all(
		"View Log",
		filters={"reference_doctype": ["in", doctypes]},
		fields=["viewed_by", "reference_doctype", "reference_name", "creation"],
		order_by="creation desc",
		limit=ROW_LIMIT,
	)


def _exports(doctypes: list[str], reports: list[str]) -> list[dict]:
	filters = {
		key: ["in", values] for key, values in (("export_from", doctypes), ("report_name", reports)) if values
	}
	if not filters:
		return []
	return frappe.get_all(
		"Access Log",
		or_filters=filters,
		fields=[
			"user",
			"export_from",
			"report_name",
			"reference_document",
			"file_type",
			"method",
			"creation",
		],
		order_by="creation desc",
		limit=ROW_LIMIT,
	)


def _people(users: set[str]) -> dict:
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", sorted(users)]},
		fields=["name", "full_name", "user_image"],
	)
	return {row.name: row for row in rows}


@frappe.whitelist()
def get_overview() -> dict:
	_require_manager()
	settings = sensitive.config()
	doctypes = sorted(name for name in settings["doctypes"] if name != rules.SETTINGS_DOCTYPE)
	reports = sorted(settings["reports"])
	active = _active_unlocks(settings)
	pins = frappe.get_all(
		sensitive.PIN_DOCTYPE,
		fields=["user", "is_set", "locked", "failed_attempts", "pin_set_on", "last_unlock"],
		order_by="locked desc, last_unlock desc",
	)
	events = frappe.get_all(
		sensitive.LOG_DOCTYPE,
		fields=[
			"name",
			"event",
			"user",
			"actor",
			"ip_address",
			"user_agent",
			"expires_on",
			"details",
			"creation",
		],
		order_by="creation desc",
		limit=ROW_LIMIT,
	)
	views = _views(doctypes)
	exports = _exports(doctypes, reports)
	users = (
		{row["user"] for row in active}
		| {row["actor"] for row in active}
		| {row.user for row in pins}
		| {row.user for row in events}
		| {row.actor for row in events}
		| {row.viewed_by for row in views}
		| {row.user for row in exports}
	) - {None}
	return {
		"enabled": settings["enabled"],
		"settings": {key: settings[key] for key in ("unlock_minutes", "idle_minutes", "max_attempts")},
		"protected": {"doctypes": doctypes, "reports": reports, "pages": sorted(settings["pages"])},
		"fields": settings["fields"],
		"active": active,
		"pins": pins,
		"events": events,
		"views": views,
		"exports": exports,
		"people": _people(users),
	}


@frappe.whitelist(methods=["POST"])
def force_lock(session: str) -> dict:
	_require_manager()
	match = next(((sid, state) for sid, state in _unlock_sessions() if _session_id(sid) == session), None)
	if not match:
		frappe.throw(_("This unlock has already ended"))
	sid, state = match
	frappe.cache.delete_value(f"{sensitive.UNLOCK_KEY}|{sid}")
	sensitive.log("Locked", state.get("user"), frappe.session.user, details=_("Locked by a manager"))
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def reset_pin(user: str) -> dict:
	_require_manager()
	sensitive.clear_pin(user)
	for sid, state in _unlock_sessions():
		if state.get("user") == user:
			frappe.cache.delete_value(f"{sensitive.UNLOCK_KEY}|{sid}")
	return {"ok": True}
