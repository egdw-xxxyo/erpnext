from types import SimpleNamespace
from unittest import TestCase

from erpnext.support.service_repair import aggregate_status


class TestRepairProgress(TestCase):
	def test_waiting_unit_prevents_ready_and_closed(self):
		for finished in ("Ready for Dispatch", "Dispatched", "Delivered", "Disposed"):
			with self.subTest(finished=finished):
				rows = [SimpleNamespace(status=finished), SimpleNamespace(status="Awaiting Receipt")]
				self.assertNotIn(aggregate_status(rows), {"Ready for Dispatch", "Dispatched", "Closed"})

	def test_partial_dispatch_and_disposal(self):
		def state(*statuses):
			return aggregate_status([SimpleNamespace(status=s) for s in statuses])

		self.assertEqual(state("Ready for Dispatch", "Dispatched"), "Ready for Dispatch")
		self.assertEqual(state("Dispatched", "Disposed"), "Dispatched")
		self.assertEqual(state("Delivered", "Disposed"), "Closed")
		self.assertEqual(state("Received", "Waiting for Parts"), "In Repair")
