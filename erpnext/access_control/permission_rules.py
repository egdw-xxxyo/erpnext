from collections.abc import Iterable, Mapping, Sequence

ALL = "all"
OWNER = "owner"

RISKY_RIGHTS = frozenset({"delete", "cancel", "export", "import", "share"})

SENSITIVE_DOCTYPES = frozenset(
	{
		"User",
		"Role",
		"Role Profile",
		"Module Profile",
		"DocPerm",
		"Custom DocPerm",
		"Custom Role",
		"User Permission",
		"DocShare",
		"Permission Type",
		"System Settings",
		"Access Request",
	}
)

SENSITIVE_MODULES = frozenset({"Payroll", "Payroll UA"})


def is_set(value) -> bool:
	try:
		return bool(int(value or 0))
	except (TypeError, ValueError):
		return False


def normalize_row(row: Mapping, rights: Sequence[str]) -> dict:
	return {
		"role": row.get("role"),
		"permlevel": int(row.get("permlevel") or 0),
		"if_owner": is_set(row.get("if_owner")),
		"rights": frozenset(right for right in rights if is_set(row.get(right))),
	}


def normalize_rows(rows: Iterable[Mapping], rights: Sequence[str]) -> tuple[dict, ...]:
	return tuple(normalize_row(row, rights) for row in rows)


def right_scope(rows: Iterable[Mapping], permlevel: int, right: str) -> str | None:
	granting = [row for row in rows if row["permlevel"] == permlevel and right in row["rights"]]
	if not granting:
		return None
	if permlevel > 0 or right == "create" or any(not row["if_owner"] for row in granting):
		return ALL
	return OWNER


def access_map(rows: Iterable[Mapping], roles: Iterable[str], rights: Sequence[str]) -> dict[int, dict]:
	role_set = frozenset(roles)
	applicable = tuple(row for row in rows if row["role"] in role_set)
	levels = sorted({row["permlevel"] for row in applicable})
	scoped = {level: {right: right_scope(applicable, level, right) for right in rights} for level in levels}
	return {
		level: {right: scope for right, scope in by_right.items() if scope}
		for level, by_right in scoped.items()
		if any(by_right.values())
	}


def _gains(before: str | None, after: str | None) -> bool:
	return bool(after) and (before is None or (before == OWNER and after == ALL))


def access_delta(before: Mapping[int, Mapping], after: Mapping[int, Mapping]) -> dict[int, dict]:
	delta = {
		level: {
			right: scope
			for right, scope in by_right.items()
			if _gains((before.get(level) or {}).get(right), scope)
		}
		for level, by_right in after.items()
	}
	return {level: by_right for level, by_right in delta.items() if by_right}


def effective_rows(standard: Sequence[Mapping], custom: Sequence[Mapping]) -> tuple[str, Sequence[Mapping]]:
	return ("custom", custom) if custom else ("standard", standard)


def inert_roles(standard: Iterable[Mapping], custom: Sequence[Mapping]) -> tuple[str, ...]:
	if not custom:
		return ()
	custom_roles = {row["role"] for row in custom if row["rights"]}
	return tuple(
		dict.fromkeys(row["role"] for row in standard if row["rights"] and row["role"] not in custom_roles)
	)


def granting_roles(rows: Iterable[Mapping], right: str, permlevel: int = 0) -> dict[str, str]:
	candidates = [row for row in rows if row["permlevel"] == permlevel and right in row["rights"]]
	return {
		role: right_scope([row for row in candidates if row["role"] == role], permlevel, right)
		for role in dict.fromkeys(row["role"] for row in candidates)
	}


def page_roles(standard: Iterable[str], custom: Iterable[str]) -> frozenset[str]:
	return frozenset(standard) | frozenset(custom)


def report_roles(standard: Iterable[str], custom: Iterable[str]) -> frozenset[str]:
	return frozenset(custom) or frozenset(standard)


