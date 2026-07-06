import logging

import frappe
from frappe.model.document import Document

log = logging.getLogger(__name__)

MAX_LOGS = 100
STATUS_TTL_SECONDS = 600


def _status_cache_key(name):
	return f"otdr:status:{name}"


def _decode_hash(raw):
	if not raw:
		return {}
	out = {}
	for k, v in raw.items():
		if isinstance(k, bytes):
			k = k.decode("utf-8", "replace")
		if isinstance(v, bytes):
			v = v.decode("utf-8", "replace")
		out[k] = v
	return out


def push_status(name, **fields):
	"""Write transient status to cache, broadcast via realtime."""
	key = _status_cache_key(name)
	cache = frappe.cache()
	current = _decode_hash(cache.hgetall(key))
	now_iso = frappe.utils.now_datetime().isoformat()
	for k, v in fields.items():
		if v is None:
			continue
		current[k] = "" if v == "" else str(v)
	current["last_seen"] = now_iso
	for k, v in current.items():
		cache.hset(key, k, v)
	cache.expire(key, STATUS_TTL_SECONDS)
	payload = {"otdr": name, "age_s": 0, "server_now": now_iso, **current}
	frappe.publish_realtime(
		"otdr_status_update",
		payload,
		doctype="OTDR",
		docname=name,
		after_commit=False,
	)


def get_status_snapshot(name):
	snap = _decode_hash(frappe.cache().hgetall(_status_cache_key(name)))
	if not snap:
		snap = {}
	now_dt = frappe.utils.now_datetime()
	snap["server_now"] = now_dt.isoformat()
	last_seen = snap.get("last_seen")
	if last_seen:
		try:
			ls_dt = frappe.utils.get_datetime(last_seen)
			snap["age_s"] = int((now_dt - ls_dt).total_seconds())
		except Exception:
			snap["age_s"] = 0
	else:
		snap["age_s"] = 0
	try:
		doc = frappe.get_cached_doc("OTDR", name)
		cfg = doc.get_configuration()
		snap["heartbeat_interval_s"] = int(cfg.get("heartbeat_interval_s") or 10)
	except Exception:
		snap["heartbeat_interval_s"] = 10
	return snap


def resolve_otdr_for_session():
	"""Return the OTDR doc bound to the current session user, or throw."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw("Authentication required", frappe.AuthenticationError)
	rows = frappe.get_all(
		"OTDR",
		filters={"device_user": user, "is_active": 1},
		fields=["name"],
		limit=1,
	)
	if not rows:
		frappe.throw(f"No active OTDR linked to user {user}", frappe.PermissionError)
	doc = frappe.get_doc("OTDR", rows[0].name)
	push_status(doc.name)
	return doc


def publish_config(otdr_name):
	"""Broadcast the current configuration to the device user for one OTDR."""
	doc = frappe.get_doc("OTDR", otdr_name)
	if not doc.device_user:
		return
	cfg = doc.get_configuration_payload()
	frappe.publish_realtime(
		"otdr_config_update",
		cfg,
		user=doc.device_user,
		after_commit=False,
	)


@frappe.whitelist()
def get_status(otdr_name):
	doc = frappe.get_doc("OTDR", otdr_name)
	doc.check_permission("read")
	return get_status_snapshot(otdr_name)


class OTDR(Document):
	def validate(self):
		self._enforce_unique_active_device_user()

	def _enforce_unique_active_device_user(self):
		if not self.device_user or not self.is_active:
			return
		conflict = frappe.db.get_value(
			"OTDR",
			{
				"device_user": self.device_user,
				"is_active": 1,
				"name": ["!=", self.name or ""],
			},
			"name",
		)
		if conflict:
			frappe.throw(
				f"OTDR '{conflict}' is already active for user {self.device_user}. "
				"Deactivate it or assign a different user before activating this one."
			)

	def get_configuration(self):
		if self.otdr_configuration:
			return frappe.get_cached_doc("OTDR Configuration", self.otdr_configuration)
		return frappe._dict(
			idle_timeout=3600,
			measurement_interval_seconds=60,
			sync_folder="/otdr",
			simple_sync=0,
			device_filter="adminvasa",
			phone_name="",
			scan_path="",
			window_hours=2400,
			poll_interval_s=5.0,
			chunk_size=20224,
			heartbeat_interval_s=10,
			extra_config=None,
		)

	def get_configuration_payload(self):
		import json
		cfg = self.get_configuration()
		extra = cfg.get("extra_config")
		if extra:
			try:
				extra = json.loads(extra)
			except Exception:
				pass
		return {
			"otdr": self.name,
			"sync_listening": bool(self.get("sync_listening")),
			"sync_folder": cfg.get("sync_folder") or "/otdr",
			"simple_sync": bool(cfg.get("simple_sync")),
			"measurement_interval_seconds": cfg.get("measurement_interval_seconds") or 60,
			"device_filter": cfg.get("device_filter") or "adminvasa",
			"phone_name": cfg.get("phone_name") or "",
			"scan_path": cfg.get("scan_path") or "",
			"window_hours": cfg.get("window_hours") or 2400,
			"poll_interval_s": cfg.get("poll_interval_s") or 5.0,
			"chunk_size": cfg.get("chunk_size") or 20224,
			"heartbeat_interval_s": cfg.get("heartbeat_interval_s") or 10,
			"extra_config": extra,
			"server_time": frappe.utils.now_datetime().isoformat(),
		}

	def on_update(self):
		watched = ("otdr_configuration", "sync_listening", "device_user", "is_active")
		before = self.get_doc_before_save()
		if before is None:
			return
		if any(self.has_value_changed(k) for k in watched):
			publish_config(self.name)

	def add_measurement_log(self, **kwargs):
		auto_sync = bool(kwargs.pop("auto_sync", False))
		row = self.append("measurement_logs", kwargs)
		self.measurement_logs.remove(row)
		self.measurement_logs.insert(0, row)
		if len(self.measurement_logs) > MAX_LOGS:
			self.measurement_logs = self.measurement_logs[:MAX_LOGS]
		for i, r in enumerate(self.measurement_logs):
			r.idx = i + 1
		self.flags.ignore_permissions = True
		self.save()
		script_results: list[dict] = []
		if auto_sync:
			try:
				from erpnext.manufacturing.doctype.device_script.device_script import run_scripts_for_event
				script_results = run_scripts_for_event(
					"Reflectometer",
					trigger_event="SOR Uploaded",
					otdr=self,
					log_entry=row,
					payload_str=kwargs.get("payload"),
				) or []
			except Exception as e:
				frappe.log_error(title="Reflectometer script dispatch failed")
				script_results = [{"script": "(dispatch)", "status": "Error", "errors": [str(e)]}]
		return {"row": row.name, "script_results": script_results}


@frappe.whitelist()
def set_sync_listening(otdr_name, listening):
	doc = frappe.get_doc("OTDR", otdr_name)
	doc.check_permission("write")
	val = 1 if str(listening).lower() in ("1", "true", "yes") else 0
	frappe.db.set_value("OTDR", otdr_name, "sync_listening", val, update_modified=False)
	frappe.db.commit()
	publish_config(otdr_name)
	return {"sync_listening": val}
