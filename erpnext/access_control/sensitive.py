import json
import time

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.rate_limiter import rate_limit
from frappe.utils import add_to_date, now_datetime
from frappe.utils.password import check_password, update_password

from erpnext.access_control import impersonation_rules
from erpnext.access_control import sensitive_rules as rules
from erpnext.access_control.permissions_engine import is_access_manager

SETTINGS = rules.SETTINGS_DOCTYPE
PIN_DOCTYPE = "Sensitive Data PIN"
LOG_DOCTYPE = "Sensitive Access Log"
AUTH_FIELD = "sensitive_pin"
CONFIG_KEY = "sensitive_data_config"
SUPERUSER = "Administrator"
UNLOCK_KEY = "sensitive_unlock"
UNTIL_HEADER = "X-Sensitive-Until"
EXPIRY_GRACE_MINUTES = 15
VIEW_SESSION_KEY = "access_view"
CHAT_PREFIX = "erpnext.crm.page.employee_chat.employee_chat."
CHAT_DOCTYPES = frozenset({"Chat Thread", "Chat Message"})


class SensitiveDataLocked(frappe.PermissionError):
	http_status_code = 403


def refusal_messages() -> dict[str, str]:
	return {
		"locked": _("This data is protected by a PIN. Enter your PIN in the browser to open it"),
		"no_browser": _("This data is protected by a PIN. Open it in the browser"),
		"format": _("The PIN must be exactly 6 digits"),
		"weak": _("The PIN is too simple. Do not use repeated or consecutive digits"),
		"mismatch": _("The PINs do not match"),
		"no_pin": _("You have not set a PIN yet"),
		"blocked": _("Your PIN is blocked after too many wrong attempts. Reset it to continue"),
		"wrong_pin": _("Wrong PIN"),
		"wrong_password": _("Wrong password"),
		"viewing": _("This is not available while viewing as another user"),
	}


def _refuse(code: str, exc=frappe.ValidationError):
	frappe.throw(refusal_messages()[code], exc)


def _module_paths(objects: list[dict]) -> dict:
	folders = {"DocType": "doctype", "Report": "report", "Page": "page"}
	paths = {}
	for row in objects:
		module = frappe.db.get_value(row["object_type"], row["object_name"], "module")
		app = module and frappe.db.get_value("Module Def", module, "app_name")
		if app:
			paths[(row["object_type"], row["object_name"])] = ".".join(
				(app, frappe.scrub(module), folders[row["object_type"]], frappe.scrub(row["object_name"]))
			)
	return paths


def _children(doctypes) -> dict:
	return {
		doctype: [df.options for df in frappe.get_meta(doctype).get_table_fields() if df.options]
		for doctype in doctypes
		if frappe.db.exists("DocType", doctype)
	}


def _hook_methods() -> dict:
	declared = frappe.get_hooks("sensitive_data_methods") or {}
	return {name: list(prefixes) for name, prefixes in declared.items()}


def _load_config() -> dict:
	settings = frappe.db.get_singles_dict(SETTINGS)
	child_filters = {"parent": SETTINGS, "parenttype": SETTINGS}
	objects = frappe.get_all(
		"Sensitive Data Object",
		filters=child_filters,
		fields=["object_type", "object_name", "unlock_minutes"],
		order_by="idx asc",
	)
	fields = frappe.get_all(
		"Sensitive Data Field", filters=child_filters, fields=["document_type", "fieldname"]
	)
	api_users = frappe.get_all("Sensitive Data API User", filters=child_filters, pluck="user")
	doctypes = [row["object_name"] for row in objects if row["object_type"] == "DocType"]
	methods = rules.method_prefixes(objects, _module_paths(objects), _hook_methods())
	return rules.build_config(
		settings,
		objects,
		fields,
		_children([*doctypes, SETTINGS]),
		{"methods": methods, "api_users": api_users},
	)


def _generate_config() -> dict:
	frappe.local.sensitive_loading = True
	try:
		return _load_config()
	finally:
		frappe.local.sensitive_loading = False


def config() -> dict:
	cached = getattr(frappe.local, "sensitive_config", None)
	if cached is None:
		cached = frappe.cache.get_value(CONFIG_KEY, generator=_generate_config)
		frappe.local.sensitive_config = cached
	return cached


def _drop_config():
	frappe.cache.delete_value(CONFIG_KEY)


