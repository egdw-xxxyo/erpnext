import hashlib
import unicodedata

from frappe.model.document import Document


def normalize_alias(value):
	return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def alias_key(supplier, item_name, part_no):
	value = "\x00".join((supplier, normalize_alias(item_name), normalize_alias(part_no)))
	return hashlib.sha256(value.encode()).hexdigest()


class SupplierItemAlias(Document):
	def autoname(self):
		self.name = alias_key(self.supplier, self.supplier_item_name, self.supplier_part_no)