def is_sensitive(doctype: str, module: str | None) -> bool:
	return doctype in SENSITIVE_DOCTYPES or module in SENSITIVE_MODULES


def risky_rights(access: Mapping[int, Mapping]) -> tuple[str, ...]:
	return tuple(
		sorted({right for by_right in access.values() for right in by_right if right in RISKY_RIGHTS})
	)


def has_field_levels(access: Mapping[int, Mapping]) -> bool:
	return any(level > 0 for level in access)


def diagnose(facts: Mapping) -> dict:
	scope = facts.get("scope")
	blockers = [
		code
		for code, failed in (
			("not_submittable", facts.get("not_submittable")),
			("not_importable", facts.get("not_importable")),
			("controller", facts.get("controller_ok") is False),
			("no_role", scope is None),
			("not_owner", scope == OWNER and facts.get("is_owner") is False),
			("user_permission", facts.get("user_permission_ok") is False),
		)
		if failed
	]
	if facts.get("allowed"):
		return {
			"allowed": True,
			"via": "share" if blockers and facts.get("shared") else "role",
			"blockers": blockers,
		}
	return {"allowed": False, "via": None, "blockers": blockers or ["unknown"]}


def docstatus_hints(ptype: str, docstatus: int | None, is_submittable: bool) -> tuple[str, ...]:
	if docstatus is None:
		return ()
	rules = (
		("submitted_is_read_only", ptype == "write" and docstatus == 1),
		("cancel_before_delete", ptype == "delete" and docstatus == 1),
		("cancelled_is_read_only", ptype in ("write", "submit") and docstatus == 2),
		("only_submitted_can_be_cancelled", ptype == "cancel" and docstatus != 1),
		("only_draft_can_be_submitted", ptype == "submit" and is_submittable and docstatus != 0),
	)
	return tuple(code for code, applies in rules if applies)


def workflow_options(transitions: Iterable[Mapping], state: str | None, roles: Iterable[str]) -> list[dict]:
	role_set = frozenset(roles)
	return [
		{
			"action": transition["action"],
			"next_state": transition["next_state"],
			"role": transition["allowed"],
			"user_has_role": transition["allowed"] in role_set,
		}
		for transition in transitions
		if transition["state"] == state
	]


NEVER_GRANTED_ROLES = frozenset(
	{"Administrator", "System Manager", "Access Manager", "All", "Guest", "Desk User"}
)

SHARE_RIGHTS = ("read", "write", "submit", "share")
SHAREABLE_PTYPES = frozenset({"read", "write", "submit", "share", "print", "email", "select"})


def is_grantable(role: str) -> bool:
	return bool(role) and role not in NEVER_GRANTED_ROLES


def delta_size(delta: Mapping) -> int:
	doctype_rights = sum(
		len(level["rights"]) for entry in delta.get("doctypes", ()) for level in entry["access"]
	)
	workflow = delta.get("workflow") or {}
	listed = sum(len(delta.get(key) or ()) for key in ("pages", "reports", "workspaces", "notifications"))
	return (
		doctype_rights
		+ listed
		+ len(workflow.get("transitions", ()))
		+ len(workflow.get("editable_states", ()))
	)


def rank_candidates(candidates: Iterable[Mapping]) -> list[dict]:
	return sorted(
		(dict(candidate) for candidate in candidates),
		key=lambda candidate: (candidate["size"], candidate["role"]),
	)


def share_rights_for(ptype: str) -> tuple[str, ...] | None:
	if ptype not in SHAREABLE_PTYPES:
		return None
	right = ptype if ptype in SHARE_RIGHTS else "read"
	return tuple(dict.fromkeys(("read", right)))


def user_permission_candidates(
	links: Iterable[tuple[str, str]], allowed: Mapping[str, Iterable[str]]
) -> list[dict]:
	return list(
		{
			(doctype, value): {"allow": doctype, "for_value": value}
			for doctype, value in links
			if value and doctype in allowed and value not in set(allowed[doctype])
		}.values()
	)