def clear_config():
	_drop_config()
	frappe.db.after_commit.add(_drop_config)
	frappe.db.after_rollback.add(_drop_config)


def _request():
	return getattr(frappe.local, "request", None)


def _api_key_request() -> bool:
	request = _request()
	return bool(request and request.headers.get("Authorization"))


def in_scope(user: str | None = None) -> bool:
	session = getattr(frappe.local, "session", None)
	if not _request() or not session or session.user in (None, "Guest"):
		return False
	if user and user != session.user:
		return False
	if exempt():
		return False
	settings = config()
	if not settings["enabled"]:
		return False
	return not (_api_key_request() and session.user in settings["api_users"])


def exempt() -> bool:
	return frappe.session.user == SUPERUSER or bool(_view_session())


def _view_session() -> dict | None:
	session = getattr(frappe.local, "session", None)
	return (session.data or {}).get(VIEW_SESSION_KEY) if session else None


def _actor() -> str | None:
	view = _view_session()
	return view["by"] if view else None


def _unlock_key() -> str:
	return f"{UNLOCK_KEY}|{frappe.session.sid}"


def _state() -> dict | None:
	if _api_key_request():
		return None
	return frappe.cache.get_value(_unlock_key())


def _store_state(state: dict):
	expires = (rules.longest_minutes(config()) + EXPIRY_GRACE_MINUTES) * 60
	frappe.cache.set_value(_unlock_key(), state, expires_in_sec=expires)


def unlocked_until(target: tuple | None = None) -> float | None:
	settings = config()
	minutes = rules.object_minutes(settings, target)
	return rules.unlocked_until(_state(), time.time(), minutes, settings["idle_minutes"])


def _touch(target: tuple | None):
	state = _state()
	if not state:
		return
	_store_state({**state, "seen": time.time()})
	frappe.local.sensitive_until = unlocked_until(target)


def is_locked(target: tuple | None) -> bool:
	if not target or not in_scope():
		return False
	memo = getattr(frappe.local, "sensitive_checked", None)
	if memo is None:
		memo = frappe.local.sensitive_checked = {}
	if target not in memo:
		memo[target] = unlocked_until(target) is None
		if not memo[target]:
			_touch(target)
	return memo[target]


def locked_message() -> str:
	return refusal_messages()["no_browser" if _api_key_request() else "locked"]


def _raise_locked(target: tuple):
	request = _request()
	frappe.local.sensitive_locked = {
		"object_type": target[0],
		"object_name": target[1],
		"retry": rules.retry_mode(request.path if request else "", frappe.local.form_dict),
	}
	frappe.throw(locked_message(), SensitiveDataLocked)


def _doctype_target(doctype) -> tuple | None:
	protected = rules.protected_doctype(config(), doctype)
	return ("DocType", protected) if protected else None


def _thread_reference(thread) -> str | None:
	return thread and frappe.db.get_value("Chat Thread", thread, "reference_doctype")


def _chat_target(method: str | None, params) -> tuple | None:
	if not method or not method.startswith(CHAT_PREFIX):
		return None
	thread = params.get("thread") or (
		params.get("message") and frappe.db.get_value("Chat Message", params.get("message"), "thread")
	)
	reference = params.get("reference_doctype") or _thread_reference(thread)
	return _doctype_target(reference)


def guard_request():
	request = _request()
	if not request or not in_scope():
		return
	params = frappe.local.form_dict
	target = rules.request_target(config(), request.path, request.method, params) or _chat_target(
		impersonation_rules.requested_method(request.path, params.get("cmd")), params
	)
	if target and is_locked(target):
		_raise_locked(target)


def target_for_context(context: dict | None) -> tuple | None:
	return rules.context_target(config(), context)


def _chat_reference(doc) -> str | None:
	if doc.doctype == "Chat Thread":
		return doc.get("reference_doctype")
	return _thread_reference(doc.get("thread"))


def has_permission(doc, ptype=None, user=None, debug=False):
	if not in_scope(user):
		return True
	doctype = _chat_reference(doc) if doc.doctype in CHAT_DOCTYPES else doc.doctype
	target = _doctype_target(doctype)
	return not (target and is_locked(target))


def is_protected_doctype(doctype) -> bool:
	settings = config()
	return settings["enabled"] and bool(rules.protected_doctype(settings, doctype))


