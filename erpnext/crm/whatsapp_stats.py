"""Reply-time arithmetic for the WhatsApp Overview.

Time is counted in working hours only (WhatsApp Chat Settings: weekly windows plus
a Holiday List), so a message that arrives on Friday evening and is answered on
Monday morning waits minutes, not a weekend.

A customer "turn" starts with the first incoming message after our last outgoing
one; the next outgoing message answers it. Reactions neither start nor answer a
turn. A turn with no answer yet is pending.
"""

import datetime
from dataclasses import dataclass, field

import frappe
from frappe.utils import get_datetime, get_time, getdate

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DEFAULT_WINDOW = (datetime.time(9, 0), datetime.time(18, 0))
DEFAULT_DAYS = WEEKDAYS[:5]


@dataclass
class Schedule:
	# weekday index (Monday = 0) -> [(start time, end time), ...]
	windows: dict = field(default_factory=dict)
	holidays: set = field(default_factory=set)
	holiday_list: str | None = None

	def describe(self):
		out = []
		for i, day in enumerate(WEEKDAYS):
			for start, end in self.windows.get(i, []):
				out.append({"weekday": day, "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")})
		return out


def load_schedule():
	settings = frappe.get_single("WhatsApp Chat Settings")
	windows = {}
	for row in settings.working_hours or []:
		windows.setdefault(WEEKDAYS.index(row.weekday), []).append(
			(get_time(row.start_time), get_time(row.end_time))
		)
	if not windows:
		windows = {WEEKDAYS.index(day): [DEFAULT_WINDOW] for day in DEFAULT_DAYS}

	holiday_list = settings.holiday_list or _company_holiday_list()
	holidays = set()
	if holiday_list:
		holidays = {
			getdate(d)
			for d in frappe.get_all("Holiday", filters={"parent": holiday_list}, pluck="holiday_date")
		}
	return Schedule(windows=windows, holidays=holidays, holiday_list=holiday_list)


def _company_holiday_list():
	company = frappe.defaults.get_defaults().get("company")
	if company:
		return frappe.get_cached_value("Company", company, "default_holiday_list")
	return None


def working_seconds(start, end, schedule):
	"""Seconds between `start` and `end` that fall inside the schedule's working windows."""
	start, end = get_datetime(start), get_datetime(end)
	if not start or not end or end <= start:
		return 0
	total = 0.0
	day = start.date()
	while day <= end.date():
		if day not in schedule.holidays:
			for w_start, w_end in schedule.windows.get(day.weekday(), []):
				a = max(start, datetime.datetime.combine(day, w_start))
				b = min(end, datetime.datetime.combine(day, w_end))
				if b > a:
					total += (b - a).total_seconds()
		day += datetime.timedelta(days=1)
	return int(total)


def conversation_turns(messages, schedule):
	"""Split one conversation's messages (oldest first) into answered turns and the
	pending one, if any.

	Returns (turns, pending) where each turn is
	{"start", "reply_at", "user", "seconds"} and pending is {"since", "count"} or None.
	"""
	turns = []
	since = None
	count = 0
	for m in messages:
		if m.get("content_type") == "reaction":
			continue
		if m.get("type") == "Incoming":
			if since is None:
				since = m["creation"]
				count = 0
			count += 1
		elif m.get("type") == "Outgoing" and since is not None:
			turns.append(
				{
					"start": since,
					"reply_at": m["creation"],
					"user": m.get("owner"),
					"seconds": working_seconds(since, m["creation"], schedule),
				}
			)
			since = None
	pending = {"since": since, "count": count} if since is not None else None
	return turns, pending


def average(values):
	return int(sum(values) / len(values)) if values else None


def median(values):
	if not values:
		return None
	ordered = sorted(values)
	mid = len(ordered) // 2
	if len(ordered) % 2:
		return int(ordered[mid])
	return int((ordered[mid - 1] + ordered[mid]) / 2)
