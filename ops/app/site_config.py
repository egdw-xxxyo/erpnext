"""Typed editor for ``site-config.json`` in the repo on the host.

./deploy's apply_site_config pushes every key into the site (or, for the
keys it lists as global, into common_site_config.json) on each deploy or on
``./deploy apply-config``. Keys this editor does not know are kept and
editable as raw JSON. Reference: docs/site-config.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CONFIG_FILE = "site-config.json"


class InvalidSiteConfig(ValueError):
	pass


@dataclass(frozen=True)
class Key:
	key: str
	label: str
	kind: str  # bool | text | int | secret | select
	help: str = ""
	options: tuple[str, ...] = ()


KEYS: tuple[Key, ...] = (
	Key(
		"environment",
		"Environment",
		"select",
		"Marks the instance as prod / dev / test (dashboard badge, instance_env).",
		("", "prod", "dev", "test"),
	),
	Key("host_name", "Site URL (host_name)", "text", "Used for links in emails and printouts."),
	Key(
		"server_script_enabled",
		"Server Scripts and Script Reports",
		"bool",
		"Written to common_site_config.json.",
	),
	Key("insights_enabled", "Install Frappe Insights on deploy", "bool"),
	Key(
		"scanner_secret", "Scanner secret", "secret", "Shared secret the barcode scanners sign requests with."
	),
	Key(
		"fcm_service_account_json",
		"Firebase service account (path)",
		"text",
		"Path inside the container; enables push notifications to the Android app.",
	),
	Key("mute_emails", "Mute all outgoing email", "bool"),
	Key("developer_mode", "Developer mode", "bool", "Never on prod."),
	Key("disable_website_cache", "Disable website cache", "bool"),
	Key("logging", "Logging level", "select", "", ("", "0", "1", "2")),
	Key("max_file_size", "Max upload size, bytes", "int"),
)
KNOWN = {k.key for k in KEYS}


def parse(text: str | None) -> dict:
	if not text or not text.strip():
		return {}
	try:
		data = json.loads(text)
	except json.JSONDecodeError as exc:
		raise InvalidSiteConfig(f"site-config.json on the host is not valid JSON: {exc}") from exc
	if not isinstance(data, dict):
		raise InvalidSiteConfig("site-config.json on the host is not a JSON object.")
	return data


def extra_json(config: dict) -> str:
	extra = {k: v for k, v in config.items() if k not in KNOWN}
	return json.dumps(extra, indent=2, ensure_ascii=False) if extra else ""


def render(config: dict) -> str:
	return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def validate(current: dict, form: dict[str, str]) -> dict:
	"""Build the new config from the form. Unchecked flags that were set
	become 0 rather than disappearing: apply_site_config only ever sets keys,
	so a removed key would stay applied in the site."""
	config: dict = {}
	for key in KEYS:
		raw = (form.get(key.key) or "").strip()
		if key.kind == "bool":
			if raw == "on":
				config[key.key] = 1
			elif key.key in current:
				config[key.key] = 0
		elif key.kind == "secret":
			if form.get(f"{key.key}__clear") == "on":
				continue
			if raw:
				config[key.key] = raw
			elif key.key in current:
				config[key.key] = current[key.key]
		elif key.kind == "int":
			if raw:
				try:
					config[key.key] = int(raw)
				except ValueError as exc:
					raise InvalidSiteConfig(f"{key.label} must be a whole number.") from exc
		elif key.kind == "select":
			if raw and raw not in key.options:
				raise InvalidSiteConfig(f"{key.label}: unexpected value {raw!r}.")
			if raw:
				config[key.key] = int(raw) if raw.isdigit() else raw
		elif raw:
			config[key.key] = raw

	extra_raw = (form.get("extra") or "").strip()
	if extra_raw:
		try:
			extra = json.loads(extra_raw)
		except json.JSONDecodeError as exc:
			raise InvalidSiteConfig(f"Other keys: not valid JSON ({exc}).") from exc
		if not isinstance(extra, dict):
			raise InvalidSiteConfig('Other keys must be a JSON object: { "key": value }.')
		clash = KNOWN.intersection(extra)
		if clash:
			raise InvalidSiteConfig(
				f"Set {', '.join(sorted(clash))} with the fields above, not under Other keys."
			)
		config.update(extra)
	return config
