import anthropic
import frappe
from frappe.utils.password import get_decrypted_password

import erpnext

MODELS = {"Haiku": "claude-haiku-5-5"}
DEFAULT_MODEL = "Haiku"
OAUTH_BETA = "oauth-2025-04-20"
OAUTH_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."
PERSONAL_FIELD = "ai_helper_token"


def is_oauth(token: str) -> bool:
	return token.startswith("sk-ant-oat")


def resolve_credentials(user: str | None = None) -> dict | None:
	"""Personal key first, then the key of the user's company, then the company-less default row."""
	user = user or frappe.session.user
	settings = frappe.get_single("AI Helper Settings")
	if not settings.enabled:
		return None

	token = get_decrypted_password("User", user, PERSONAL_FIELD, raise_exception=False)
	if token:
		return {"token": token, "model": DEFAULT_MODEL, "source": "user"}

	company = erpnext.get_default_company(user)
	rows = {(row.company or ""): row for row in settings.company_keys}
	row = rows.get(company or "") or rows.get("")
	if not row:
		return None
	token = row.get_password("auth_token", raise_exception=False)
	if not token:
		return None
	return {
		"token": token,
		"model": row.model or DEFAULT_MODEL,
		"source": "company" if row.company else "default",
	}


def build_client(token: str) -> anthropic.Anthropic:
	if is_oauth(token):
		return anthropic.Anthropic(
			api_key=None,
			auth_token=token,
			default_headers={"anthropic-beta": OAUTH_BETA},
			timeout=60.0,
		)
	return anthropic.Anthropic(api_key=token, timeout=60.0)


def model_id(model: str) -> str:
	return MODELS.get(model, MODELS[DEFAULT_MODEL])
