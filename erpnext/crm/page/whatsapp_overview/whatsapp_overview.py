"""One picture of the WhatsApp setup: business numbers, who answers them, and how fast.

Reply and waiting times are counted in working hours (see erpnext.crm.whatsapp_stats).
Reads only.
"""

from collections import defaultdict

import frappe
from frappe.utils import add_days, get_datetime, now_datetime, nowdate

from erpnext.crm import whatsapp_access as wa_access
from erpnext.crm import whatsapp_stats as stats

VIEW_ROLES = ("System Manager", "Sales Manager")
PERIODS = {"today": 0, "7": 7, "30": 30, "90": 90}
# A pending chat older than this is abandoned, not waiting — it stays out of the list.
PENDING_WINDOW_DAYS = 90


@frappe.whitelist()
def get_overview(period="7"):
	frappe.only_for(VIEW_ROLES)
	if not frappe.db.table_exists("WhatsApp Account"):
		return {"installed": False}

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
		fields=["name", "whatsapp_account", "phone", "title", "creation", "last_message_on", "last_preview"],
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

	for acc in accounts:
		name = acc["name"]
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
		"managers": _managers(access, labels, turns_by_user, user_sent, user_last, pending_by_account),
		"pending": pending,
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
	]
	fields = [f for f in fields if f == "name" or meta.has_field(f)]
	out = []
	for row in frappe.get_all("WhatsApp Account", fields=fields, order_by="creation asc"):
		info = labels.get(row.name, {})
		out.append(
			dict(
				row,
				label=info.get("label") or row.name,
				display_phone_number=info.get("display_phone_number"),
				verified_name=info.get("verified_name"),
			)
		)
	return out


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


def _managers(access, labels, turns_by_user, user_sent, user_last, pending_by_account):
	people = {}
	for row in access:
		p = people.setdefault(
			row.user, {"user": row.user, "full_name": row.full_name or row.user, "numbers": []}
		)
		p["numbers"].append(
			{
				"whatsapp_account": row.whatsapp_account,
				"label": labels.get(row.whatsapp_account, {}).get("label") or row.whatsapp_account,
				"access": row.access,
			}
		)
	# Whoever answered without an access row (e.g. a System Manager) still shows up.
	for user in set(turns_by_user) | set(user_sent):
		if user and user not in people and user not in ("Guest",):
			people[user] = {
				"user": user,
				"full_name": frappe.utils.get_fullname(user),
				"numbers": [],
			}

	out = []
	for p in people.values():
		replies = turns_by_user.get(p["user"], [])
		responsible = [n["whatsapp_account"] for n in p["numbers"] if n["access"] == wa_access.RESPONSIBLE]
		p.update(
			{
				"replies": len(replies),
				"avg_reply": stats.average(replies),
				"median_reply": stats.median(replies),
				"messages_sent": user_sent.get(p["user"], 0),
				"last_activity": str(user_last[p["user"]]) if p["user"] in user_last else None,
				"pending": sum(len(pending_by_account.get(a, [])) for a in responsible),
			}
		)
		out.append(p)
	out.sort(key=lambda p: (-p["replies"], p["full_name"] or ""))
	return out
