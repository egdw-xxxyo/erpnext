from frappe.query_builder.functions import Coalesce, Concat_ws, NullIf

NAME_PARTS = ("last_name", "first_name", "middle_name")


def get_full_name(employee: dict) -> str:
	parts = filter(None, (employee.get(part) for part in NAME_PARTS))
	return " ".join(parts) or employee.get("employee_name") or ""


def full_name_column(table):
	parts = (NullIf(table[part], "") for part in NAME_PARTS)
	return Coalesce(NullIf(Concat_ws(" ", *parts), ""), table.employee_name)
