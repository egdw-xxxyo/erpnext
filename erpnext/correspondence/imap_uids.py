import re
from datetime import date, timedelta
from typing import NamedTuple

BATCH_SIZE = 100
IMAP_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class FolderState(NamedTuple):
	uidvalidity: str
	uidnext: int


class ReadPlan(NamedTuple):
	criteria: str
	start: int


def status_value(text: str, key: str) -> int:
	match = re.search(rf"\b{key} (\d+)", text, re.IGNORECASE)
	return int(match[1]) if match else 0


def parse_status(response: bytes) -> FolderState:
	text = response.decode(errors="replace")
	return FolderState(str(status_value(text, "UIDVALIDITY")), status_value(text, "UIDNEXT"))


def stored_uid(value) -> int:
	text = str(value or "").strip()
	return int(text) if text.isdigit() else 0


def imap_date(day: date) -> str:
	return f"{day.day:02d}-{IMAP_MONTHS[day.month - 1]}-{day.year}"


def uid_plan(start: int) -> ReadPlan:
	return ReadPlan(f"UID {start}:*", start)


def read_plan(
	stored_validity, stored_next, server: FolderState, reread_since: date | None
) -> ReadPlan | None:
	if not server.uidnext:
		return None
	if str(stored_validity or "") == server.uidvalidity and stored_uid(stored_next):
		return uid_plan(stored_uid(stored_next))
	if stored_validity and reread_since:
		return ReadPlan(f"SINCE {imap_date(reread_since - timedelta(days=1))}", 1)
	return uid_plan(server.uidnext)


def progress_start(plan: ReadPlan, uids: list[int], server: FolderState) -> int:
	return uids[0] if uids else max(plan.start, server.uidnext)


def new_uids(search_response: bytes | None, start: int, limit: int = BATCH_SIZE) -> list[int]:
	uids = (int(uid) for uid in (search_response or b"").split())
	return sorted(uid for uid in uids if uid >= start)[:limit]


def parse_fetch(data: list | None) -> tuple[bytes | None, str]:
	parts = data or []
	raw = next((part[1] for part in parts if isinstance(part, tuple) and b"BODY[]" in part[0]), None)
	headers = [part[0] if isinstance(part, tuple) else part for part in parts]
	seen = any(isinstance(header, bytes) and b"\\seen" in header.lower() for header in headers)
	return raw, "SEEN" if seen else "UNSEEN"
