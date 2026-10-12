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


PRIVILEGED_ROLES = frozenset({"Administrator", "System Manager", "Access Manager"})
NEVER_GRANTED_ROLES = PRIVILEGED_ROLES | {"All", "Guest", "Desk User"}
PROFILE_MODES = ("add", "replace")

SHARE_RIGHTS = ("read", "write", "submit", "share")
SHAREABLE_PTYPES = frozenset({"read", "write", "submit", "share", "print", "email", "select"})


PROTECTED_MODULES = frozenset({"Core", "Custom", "Desk", "Integrations", "Automation"})


def is_grantable(role: str) -> bool:
	return bool(role) and role not in NEVER_GRANTED_ROLES


def role_right_unavailable(is_doctype_request: bool, doctype: str | None, module: str | None) -> str | None:
	if not is_doctype_request:
		return "not_doctype"
	if doctype in SENSITIVE_DOCTYPES or module in PROTECTED_MODULES:
		return "protected_doctype"
	return None


def role_right_refusal(role: str | None, approver_roles: Iterable[str]) -> str | None:
	held = frozenset(approver_roles)
	if not is_grantable(role):
		return "never_granted"
	if role in held and "System Manager" not in held:
		return "own_role"
	return None


def held_rights(rows: Iterable[Mapping], role: str) -> frozenset[str]:
	return frozenset(
		right
		for row in rows
		if row["role"] == role and row["permlevel"] == 0 and not row["if_owner"]
		for right in row["rights"]
	)


def rights_to_add(rows: Iterable[Mapping], role: str, wanted: Iterable[str]) -> list[str]:
	held = held_rights(rows, role)
	return [right for right in dict.fromkeys(wanted) if right not in held]


def role_grant_log(role: str, profiles: Sequence[str], profile_action: str | None) -> dict:
	linked = bool(profiles) and profile_action != "unlink"
	return {
		"role": role,
		"profile": (profile_action or "").removeprefix("profile:") if linked else None,
		"unlinked": list(profiles) if profiles and profile_action == "unlink" else [],
	}


REVOCABLE = ("Role", "Role Right", "Document Share", "User Permission")


def is_revocable(resolution: str | None, log: Mapping | None) -> bool:
	if not log or resolution not in REVOCABLE:
		return False
	return not (resolution == "Role" and log.get("profile"))


def roles_after_revoke(resolution: str, log: Mapping, current: Iterable[str]) -> list[str] | None:
	if resolution != "Role":
		return None
	return [role for role in current if role != log["role"]]


def same_rows(left: Iterable[Mapping], right: Iterable[Mapping]) -> bool:
	def signature(rows):
		return frozenset(
			(row["role"], row["permlevel"], row["if_owner"], row["rights"]) for row in rows if row["rights"]
		)

	return signature(left) == signature(right)


def rows_with_rights(rows: Iterable[Mapping], role: str, rights: Iterable[str]) -> tuple[dict, ...]:
	return (*rows, {"role": role, "permlevel": 0, "if_owner": False, "rights": frozenset(rights)})


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
		key=lambda candidate: (len(candidate.get("missing") or ()), candidate["size"], candidate["role"]),
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


def share_unavailable(has_document: bool, ptype: str) -> str | None:
	if not has_document:
		return "no_document"
	return None if share_rights_for(ptype) else "not_shareable"


def user_permission_unavailable(
	has_document: bool, links: Iterable[tuple[str, str]], allowed: Mapping[str, Iterable[str]]
) -> str | None:
	if not has_document:
		return "no_document"
	links = list(links)
	if user_permission_candidates(links, allowed):
		return None
	restricted = any(value and doctype in allowed for doctype, value in links)
	return "already_allowed" if restricted else "no_restrictions"


def is_offerable_profile(profile_roles: Iterable[str], granting: Iterable[str]) -> bool:
	roles = set(profile_roles)
	return bool(roles & set(granting)) and not roles & PRIVILEGED_ROLES


def roles_after_profile(
	mode: str, current_profiles: Iterable[Iterable[str]], profile_roles: Iterable[str]
) -> list[str]:
	kept = () if mode == "replace" else (role for roles in current_profiles for role in roles)
	return sorted({*kept, *profile_roles})


def rank_profiles(candidates: Iterable[Mapping]) -> list[dict]:
	return sorted(
		(dict(candidate) for candidate in candidates),
		key=lambda candidate: (
			len(candidate.get("missing") or ()),
			len(candidate["lost_roles"]),
			candidate["size"],
			candidate["profile"],
		),
	)


SUBMIT_RIGHTS = frozenset({"submit", "cancel", "amend"})
SHARE_IMPLIED = {"print": "read", "email": "read"}


def applicable_rights(rights: Iterable[str], is_submittable: bool, allow_import: bool) -> list[str]:
	skipped = {"select", *(() if is_submittable else SUBMIT_RIGHTS), *(() if allow_import else ("import",))}
	return [right for right in rights if right not in skipped]


def requested_rights(ptype: str | None, extra: Iterable[str], applicable: Sequence[str]) -> list[str]:
	required = ("read", ptype or "read")
	chosen = {*required, *(right for right in extra if right in applicable)}
	return list(dict.fromkeys([*(right for right in applicable if right in chosen), *required]))


def chosen_rights(applicable: Sequence[str], chosen: Iterable[str] | None, fallback: list[str]) -> list[str]:
	picked = set(chosen or ())
	return [right for right in applicable if right in picked] or fallback


def coverage(rows: Iterable[Mapping], roles: Iterable[str], rights: Sequence[str]) -> dict[str, str]:
	return dict(access_map(rows, roles, rights).get(0, {}))


def share_coverage(current: Mapping[str, str], shared: Iterable[str]) -> dict[str, str]:
	shared = set(shared)
	given = {right: ALL for right in shared} | {
		right: ALL for right, base in SHARE_IMPLIED.items() if base in shared
	}
	return {**current, **given}


def missing_rights(covered: Mapping[str, str], wanted: Iterable[str]) -> list[str]:
	return [right for right in wanted if not covered.get(right)]


def merge_granting(maps: Iterable[Mapping[str, str]]) -> dict[str, str]:
	maps = list(maps)
	roles = dict.fromkeys(role for granting in maps for role in granting)
	return {role: ALL if any(granting.get(role) == ALL for granting in maps) else OWNER for role in roles}
