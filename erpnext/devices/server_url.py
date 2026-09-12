"""Best guess at the address a device on the LAN can actually reach this site on.

Moved out of `otdr_api` when the OTDR doctype was removed. It never had anything to do
with reflectometers — `Scanner.get_config_barcodes` uses it to bake a server URL into the
scanner's configuration barcodes, and the provisioning QR needs the same answer. The
problem it solves is that a Dockerised bench site knows itself as `frontend` or
`localhost`, neither of which means anything to a phone or a scanner gun.
"""

import os
import socket
from urllib.parse import urlparse, urlunparse

import frappe


def detect_public_base_url() -> str:
	"""Return best-guess LAN-reachable server URL.

	Preference:
	1. Env var PUBLIC_SERVER_URL (explicit override).
	2. Incoming HTTP request Host header (what the user actually typed) — unless localhost.
	3. Socket-detected outbound LAN IP + scheme/port from get_url() — Docker bridge IPs
	   are filtered out (10.*, 172.16-31.*, 192.168.* accepted; but only if not the
	   container's own bridge subnet — best effort).
	4. frappe.utils.get_url() as-is.
	"""
	env = (os.environ.get("PUBLIC_SERVER_URL") or "").strip().rstrip("/")
	if env:
		return env

	base = frappe.utils.get_url() or "http://localhost:8080"
	parsed = urlparse(base)

	req_url = _url_from_request()
	if req_url:
		return req_url

	host = (parsed.hostname or "").lower()
	needs_swap = (
		host in ("", "localhost", "127.0.0.1") or host.startswith("frontend") or host.startswith("backend")
	)
	if not needs_swap:
		return base.rstrip("/")

	lan = _detect_lan_ip()
	if lan:
		port = f":{parsed.port}" if parsed.port else ""
		netloc = f"{lan}{port}"
		return urlunparse((parsed.scheme or "http", netloc, parsed.path or "", "", "", "")).rstrip("/")

	return base.rstrip("/")


def _url_from_request() -> str | None:
	try:
		req = getattr(frappe.local, "request", None)
		if req is None:
			return None
		host_hdr = (req.headers.get("X-Forwarded-Host") or req.headers.get("Host") or "").strip()
		if not host_hdr:
			return None
		hostname = host_hdr.split(":", 1)[0].lower()
		if (
			hostname in ("localhost", "127.0.0.1", "")
			or hostname.startswith("frontend")
			or hostname.startswith("backend")
		):
			return None
		scheme = (req.headers.get("X-Forwarded-Proto") or req.scheme or "http").split(",")[0].strip()
		return f"{scheme}://{host_hdr}".rstrip("/")
	except Exception:
		return None


def _detect_lan_ip() -> str | None:
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.settimeout(0.5)
		s.connect(("8.8.8.8", 80))
		ip = s.getsockname()[0]
		s.close()
		if ip and not ip.startswith("127.") and ip != "0.0.0.0":
			return ip
	except Exception:
		return None
	return None
