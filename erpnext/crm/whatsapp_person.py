"""The customer behind a WhatsApp number, across every business number they write to.

Backed by the fork's `WhatsApp Profiles` (one row per customer number; the webhook keeps
`profile_name` — the name the customer set in WhatsApp — current). We add `custom_name`
and `image` (setup_custom_fields.create_custom_fields_on_whatsapp_profiles): what the
team calls them in ERP. Shown name: custom name > linked Contact > WhatsApp name >
number. Chat titles follow it, so the chat list and headers agree with the person page.

A user reaches a person through their chats: reading needs a chat with that number on a
number the user can read; renaming or changing the photo needs one they answer (or the
WhatsApp manager role).
"""

import frappe
from frappe import _

from erpnext.crm import whatsapp_access as wa_access

PROFILE = "WhatsApp Profiles"


def _digits(phone):
	return "".join(ch for ch in str(phone or "") if ch.isdigit())


def _has_custom_fields():
	meta = frappe.get_meta(PROFILE)
	return meta.has_field("custom_name") and meta.has_field("image")


def profile_name(phone, create=False):
	"""Name of the WhatsApp Profiles row for `phone`, created on demand."""
	phone = _digits(phone)
	if not phone or not frappe.db.exists("DocType", PROFILE):
		return None
	name = frappe.db.get_value(PROFILE, {"number": phone}, "name")
	if name or not create:
		return name
	doc = frappe.get_doc({"doctype": PROFILE, "number": phone}).insert(ignore_permissions=True)
	return doc.name


def people_for(phones):
	"""{phone: {name, image, whatsapp_name, custom_name}} for chat lists, one query."""
	phones = [p for p in {_digits(p) for p in phones} if p]
	if not phones or not frappe.db.exists("DocType", PROFILE):
		return {}
	fields = ["number", "profile_name", "contact"]
	if _has_custom_fields():
		fields += ["custom_name", "image"]
	rows = frappe.get_all(PROFILE, filters={"number": ["in", phones]}, fields=fields)
	contacts = {r.contact for r in rows if r.contact}
	contact_names = (
		dict(
			frappe.get_all(
				"Contact",
				filters={"name": ["in", list(contacts)]},
				fields=["name", "full_name"],
				as_list=True,
			)
		)
		if contacts
		else {}
	)
	out = {}
	for r in rows:
		out[r.number] = {
			"name": r.get("custom_name") or contact_names.get(r.contact) or r.profile_name or None,
			"image": r.get("image"),
			"whatsapp_name": r.profile_name,
			"custom_name": r.get("custom_name"),
		}
	return out


def display_name(phone):
	"""The name ERP shows for this customer number, or None to fall back to the number."""
	return (people_for([phone]).get(_digits(phone)) or {}).get("name")


def _refresh_chat_titles(phone):
	phone = _digits(phone)
	title = display_name(phone)
	for chat in frappe.get_all("WhatsApp Chat", filters={"phone": phone}, pluck="name"):
		frappe.db.set_value("WhatsApp Chat", chat, "title", title or phone, update_modified=False)


def _chats(phone):
	return frappe.get_all(
		"WhatsApp Chat",
		filters={"phone": _digits(phone)},
		fields=[
			"name",
			"whatsapp_account",
			"last_message_on",
			"last_preview",
			"last_content_type",
			"contact",
		],
		order_by="last_message_on desc",
	)


def _require(phone, write=False):
	phone = _digits(phone)
	if not phone:
		frappe.throw(_("Phone number is required"))
	if wa_access.is_manager():
		return phone
	allowed = wa_access.accounts_for(write=write)
	if not any(c.whatsapp_account in allowed for c in _chats(phone)):
		frappe.throw(_("Not permitted to see this WhatsApp contact"), frappe.PermissionError)
	return phone