def protected_push_text() -> str:
	return _("Protected data. Open it in the browser")


def hide_locked_previews(threads: list[dict]) -> list[dict]:
	for thread in threads:
		target = _doctype_target(thread.get("reference_doctype")) if in_scope() else None
		if target and unlocked_until(target) is None:
			thread["last_message_preview"] = protected_push_text()
			thread["sensitive_locked"] = 1
	return threads


def query_conditions(user=None, doctype=None):
	if not doctype or not in_scope(user):
		return ""
	protected = rules.protected_doctype(config(), doctype)
	return "1=0" if protected and is_locked(("DocType", protected)) else ""


def masked_fields(doctype, parenttype=None):
	if getattr(frappe.local, "sensitive_loading", False) or not _request():
		return ()
	fields = config()["fields"].get(doctype)
	if not fields or not in_scope():
		return ()
	return fields if is_locked(("Field", doctype)) else ()


def mask_print(doc, method=None, *args, **kwargs):
	doc.mask_fields()


def after_request(response=None, request=None):
	if response is None:
		return
	until = getattr(frappe.local, "sensitive_until", None)
	if until:
		response.headers[UNTIL_HEADER] = str(int(until))
	locked = getattr(frappe.local, "sensitive_locked", None)
	if not locked or response.mimetype != "application/json":
		return
	body = json.loads(response.get_data(as_text=True) or "{}")
	if isinstance(body, dict):
		response.set_data(json.dumps({**body, "_sensitive_locked": locked}, default=str))


def clear_unlock_on_logout(login_manager=None):
	frappe.cache.delete_value(_unlock_key())


def _pin_doc(user: str, for_update: bool = False):
	if not frappe.db.exists(PIN_DOCTYPE, user):
		return None
	return frappe.get_doc(PIN_DOCTYPE, user, for_update=for_update)


def _ensure_pin_doc(user: str):
	return _pin_doc(user, for_update=True) or frappe.get_doc({"doctype": PIN_DOCTYPE, "user": user})


def _save(doc):
	doc.flags.ignore_permissions = True
	if doc.is_new():
		doc.insert()
	else:
		doc.save()


def log(event: str, user: str, actor: str | None = None, expires_on=None, details: str | None = None):
	request = _request()
	frappe.get_doc(
		{
			"doctype": LOG_DOCTYPE,
			"event": event,
			"user": user,
			"actor": actor if actor and actor != user else None,
			"expires_on": expires_on,
			"ip_address": getattr(frappe.local, "request_ip", None),
			"user_agent": (request.headers.get("User-Agent") or "")[:500] if request else None,
			"details": details,
		}
	).insert(ignore_permissions=True, ignore_links=True)


def access_managers(exclude: str | None = None) -> list[str]:
	from erpnext.access_control.denial import access_managers as managers

	return managers(exclude=exclude)


def notify_managers(subject: str, user: str):
	recipients = [manager for manager in access_managers() if manager not in (user, frappe.session.user)]
	if not recipients:
		return
	enqueue_create_notification(
		recipients,
		{
			"type": "Alert",
			"document_type": PIN_DOCTYPE,
			"document_name": user,
			"subject": subject,
			"from_user": frappe.session.user,
		},
	)


def _check_login_password(password: str):
	try:
		check_password(frappe.session.user, password or "", delete_tracker_cache=False)
	except frappe.AuthenticationError:
		_refuse("wrong_password")


def _validate_new_pin(pin: str, confirm: str):
	refusal = rules.pin_refusal(pin)
	if refusal:
		_refuse(refusal)
	if pin != confirm:
		_refuse("mismatch")


def _no_view_session():
	if _view_session():
		_refuse("viewing", frappe.PermissionError)


def _store_pin(user: str, pin: str):
	update_password(user, pin, doctype="User", fieldname=AUTH_FIELD)
	doc = _ensure_pin_doc(user)
	doc.update(
		{
			"is_set": 1,
			"locked": 0,
			"failed_attempts": 0,
			"pin_set_on": now_datetime(),
		}
	)
	_save(doc)


def _start_unlock(user: str) -> dict:
	now = time.time()
	_store_state({"since": now, "seen": now, "user": user, "actor": _actor()})
	until = unlocked_until()
	frappe.db.set_value(PIN_DOCTYPE, user, "last_unlock", now_datetime(), update_modified=False)
	expires_on = add_to_date(now_datetime(), seconds=int(until - now)) if until else None
	log("Unlocked", user, _actor(), expires_on=expires_on)
	return get_status()


