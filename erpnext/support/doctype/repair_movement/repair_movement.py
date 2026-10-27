from frappe.model.document import Document


class RepairMovement(Document):
	def validate(self):
		if self.issue:
			from erpnext.support import repair_unit_movement

			return repair_unit_movement.validate(self)
		from erpnext.support.repair_custody import validate_movement

		validate_movement(self)

	def before_submit(self):
		if self.issue:
			from erpnext.support import repair_unit_movement

			return repair_unit_movement.before_submit(self)
		from erpnext.support.repair_custody import snapshot_movement

		snapshot_movement(self)

	def on_submit(self):
		if self.issue:
			from erpnext.support import repair_unit_movement

			return repair_unit_movement.on_submit(self)
		from erpnext.support.repair_custody import submit_movement

		submit_movement(self)

	def on_cancel(self):
		if self.issue:
			from erpnext.support import repair_unit_movement

			return repair_unit_movement.on_cancel(self)
		from erpnext.support.repair_custody import cancel_movement

		cancel_movement(self)

	def before_cancel(self):
		if self.issue:
			from erpnext.support import repair_unit_movement

			return repair_unit_movement.before_cancel(self)
		from erpnext.support.repair_custody import validate_cancellation

		validate_cancellation(self)