@frappe.whitelist()
def get_person(phone):
	"""Everything about one customer number for the person page."""
	phone = _require(phone)
	name = profile_name(phone)
	profile = frappe.db.get_value(PROFILE, name, ["profile_name", "contact"], as_dict=True) if name else None
	info = people_for([phone]).get(phone) or {}
	readable = wa_access.accounts_for()
	work = wa_access.work_accounts()
	watch = wa_access.watch_accounts()
	labels = wa_access.account_labels()

	chats, links, seen = [], [], set()
	contact = profile.contact if profile else None
	for c in _chats(phone):
		if c.whatsapp_account not in readable:
			continue
		contact = contact or c.contact
		chats.append(
			{
				"chat": c.name,
				"whatsapp_account": c.whatsapp_account,
				"number": dict(labels.get(c.whatsapp_account, {}), name=c.whatsapp_account),
				"last_message_on": str(c.last_message_on) if c.last_message_on else None,
				"preview": frappe.utils.strip_html(c.last_preview or "")[:160],
				"content_type": c.last_content_type,
				"page": "whatsapp-chat-center"
				if c.whatsapp_account in work
				else ("whatsapp-chat-monitor" if c.whatsapp_account in watch else None),
			}
		)
		for row in frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "WhatsApp Chat", "parent": c.name},
			fields=["link_doctype", "link_name"],
		):
			key = (row.link_doctype, row.link_name)
			if key not in seen:
				seen.add(key)
				links.append({"doctype": row.link_doctype, "name": row.link_name})

	accounts = [c["whatsapp_account"] for c in chats]
	counts = (
		frappe.db.sql(
			"""
			select type, count(*) n, min(creation) first, max(creation) last
			from `tabWhatsApp Message`
			where whatsapp_account in %(accounts)s
				and ((type = 'Incoming' and `from` = %(phone)s) or (type = 'Outgoing' and `to` = %(phone)s))
				and content_type != 'reaction'
			group by type
			""",
			{"accounts": accounts, "phone": phone},
			as_dict=True,
		)
		if accounts
		else []
	)
	stats = {r.type: r for r in counts}
	firsts = [r.first for r in counts if r.first]
	lasts = [r.last for r in counts if r.last]

	return {
		"phone": phone,
		"name": info.get("name") or f"+{phone}",
		"image": info.get("image"),
		"whatsapp_name": info.get("whatsapp_name"),
		"custom_name": info.get("custom_name"),
		"contact": contact,
		"contact_name": frappe.db.get_value("Contact", contact, "full_name") if contact else None,
		"chats": chats,
		"links": links,
		"messages_in": stats["Incoming"].n if "Incoming" in stats else 0,
		"messages_out": stats["Outgoing"].n if "Outgoing" in stats else 0,
		"first_message": str(min(firsts)) if firsts else None,
		"last_message": str(max(lasts)) if lasts else None,
		"can_edit": 1 if _can_edit(phone) else 0,
		"has_custom_fields": 1 if _has_custom_fields() else 0,
	}


def _can_edit(phone):
	if wa_access.is_manager():
		return True
	work = wa_access.work_accounts()
	return any(c.whatsapp_account in work for c in _chats(phone))


def _profile_for_edit(phone):
	phone = _require(phone, write=not wa_access.is_manager())
	if not _has_custom_fields():
		frappe.throw(_("Run the site migration first: WhatsApp contact fields are missing"))
	return phone, frappe.get_doc(PROFILE, profile_name(phone, create=True))


@frappe.whitelist()
def rename(phone, name):
	phone, doc = _profile_for_edit(phone)
	doc.db_set("custom_name", (name or "").strip() or None)
	_refresh_chat_titles(phone)
	return get_person(phone)


@frappe.whitelist()
def set_image(phone, file_url):
	"""Use an image the caller just uploaded as this customer's photo."""
	phone, doc = _profile_for_edit(phone)
	file_name = frappe.db.get_value("File", {"file_url": file_url, "owner": frappe.session.user}, "name")
	if not file_name:
		frappe.throw(_("Upload the image first"))
	frappe.db.set_value(
		"File",
		file_name,
		{"attached_to_doctype": PROFILE, "attached_to_name": doc.name, "attached_to_field": "image"},
	)
	doc.db_set("image", file_url)
	return get_person(phone)


@frappe.whitelist()
def reset(phone):
	"""Back to what WhatsApp reports: drop our custom name and photo."""
	phone, doc = _profile_for_edit(phone)
	doc.db_set({"custom_name": None, "image": None})
	_refresh_chat_titles(phone)
	return get_person(phone)
