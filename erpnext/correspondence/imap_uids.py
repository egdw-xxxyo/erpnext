import re
from typing import NamedTuple

BATCH_SIZE = 100


class FolderState(NamedTuple):
	uidvalidity: str
	uidnext: int


def status_value(text: str, key: str) -> int:
	match = re.search(rf"\b{key} (\d+)", text, re.IGNORECASE)
	return int(match[1]) if match else 0


def parse_status(response: bytes) -> FolderState:
	text = response.decode(errors="replace")
	return FolderState(str(status_value(text, "UIDVALIDITY")), status_value(text, "UIDNEXT"))


def stored_uid(value) -> int:
	text = str(value or "").strip()
	return int(text) if text.isdigit() else 0


def first_uid(stored_validity, stored_next, server: FolderState, backlog: int) -> int:
	if str(stored_validity or "") == server.uidvalidity and stored_uid(stored_next):
		return stored_uid(stored_next)
	return max(1, server.uidnext - backlog)


def new_uids(search_response: bytes | None, start: int, limit: int = BATCH_SIZE) -> list[int]:
	return sorted(uid for uid in map(int, (search_response or b"").split()) if uid >= start)[:limit]


def parse_fetch(data: list | None) -> tuple[bytes | None, str]:
	parts = data or []
	raw = next((part[1] for part in parts if isinstance(part, tuple) and b"BODY[]" in part[0]), None)
	headers = [part[0] if isinstance(part, tuple) else part for part in parts]
	seen = any(isinstance(header, bytes) and b"\\seen" in header.lower() for header in headers)
	return raw, "SEEN" if seen else "UNSEEN"
