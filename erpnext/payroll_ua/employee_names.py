NAME_PARTS = ("last_name", "first_name", "middle_name")


def get_full_name(employee: dict) -> str:
	parts = filter(None, (employee.get(part) for part in NAME_PARTS))
	return " ".join(parts) or employee.get("employee_name") or ""


def order_by_full_name(query, table):
	return query.orderby(*(table[part] for part in NAME_PARTS))
