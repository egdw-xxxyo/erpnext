"""One picture of the WhatsApp setup: business numbers, who answers them, and how fast.

Also where WhatsApp managers configure it: each number opens a card (Meta business
profile, notes, who answers and who watches it) and the Employees tab decides who works
with WhatsApp at all. Reply and waiting times are counted in working hours (see
erpnext.crm.whatsapp_stats).
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime, nowdate

from erpnext.crm import whatsapp_access as wa_access
from erpnext.crm import whatsapp_stats as stats

PERIODS = {"today": 0, "7": 7, "30": 30, "90": 90}
# A pending chat older than this is abandoned, not waiting — it stays out of the list.
PENDING_WINDOW_DAYS = 90
PROFILE_FIELDS = (
	"display_phone_number",
	"verified_name",
	"profile_image",
	"about",
	"description",
	"email",
	"websites",
	"address",
	"vertical",
	"quality_rating",
	"messaging_limit",
	"profile_synced_on",
)
EMPLOYEE = "Employee"
MANAGER = "Manager"
ADMIN = "Admin"
# How long to wait before trying again to load a number's profile Meta did not return.
SYNC_RETRY_SECONDS = 3600


@frappe.whitelist()
def get_overview(period="7"):
	wa_access.require_manager()
	if not frappe.db.table_exists("WhatsApp Account"):
		return {"installed": False}
	_sync_new_numbers()
	return _collect(period)


def _collect(period):
	days = PERIODS.get(str(period), 7)
	start = get_datetime(add_days(nowdate(), -days))
	now = now_datetime()
	schedule = stats.load_schedule()

	labels = wa_access.account_labels()
	accounts = _accounts(labels)
	access = frappe.get_all(
		"WhatsApp Number Access", fields=["whatsapp_account", "user", "full_name", "access"]
	)
	chats = frappe.get_all(
		"WhatsApp Chat",
		fields=[
			"name",
			"whatsapp_account",
			"phone",
			"title",
			"creation",
			"last_message_on",
			"last_preview",
			"last_content_type",
			"finished",
			"archived",
		],
	)
	chat_by_key = {(c.whatsapp_account, c.phone): c for c in chats}

	messages = frappe.db.sql(
		"""
		select whatsapp_account, type, `from`, `to`, content_type, creation, owner
		from `tabWhatsApp Message`
		where creation >= %(start)s and whatsapp_account is not null
		order by creation asc
		""",
		{"start": start},
		as_dict=True,
	)

	by_chat = defaultdict(list)
	number_counts = defaultdict(lambda: {"in": 0, "out": 0})
	user_sent = defaultdict(int)
	user_last = {}
	for m in messages:
		peer = m["from"] if m.type == "Incoming" else m["to"]
		by_chat[(m.whatsapp_account, peer)].append(m)
		if m.content_type == "reaction":
			continue
		number_counts[m.whatsapp_account]["in" if m.type == "Incoming" else "out"] += 1
		if m.type == "Outgoing":
			user_sent[m.owner] += 1
			user_last[m.owner] = m.creation

	turns_by_account = defaultdict(list)
	turns_by_user = defaultdict(list)
	pending_in_period = defaultdict(int)
	for key, rows in by_chat.items():
		turns, pending = stats.conversation_turns(rows, schedule)
		for t in turns:
			turns_by_account[key[0]].append(t["seconds"])
			turns_by_user[t["user"]].append(t["seconds"])
		if pending:
			pending_in_period[key[0]] += 1

	pending = _pending(chat_by_key, labels, schedule, now)
	pending_by_account = defaultdict(list)
	for p in pending:
		pending_by_account[p["whatsapp_account"]].append(p)

	mine = wa_access.access_by_account()
	recent = _recent_chats([a["name"] for a in accounts if a["name"] in mine], mine)

	for acc in accounts:
		name = acc["name"]
		acc["my_access"] = mine.get(name)
		acc["recent_chats"] = recent.get(name, [])
		rows = [a for a in access if a.whatsapp_account == name]
		acc_chats = [c for c in chats if c.whatsapp_account == name]
		replies = turns_by_account.get(name, [])
		waiting = pending_by_account.get(name, [])
		asked = len(replies) + pending_in_period.get(name, 0)
		acc.update(
			{
				"responsible": [_person(a) for a in rows if a.access == wa_access.RESPONSIBLE],
				"spectators": [_person(a) for a in rows if a.access == wa_access.SPECTATOR],
				"chats_total": len(acc_chats),
				"chats_active": sum(1 for (a, _p) in by_chat if a == name),
				"chats_new": sum(1 for c in acc_chats if get_datetime(c.creation) >= start),
				"messages_in": number_counts[name]["in"],
				"messages_out": number_counts[name]["out"],
				"replies": len(replies),
				"avg_reply": stats.average(replies),
				"median_reply": stats.median(replies),
				"reply_rate": round(100 * len(replies) / asked) if asked else None,
				"pending": len(waiting),
				"oldest_pending": max((p["waiting"] for p in waiting), default=None),
			}
		)

	return {
		"installed": True,
		"generated_at": frappe.utils.now(),
		"period": str(period),
		"accounts": accounts,
		"employees": _employees(access, labels, turns_by_user, user_sent, user_last, pending_by_account),
		"pending": pending,
		"in_progress": _in_progress(chats, pending, labels),
		"schedule": {"hours": schedule.describe(), "holiday_list": schedule.holiday_list},
	}


def _accounts(labels):
	meta = frappe.get_meta("WhatsApp Account")
	fields = [
		"name",
		"account_name",
		"status",
		"phone_id",
		"business_id",
		"is_default_incoming",
		"is_default_outgoing",
		*PROFILE_FIELDS,
	]
	fields = [f for f in fields if f == "name" or meta.has_field(f)]
	out = []
	for row in frappe.get_all("WhatsApp Account", fields=fields, order_by="creation asc"):
		info = labels.get(row.name, {})
		out.append(dict(row, label=info.get("label") or row.name))
	return out


RECENT_CHATS = 5


def _recent_chats(accounts, mine):
	"""The latest chats of the numbers the user answers or spectates, for the cards."""
	from erpnext.crm.whatsapp_person import people_for

	out = {}
	for account in accounts:
		rows = frappe.get_all(
			"WhatsApp Chat",
			filters={"whatsapp_account": account},
			fields=[
				"name",
				"phone",
				"title",
				"last_message_on",
				"last_preview",
				"last_content_type",
				"finished",
				"archived",
			],
			order_by="last_message_on desc",
			limit=RECENT_CHATS,
		)
		people = people_for([r.phone for r in rows])
		page = (
			"whatsapp-chat-center" if mine.get(account) == wa_access.RESPONSIBLE else "whatsapp-chat-monitor"
		)
		out[account] = [
			{
				"chat": r.name,
				"phone": r.phone,
				"title": r.title or r.phone,
				"image": (people.get(r.phone) or {}).get("image"),
				"last_message_on": str(r.last_message_on) if r.last_message_on else None,
				"preview": frappe.utils.strip_html(r.last_preview or "")[:120],
				"content_type": r.last_content_type,
				"state": _conversation_state(r),
				"page": page,
			}
			for r in rows
		]
	return out


def _conversation_state(chat):
	"""finished / obsolete / progress — the badge a chat carries on the cards."""
	from erpnext.crm.doctype.whatsapp_chat.whatsapp_chat import is_obsolete

	if chat.get("finished"):
		return "obsolete" if is_obsolete(chat) else "finished"
	return "obsolete" if chat.get("archived") else "progress"


def _in_progress(chats, pending, labels):
	"""Conversations nobody marked finished (and not moved to obsolete): the ones a
	customer is waiting in first, longest wait on top, then the rest by last message."""
	from erpnext.crm.whatsapp_person import people_for

	waiting = {p["chat"]: p for p in pending if p["chat"]}
	rows = [c for c in chats if c.last_message_on and not c.finished and not c.archived]
	people = people_for([c.phone for c in rows])
	out = []
	for c in rows:
		p = waiting.get(c.name)
		out.append(
			{
				"chat": c.name,
				"title": c.title or c.phone,
				"phone": c.phone,
				"image": (people.get(c.phone) or {}).get("image"),
				"whatsapp_account": c.whatsapp_account,
				"number_label": labels.get(c.whatsapp_account, {}).get("label") or c.whatsapp_account,
				"last_message_on": str(c.last_message_on),
				"preview": frappe.utils.strip_html(c.last_preview or "")[:120],
				"content_type": c.last_content_type,
				"waiting": p["waiting"] if p else None,
				"since": p["since"] if p else None,
				"count": p["count"] if p else 0,
			}
		)
	out.sort(key=lambda r: r["last_message_on"], reverse=True)
	out.sort(key=lambda r: r["waiting"] if r["waiting"] is not None else -1, reverse=True)
	return out


def _sync_new_numbers():
	"""Load the Meta profile of numbers that never had it (added before the card existed,
	or created without a token); at most once an hour per number."""
	if not frappe.get_meta("WhatsApp Account").has_field("profile_synced_on"):
		return
	for name in frappe.get_all(
		"WhatsApp Account", filters={"profile_synced_on": ["is", "not set"]}, pluck="name"
	):
		key = f"whatsapp_profile_sync_tried:{name}"
		if frappe.cache.get_value(key):
			continue
		frappe.cache.set_value(key, 1, expires_in_sec=SYNC_RETRY_SECONDS)
		try:
			frappe.get_doc("WhatsApp Account", name).save_number_info()
		except Exception:
			frappe.log_error(title="WhatsApp number profile sync failed", message=frappe.get_traceback())


def _person(row):
	return {"user": row.user, "full_name": row.full_name or row.user}


def _pending(chat_by_key, labels, schedule, now):
	"""Chats whose customer spoke last: unanswered incoming messages newer than our
	last outgoing one, per (business number, customer)."""
	rows = frappe.db.sql(
		"""
		select m.whatsapp_account, m.`from` as phone, min(m.creation) as since,
			max(m.creation) as last, count(*) as count
		from `tabWhatsApp Message` m
		left join (
			select whatsapp_account, `to` as phone, max(creation) as last_out
			from `tabWhatsApp Message`
			where type = 'Outgoing' and content_type != 'reaction'
			group by whatsapp_account, `to`
		) o on o.whatsapp_account = m.whatsapp_account and o.phone = m.`from`
		where m.type = 'Incoming'
			and m.content_type != 'reaction'
			and m.creation >= %(window)s
			and (o.last_out is null or m.creation > o.last_out)
		group by m.whatsapp_account, m.`from`
		""",
		{"window": add_days(nowdate(), -PENDING_WINDOW_DAYS)},
		as_dict=True,
	)
	out = []
	for r in rows:
		chat = chat_by_key.get((r.whatsapp_account, r.phone))
		out.append(
			{
				"chat": chat.name if chat else None,
				"title": (chat.title if chat else None) or r.phone,
				"phone": r.phone,
				"whatsapp_account": r.whatsapp_account,
				"number_label": labels.get(r.whatsapp_account, {}).get("label") or r.whatsapp_account,
				"since": str(r.since),
				"last": str(r.last),
				"count": r.count,
				"preview": frappe.utils.strip_html(chat.last_preview or "")[:120] if chat else "",
				"waiting": stats.working_seconds(r.since, now, schedule),
				"waiting_total": int((now - get_datetime(r.since)).total_seconds()),
			}
		)
	out.sort(key=lambda p: p["waiting"], reverse=True)
	return out


def _employees(access, labels, turns_by_user, user_sent, user_last, pending_by_account):
	"""Everyone who works with WhatsApp: holders of the chat or manager role, people with a
	number, and whoever answered a customer in the period (e.g. a System Manager)."""
	numbers = defaultdict(list)
	for row in access:
		numbers[row.user].append(
			{
				"whatsapp_account": row.whatsapp_account,
				"label": labels.get(row.whatsapp_account, {}).get("label") or row.whatsapp_account,
				"access": row.access,
			}
		)
	roles = defaultdict(set)
	for row in frappe.get_all(
		"Has Role",
		filters={
			"parenttype": "User",
			"role": ["in", [wa_access.CHAT_ROLE, wa_access.MANAGER_ROLE, wa_access.ADMIN_ROLE]],
		},
		fields=["parent", "role"],
	):
		roles[row.parent].add(row.role)

	candidates = {u for u, r in roles.items() if r - {wa_access.ADMIN_ROLE}}
	candidates |= set(numbers) | set(turns_by_user) | set(user_sent)
	candidates -= {None, "", "Guest"}
	users = frappe.get_all(
		"User",
		filters={"name": ["in", list(candidates) or [""]], "enabled": 1},
		fields=["name", "full_name", "user_image"],
	)

	out = []
	for u in users:
		replies = turns_by_user.get(u.name, [])
		mine = numbers.get(u.name, [])
		responsible = [n["whatsapp_account"] for n in mine if n["access"] == wa_access.RESPONSIBLE]
		out.append(
			{
				"user": u.name,
				"full_name": u.full_name or u.name,
				"user_image": u.user_image,
				"level": _level(u.name, roles.get(u.name, set())),
				"numbers": mine,
				"replies": len(replies),
				"avg_reply": stats.average(replies),
				"median_reply": stats.median(replies),
				"messages_sent": user_sent.get(u.name, 0),
				"last_activity": str(user_last[u.name]) if u.name in user_last else None,
				"pending": sum(len(pending_by_account.get(a, [])) for a in responsible),
			}
		)
	order = {ADMIN: 0, MANAGER: 1, EMPLOYEE: 2, "": 3}
	out.sort(key=lambda p: (order[p["level"]], (p["full_name"] or "").lower()))
	return out


def _level(user, roles):
	if user == "Administrator" or wa_access.ADMIN_ROLE in roles:
		return ADMIN
	if wa_access.MANAGER_ROLE in roles:
		return MANAGER
	if wa_access.CHAT_ROLE in roles:
		return EMPLOYEE
	return ""


# ---------------------------------------------------------------------------
# Number card
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_number(account, period="30"):
	"""One business number: its Meta profile, notes, people and figures for the period."""
	wa_access.require_manager()
	if not frappe.db.exists("WhatsApp Account", account):
		frappe.throw(_("WhatsApp number {0} not found").format(account), frappe.DoesNotExistError)
	data = _collect(period)
	number = next(a for a in data["accounts"] if a["name"] == account)
	if frappe.get_meta("WhatsApp Account").has_field("notes"):
		number["notes"] = frappe.db.get_value("WhatsApp Account", account, "notes")
	people = {
		row.user: row
		for row in frappe.get_all(
			"WhatsApp Number Access", filters={"whatsapp_account": account}, fields=["user", "access"]
		)
	}
	number["people"] = [
		dict(e, access=people[e["user"]].access) for e in data["employees"] if e["user"] in people
	]
	mine = people.get(frappe.session.user)
	return {
		"number": number,
		"pending": [p for p in data["pending"] if p["whatsapp_account"] == account],
		"in_progress": [c for c in data["in_progress"] if c["whatsapp_account"] == account],
		"my_access": mine.access if mine else None,
		"can_edit_account": 1 if wa_access.is_admin() else 0,
		"period": str(period),
		"generated_at": frappe.utils.now(),
	}


@frappe.whitelist()
def sync_number(account, period="30"):
	wa_access.require_manager()
	doc = frappe.get_doc("WhatsApp Account", account)
	doc.save_number_info()
	return get_number(account, period)


@frappe.whitelist()
def save_notes(account, notes=None):
	wa_access.require_manager()
	frappe.db.set_value("WhatsApp Account", account, "notes", notes or "")


@frappe.whitelist()
def set_number_access(account, user, access=None):
	"""Make `user` Responsible or Spectator on a number; empty `access` takes it away.
	Giving a number also gives the WhatsApp User role, without which the chat pages
	stay hidden. Returns the caller's own numbers, which change when they edit
	themselves."""
	wa_access.require_manager()
	if not frappe.db.exists("WhatsApp Account", account):
		frappe.throw(_("WhatsApp number {0} not found").format(account), frappe.DoesNotExistError)
	if access and access not in (wa_access.RESPONSIBLE, wa_access.SPECTATOR):
		frappe.throw(_("Unknown access level: {0}").format(access))

	name = frappe.db.get_value("WhatsApp Number Access", {"user": user, "whatsapp_account": account})
	if not access:
		if name:
			frappe.delete_doc("WhatsApp Number Access", name, ignore_permissions=True)
	else:
		if not frappe.db.get_value("User", {"name": user, "enabled": 1, "user_type": "System User"}):
			frappe.throw(_("{0} is not an active desk user").format(user))
		if name:
			frappe.db.set_value("WhatsApp Number Access", name, "access", access)
		else:
			frappe.get_doc(
				{
					"doctype": "WhatsApp Number Access",
					"whatsapp_account": account,
					"user": user,
					"access": access,
				}
			).insert(ignore_permissions=True)
		if not _level(user, set(frappe.get_roles(user))):
			doc = frappe.get_doc("User", user)
			doc.flags.ignore_permissions = True
			doc.add_roles(wa_access.CHAT_ROLE)
	frappe.cache.delete_value(wa_access.CACHE_KEY)
	return _my_numbers()


@frappe.whitelist()
def toggle_spectate(account):
	"""A manager starts or stops spectating a number (it shows on their monitor page)."""
	wa_access.require_manager()
	user = frappe.session.user
	current = frappe.db.get_value(
		"WhatsApp Number Access", {"user": user, "whatsapp_account": account}, "access"
	)
	if current == wa_access.RESPONSIBLE:
		frappe.throw(_("You answer this number; its chats are on the WhatsApp Chat page"))
	return set_number_access(account, user, None if current else wa_access.SPECTATOR)


def _my_numbers():
	return {"work": wa_access.my_accounts(), "watch": wa_access.my_watch_accounts()}


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------


@frappe.whitelist()
def set_employee(user, level=None):
	"""Employee chats on the numbers given to them; Manager also configures WhatsApp here.
	No level takes WhatsApp away: both roles and every number."""
	wa_access.require_manager()
	level = level or ""
	if level not in ("", EMPLOYEE, MANAGER):
		frappe.throw(_("Unknown WhatsApp level: {0}").format(level))
	if not frappe.db.get_value("User", {"name": user, "enabled": 1, "user_type": "System User"}):
		frappe.throw(_("{0} is not an active desk user").format(user))
	if user == frappe.session.user and not wa_access.is_admin():
		frappe.throw(_("You cannot change your own WhatsApp level"))

	doc = frappe.get_doc("User", user)
	doc.flags.ignore_permissions = True
	add = {EMPLOYEE: [wa_access.CHAT_ROLE], MANAGER: [wa_access.CHAT_ROLE, wa_access.MANAGER_ROLE]}.get(
		level, []
	)
	drop = [r for r in (wa_access.CHAT_ROLE, wa_access.MANAGER_ROLE) if r not in add]
	current = set(frappe.get_roles(user))
	if drop and current & set(drop):
		doc.remove_roles(*drop)
	if add and set(add) - current:
		doc.add_roles(*add)
	if not level:
		frappe.db.delete("WhatsApp Number Access", {"user": user})
		frappe.cache.delete_value(wa_access.CACHE_KEY)