def _refused(code: str) -> dict:
	return {**get_status(), "refusal": code, "message": refusal_messages()[code]}


@frappe.whitelist()
def get_status() -> dict:
	user = frappe.session.user
	doc = _pin_doc(user)
	settings = config()
	return {
		"enabled": settings["enabled"] and not exempt(),
		"has_pin": bool(doc and doc.is_set),
		"blocked": bool(doc and doc.locked),
		"until": unlocked_until(),
		"unlock_minutes": settings["unlock_minutes"],
		"idle_minutes": settings["idle_minutes"],
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=10 * 60)
def set_pin(password: str, pin: str, confirm: str) -> dict:
	_no_view_session()
	user = frappe.session.user
	doc = _pin_doc(user)
	replacing = bool(doc and (doc.is_set or doc.locked))
	_check_login_password(password)
	_validate_new_pin(pin, confirm)
	_store_pin(user, pin)
	log("PIN Reset" if replacing else "PIN Set", user)
	if replacing:
		notify_managers(_("{0} reset their PIN").format(frappe.utils.get_fullname(user)), user)
	return _start_unlock(user)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=10 * 60)
def change_pin(current_pin: str, pin: str, confirm: str) -> dict:
	_no_view_session()
	user = frappe.session.user
	refusal = _verify_pin(user, current_pin)
	if refusal:
		return _refused(refusal)
	_validate_new_pin(pin, confirm)
	_store_pin(user, pin)
	log("PIN Changed", user)
	return _start_unlock(user)


def _verify_pin(user: str, pin: str) -> str | None:
	doc = _pin_doc(user, for_update=True)
	if not doc or not doc.is_set:
		return "no_pin"
	if doc.locked:
		return "blocked"
	try:
		check_password(user, pin or "", doctype="User", fieldname=AUTH_FIELD, delete_tracker_cache=False)
	except frappe.AuthenticationError:
		return _record_failure(doc)
	if doc.failed_attempts:
		doc.failed_attempts = 0
		_save(doc)
	return None


def _record_failure(doc) -> str:
	failed, blocked = rules.after_failure(doc.failed_attempts, config()["max_attempts"])
	doc.update({"failed_attempts": failed, "locked": int(blocked)})
	_save(doc)
	actor = _actor()
	log("Wrong PIN", doc.user, actor, details=str(failed))
	if blocked:
		log("PIN Blocked", doc.user, actor)
		notify_managers(
			_("PIN of {0} is blocked after {1} wrong attempts").format(
				frappe.utils.get_fullname(doc.user), failed
			),
			doc.user,
		)
	return "blocked" if blocked else "wrong_pin"


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=10 * 60)
def unlock(pin: str) -> dict:
	user = frappe.session.user
	refusal = _verify_pin(user, pin)
	return _refused(refusal) if refusal else _start_unlock(user)


@frappe.whitelist(methods=["POST"])
def lock() -> dict:
	if _state():
		frappe.cache.delete_value(_unlock_key())
		log("Locked", frappe.session.user, _actor())
	return get_status()


def clear_pin(user: str):
	doc = _pin_doc(user, for_update=True)
	if not doc or not (doc.is_set or doc.locked):
		frappe.throw(_("{0} has no PIN to reset").format(frappe.utils.get_fullname(user)))
	doc.update({"is_set": 0, "locked": 0, "failed_attempts": 0})
	_save(doc)
	log("PIN Reset", user, frappe.session.user)
	if user != frappe.session.user:
		enqueue_create_notification(
			[user],
			{
				"type": "Alert",
				"document_type": PIN_DOCTYPE,
				"document_name": user,
				"subject": _(
					"{0} reset your PIN. Create a new one the next time you open protected data"
				).format(frappe.utils.get_fullname(frappe.session.user)),
				"from_user": frappe.session.user,
			},
		)


def boot(bootinfo):
	if frappe.session.user in (None, "Guest"):
		return
	settings = config()
	bootinfo.sensitive_data = {
		**get_status(),
		"objects": {
			"doctypes": sorted(settings["doctypes"]),
			"reports": sorted(settings["reports"]),
			"pages": sorted(settings["pages"]),
		},
		"fields": settings["fields"],
	}
