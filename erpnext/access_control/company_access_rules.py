from collections.abc import Iterable, Mapping

ALLOW = "Company"

IN_EFFECT = "In Effect"
NARROWS = "Narrows"
NO_EFFECT = "No Effect"
USER_DISABLED = "User Disabled"


def module_doctypes(candidates: Mapping[str, str], modules: Iterable[str]) -> set[str]:
	chosen_modules = set(modules)
	return {doctype for doctype, module in candidates.items() if module in chosen_modules}


def scope_doctypes(
	candidates: Mapping[str, str],
	modules: Iterable[str],
	include: Iterable[str],
	exclude: Iterable[str],
) -> list[str]:
	return sorted(set(exclude_choices(candidates, modules, include)) - set(exclude))


def include_choices(candidates: Mapping[str, str], modules: Iterable[str]) -> list[str]:
	return sorted(candidates.keys() - module_doctypes(candidates, modules))


def exclude_choices(
	candidates: Mapping[str, str], modules: Iterable[str], include: Iterable[str]
) -> list[str]:
	return sorted(module_doctypes(candidates, modules) | (set(include) & candidates.keys()))


def kept_excludes(
	candidates: Mapping[str, str], modules: Iterable[str], include: Iterable[str], exclude: Iterable[str]
) -> list[str]:
	allowed = set(exclude_choices(candidates, modules, include))
	return [doctype for doctype in exclude if doctype in allowed]


def unusable_doctypes(candidates: Mapping[str, str], doctypes: Iterable[str]) -> list[str]:
	return sorted(set(doctypes) - candidates.keys())


def by_module(doctypes: Iterable[str], candidates: Mapping[str, str]) -> dict[str, list[str]]:
	modules = sorted({candidates[doctype] for doctype in doctypes})
	return {module: sorted(d for d in doctypes if candidates[d] == module) for module in modules}


def global_companies(rows: Iterable[Mapping]) -> frozenset[str]:
	return frozenset(
		row["for_value"] for row in rows if row.get("apply_to_all_doctypes") and not row.get("managed")
	)


def desired_pairs(
	grants: Iterable[tuple[str, str]],
	doctypes_by_scope: Mapping[str, Iterable[str]],
	already_global: frozenset[str],
) -> frozenset[tuple[str, str]]:
	return frozenset(
		(company, doctype)
		for company, scope in grants
		if company not in already_global
		for doctype in doctypes_by_scope.get(scope, ())
	)


def permission_delta(
	desired: frozenset[tuple[str, str]], rows: Iterable[Mapping]
) -> tuple[list[tuple[str, str]], list[str]]:
	rows = list(rows)
	present = {(row["for_value"], row.get("applicable_for")) for row in rows}
	to_add = sorted(desired - present)
	to_remove = sorted(
		row["name"]
		for row in rows
		if row.get("managed") and (row["for_value"], row.get("applicable_for")) not in desired
	)
	return to_add, to_remove


def duplicate_grants(grants: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
	grants = list(grants)
	return sorted({grant for grant in grants if grants.count(grant) > 1})


def access_status(enabled: bool, already_global: Iterable[str], desired: Iterable[tuple[str, str]]) -> str:
	if not enabled:
		return USER_DISABLED
	if not set(desired):
		return NO_EFFECT
	return NARROWS if not set(already_global) else IN_EFFECT


def grant_lines(grants: Iterable[tuple[str, str]]) -> str:
	return "\n".join(f"{company} · {scope}" for company, scope in grants if company and scope)
