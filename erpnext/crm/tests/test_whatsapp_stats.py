import datetime
import unittest

from erpnext.crm.whatsapp_stats import Schedule, conversation_turns, median, working_seconds

NINE, SIX = datetime.time(9, 0), datetime.time(18, 0)


def schedule(holidays=()):
	return Schedule(windows={day: [(NINE, SIX)] for day in range(5)}, holidays=set(holidays))


def dt(value):
	return datetime.datetime.fromisoformat(value)


class TestWorkingSeconds(unittest.TestCase):
	# 2026-09-25 is a Friday.

	def test_inside_one_window(self):
		self.assertEqual(working_seconds(dt("2026-09-25 10:00"), dt("2026-09-25 10:30"), schedule()), 1800)

	def test_evening_to_next_morning(self):
		# Thursday 17:30 → Friday 09:15: half an hour Thursday + 15 min Friday.
		self.assertEqual(working_seconds(dt("2026-09-24 17:30"), dt("2026-09-25 09:15"), schedule()), 45 * 60)

	def test_weekend_is_skipped(self):
		# Friday 17:00 → Monday 10:00: 1 h Friday + 1 h Monday.
		self.assertEqual(
			working_seconds(dt("2026-09-25 17:00"), dt("2026-09-28 10:00"), schedule()), 2 * 3600
		)

	def test_holiday_is_skipped(self):
		holiday = datetime.date(2026, 9, 28)
		# Friday 17:00 → Tuesday 10:00 with Monday off: 1 h Friday + 1 h Tuesday.
		self.assertEqual(
			working_seconds(dt("2026-09-25 17:00"), dt("2026-09-29 10:00"), schedule([holiday])), 2 * 3600
		)

	def test_outside_hours_only(self):
		self.assertEqual(working_seconds(dt("2026-09-26 10:00"), dt("2026-09-27 20:00"), schedule()), 0)

	def test_reversed_range(self):
		self.assertEqual(working_seconds(dt("2026-09-25 11:00"), dt("2026-09-25 10:00"), schedule()), 0)


def msg(kind, at, owner="Administrator", content_type="text"):
	return {"type": kind, "creation": dt(at), "owner": owner, "content_type": content_type}


class TestConversationTurns(unittest.TestCase):
	def test_turn_starts_at_first_unanswered_incoming(self):
		turns, pending = conversation_turns(
			[
				msg("Incoming", "2026-09-25 10:00"),
				msg("Incoming", "2026-09-25 10:05"),
				msg("Outgoing", "2026-09-25 10:20", owner="a@x"),
				msg("Outgoing", "2026-09-25 10:25", owner="b@x"),
			],
			schedule(),
		)
		self.assertEqual(len(turns), 1)
		self.assertEqual(turns[0]["seconds"], 20 * 60)
		self.assertEqual(turns[0]["user"], "a@x")
		self.assertIsNone(pending)

	def test_reactions_are_ignored(self):
		turns, pending = conversation_turns(
			[
				msg("Incoming", "2026-09-25 10:00"),
				msg("Outgoing", "2026-09-25 10:01", content_type="reaction"),
				msg("Incoming", "2026-09-25 10:02"),
			],
			schedule(),
		)
		self.assertEqual(turns, [])
		self.assertEqual(pending, {"since": dt("2026-09-25 10:00"), "count": 2})

	def test_outgoing_without_question_is_not_a_reply(self):
		turns, pending = conversation_turns(
			[msg("Outgoing", "2026-09-25 10:00"), msg("Incoming", "2026-09-25 11:00")], schedule()
		)
		self.assertEqual(turns, [])
		self.assertEqual(pending["count"], 1)


class TestMedian(unittest.TestCase):
	def test_median(self):
		self.assertIsNone(median([]))
		self.assertEqual(median([5, 1, 3]), 3)
		self.assertEqual(median([4, 1, 3, 2]), 2)
