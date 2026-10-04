import hashlib
import re
from collections.abc import Iterable, Mapping

PATTERN_SEPARATORS = re.compile(r"[\s,;]+")


def parse_patterns(text: str | None) -> tuple[str, ...]:
	return tuple(dict.fromkeys(part.lower() for part in PATTERN_SEPARATORS.split(text or "") if part))


def matches(patterns: Iterable[str], address: str | None) -> bool:
	address = (address or "").strip().lower()
	return bool(address) and any(pattern in address for pattern in patterns)


def applies_to_mailbox(rule: Mapping, mailbox: str) -> bool:
	return not rule.get("email_account") or rule["email_account"] == mailbox


def route(rules: Iterable[Mapping], sender: str, mailbox: str) -> dict[str, tuple[str, ...]]:
	pairs = [
		(code, rule["name"])
		for rule in rules
		if applies_to_mailbox(rule, mailbox) and matches(rule["patterns"], sender)
		for code in rule["recipients"]
	]
	return {
		code: tuple(dict.fromkeys(name for pair_code, name in pairs if pair_code == code))
		for code in dict.fromkeys(code for code, _name in pairs)
	}


def skip_reason(recipient: Mapping | None) -> str | None:
	if not recipient:
		return "Recipient not found"
	if not recipient.get("enabled"):
		return "Recipient is disabled"
	if not recipient.get("email"):
		return "Recipient has no email"
	return None


def plan_copies(routes: Mapping[str, tuple[str, ...]], recipients: Mapping[str, Mapping]) -> list[dict]:
	candidates = [
		{
			"recipient": code,
			"email": ((recipients.get(code) or {}).get("email") or "").strip().lower() or None,
			"rules": rules,
			"skip": skip_reason(recipients.get(code)),
		}
		for code, rules in routes.items()
	]
	skipped = [copy for copy in candidates if copy["skip"]]
	deliverable = [copy for copy in candidates if not copy["skip"]]
	emails = dict.fromkeys(copy["email"] for copy in deliverable)
	merged = [
		{
			**next(copy for copy in deliverable if copy["email"] == email),
			"rules": tuple(
				dict.fromkeys(
					rule for copy in deliverable if copy["email"] == email for rule in copy["rules"]
				)
			),
		}
		for email in emails
	]
	return merged + skipped


def dedupe_key(message_id: str | None, communication: str, target: str) -> str:
	source = f"{message_id or communication}|{target}".lower()
	return hashlib.sha1(source.encode()).hexdigest()
