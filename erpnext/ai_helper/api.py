import anthropic
import frappe
from frappe import _

import erpnext
from erpnext.ai_helper import tools
from erpnext.ai_helper.client import (
	OAUTH_SYSTEM_PREFIX,
	build_client,
	is_oauth,
	model_id,
	resolve_credentials,
)

MAX_STEPS = 6
MAX_TURNS = 30
MAX_MESSAGE_CHARS = 8000
MAX_CONTEXT_CHARS = 6000

SYSTEM_PROMPT = """You are the built-in assistant of an ERPNext (Frappe v16) installation used by a manufacturing company.
The user opened you from an error popup. Explain in plain words why the error happened and how to fix it, step by step.
Answer in Ukrainian unless the user writes in another language. Format answers in Markdown, keep them short.
You have read-only tools that read ERP data with the user's own permissions: use them when the cause depends on
data (a document's state, stock, a linked record) instead of guessing. You cannot change anything; if a fix needs a
change, tell the user exactly what to do. If you are not sure, say so."""


@frappe.whitelist()
def get_status() -> dict:
	credentials = resolve_credentials()
	return {"available": bool(credentials), "source": credentials["source"] if credentials else None}


@frappe.whitelist(methods=["POST"])
def chat(messages, context=None) -> dict:
	credentials = resolve_credentials()
	if not credentials:
		return {
			"ok": False,
			"error": _("No AI key is set up. Add one in My Settings or ask an administrator."),
		}

	history = _clean_messages(frappe.parse_json(messages))
	context = frappe.parse_json(context) if context else {}

	try:
		reply = _run(credentials, history, context)
	except anthropic.AuthenticationError:
		return {
			"ok": False,
			"error": _("The AI key was rejected. Check it in My Settings or AI Helper Settings."),
		}
	except anthropic.PermissionDeniedError:
		return {"ok": False, "error": _("The AI key has no access to this model.")}
	except anthropic.RateLimitError:
		return {"ok": False, "error": _("AI rate limit reached, try again in a minute.")}
	except anthropic.APIConnectionError:
		return {"ok": False, "error": _("Cannot reach the AI service.")}
	except anthropic.APIStatusError as e:
		frappe.log_error(title="AI Helper API error")
		return {"ok": False, "error": _("AI service error ({0}).").format(e.status_code)}
	return {"ok": True, "reply": reply}


def _clean_messages(raw) -> list[dict]:
	if not isinstance(raw, list) or not raw:
		frappe.throw(_("Nothing to send"))
	cleaned = []
	for m in raw[-MAX_TURNS:]:
		role = m.get("role")
		text = str(m.get("content") or "")[:MAX_MESSAGE_CHARS]
		if role in ("user", "assistant") and text:
			cleaned.append({"role": role, "content": text})
	while cleaned and cleaned[0]["role"] != "user":
		cleaned.pop(0)
	if not cleaned or cleaned[-1]["role"] != "user":
		frappe.throw(_("Nothing to send"))
	return cleaned


def _context_block(context: dict) -> str:
	lines = [
		f"User: {frappe.session.user}",
		f"Company: {erpnext.get_default_company() or '-'}",
		f"Today: {frappe.utils.today()}",
	]
	for key in ("url", "route", "title"):
		if context.get(key):
			lines.append(f"{key.capitalize()}: {str(context[key])[:500]}")
	if context.get("error"):
		lines.append("Error shown to the user:\n" + str(context["error"])[:MAX_CONTEXT_CHARS])
	return "\n".join(lines)


def _system(token: str, context: dict) -> list[dict]:
	blocks = []
	if is_oauth(token):
		blocks.append({"type": "text", "text": OAUTH_SYSTEM_PREFIX})
	blocks.append({"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}})
	blocks.append({"type": "text", "text": _context_block(context)})
	return blocks


def _run(credentials: dict, history: list[dict], context: dict) -> str:
	client = build_client(credentials["token"])
	system = _system(credentials["token"], context)
	conversation = list(history)

	for _step in range(MAX_STEPS):
		response = client.messages.create(
			model=model_id(credentials["model"]),
			max_tokens=4096,
			system=system,
			tools=tools.TOOL_SCHEMAS,
			messages=conversation,
		)
		text = "".join(b.text for b in response.content if b.type == "text").strip()

		if response.stop_reason == "refusal":
			return _("The AI declined to answer this request.")
		if response.stop_reason != "tool_use":
			return text or _("No answer.")

		conversation.append({"role": "assistant", "content": response.content})
		results = []
		for block in response.content:
			if block.type != "tool_use":
				continue
			output, is_error = tools.execute(block.name, block.input)
			results.append(
				{"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error}
			)
		conversation.append({"role": "user", "content": results})

	return _("The AI needed too many data lookups. Ask a narrower question.")
