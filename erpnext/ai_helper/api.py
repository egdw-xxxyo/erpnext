import anthropic
import frappe
from frappe import _

import erpnext
from erpnext.ai_helper import knowledge, tools
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
data (a document's state, stock, a linked record) instead of guessing. Use get_doctype_logic to see the validation
code (controller, hooks, scripts) when you need to know which check raised the error. You cannot change anything;
if a fix needs a change, tell the user exactly what to do. If you are not sure, say so.
If the context lists known wrong solutions, never suggest them again; propose a different cause or fix."""

DISTILL_PROMPT = """You turn a solved support conversation about an ERPNext error into a short, reusable solution card.
Write 1-3 short imperative sentences (or at most 4 short bullet points) in Ukrainian that tell any user how to fix
this kind of error. Be generic: no user names, document numbers, company names, amounts or dates; say "the document"
instead. No greeting, no explanation of the error, no Markdown headings. Reply with the solution text only."""


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
	return _guarded(lambda: {"reply": _run(credentials, history, context)})


@frappe.whitelist(methods=["POST"])
def lookup(context=None) -> dict:
	"""Saved solutions for the error in `context`; never fails the popup."""
	try:
		return knowledge.lookup(frappe.parse_json(context) if context else {})
	except Exception:
		frappe.clear_messages()
		frappe.log_error(title="AI Helper lookup")
		return {"type": None, "solutions": []}


@frappe.whitelist(methods=["POST"])
def rate(error_type, solution, verdict) -> dict:
	knowledge.rate(error_type, solution, verdict)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def learn(messages, context=None) -> dict:
	"""The user confirmed the conversation helped: distil it into a saved solution."""
	credentials = resolve_credentials()
	if not credentials:
		return {
			"ok": False,
			"error": _("No AI key is set up. Add one in My Settings or ask an administrator."),
		}

	history = _clean_messages(frappe.parse_json(messages), last_role=None)
	context = frappe.parse_json(context) if context else {}
	error_type = context.get("error_type")
	if not error_type or not frappe.db.exists(knowledge.TYPE, error_type):
		found = knowledge.touch(context)
		if not found:
			return {"ok": False, "error": _("Nothing to save")}
		error_type = found["name"]

	def distil():
		text = _distil(credentials, history, context)
		return {"solution": knowledge.add_solution(error_type, text)}

	return _guarded(distil)


def _guarded(fn) -> dict:
	try:
		return {"ok": True, **fn()}
	except frappe.ValidationError as e:
		frappe.clear_messages()
		return {"ok": False, "error": str(e)}
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


def _clean_messages(raw, last_role: str | None = "user") -> list[dict]:
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
	if not cleaned or (last_role and cleaned[-1]["role"] != last_role):
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
	known = knowledge.knowledge_block(context.get("error_type"))
	if known:
		lines.append(known)
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


def _distil(credentials: dict, history: list[dict], context: dict) -> str:
	client = build_client(credentials["token"])
	system = []
	if is_oauth(credentials["token"]):
		system.append({"type": "text", "text": OAUTH_SYSTEM_PREFIX})
	system.append({"type": "text", "text": DISTILL_PROMPT})
	transcript = "\n\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in history)
	prompt = f"Error:\n{str(context.get('error') or '')[:MAX_CONTEXT_CHARS]}\n\nConversation:\n{transcript}"
	response = client.messages.create(
		model=model_id(credentials["model"]),
		max_tokens=600,
		system=system,
		messages=[{"role": "user", "content": prompt}],
	)
	text = "".join(b.text for b in response.content if b.type == "text").strip()
	if response.stop_reason == "refusal" or not text:
		frappe.throw(_("The AI could not write a solution."))
	return text
