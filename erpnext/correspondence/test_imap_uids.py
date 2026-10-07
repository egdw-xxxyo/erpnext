import unittest
from datetime import date

from erpnext.correspondence.imap_uids import (
	FolderState,
	ReadPlan,
	imap_date,
	new_uids,
	parse_fetch,
	parse_status,
	progress_start,
	read_plan,
)


class TestImapUids(unittest.TestCase):
	def test_status_response_is_parsed(self):
		self.assertEqual(parse_status(b'"Banks" (UIDVALIDITY 1696 UIDNEXT 42)'), FolderState("1696", 42))

	def test_known_folder_continues_from_its_own_counter(self):
		self.assertEqual(read_plan("1696", "17", FolderState("1696", 42), None), ReadPlan("UID 17:*", 17))

	def test_new_folder_skips_the_mail_already_there(self):
		self.assertEqual(
			read_plan(None, None, FolderState("1696", 420), date(2026, 10, 1)), ReadPlan("UID 420:*", 420)
		)
		self.assertEqual(read_plan("", "", FolderState("1696", 42), None), ReadPlan("UID 42:*", 42))

	def test_changed_uidvalidity_rereads_since_the_day_before_the_last_check(self):
		self.assertEqual(
			read_plan("1", "900", FolderState("2", 150), date(2026, 10, 1)), ReadPlan("SINCE 30-Sep-2026", 1)
		)

	def test_changed_uidvalidity_without_a_last_check_starts_from_now(self):
		self.assertEqual(read_plan("1", "900", FolderState("2", 150), None), ReadPlan("UID 150:*", 150))

	def test_folder_without_uidnext_is_not_read(self):
		self.assertIsNone(read_plan(None, None, FolderState("2", 0), None))

	def test_imap_dates_use_english_months(self):
		self.assertEqual(imap_date(date(2026, 1, 5)), "05-Jan-2026")

	def test_progress_starts_at_the_first_found_mail_or_the_next_uid(self):
		self.assertEqual(progress_start(ReadPlan("SINCE 30-Sep-2026", 1), [7, 9], FolderState("2", 12)), 7)
		self.assertEqual(progress_start(ReadPlan("SINCE 30-Sep-2026", 1), [], FolderState("2", 12)), 12)
		self.assertEqual(progress_start(ReadPlan("UID 20:*", 20), [], FolderState("2", 12)), 20)

	def test_uids_below_the_start_are_dropped(self):
		self.assertEqual(new_uids(b"41", 42), [])
		self.assertEqual(new_uids(b"44 42 43", 42), [42, 43, 44])
		self.assertEqual(new_uids(None, 1), [])

	def test_batch_is_limited_to_the_oldest_uids(self):
		self.assertEqual(new_uids(b"5 3 4", 1, limit=2), [3, 4])

	def test_fetch_response_gives_message_and_seen_flag(self):
		raw = b"Subject: hi\r\n\r\nbody"
		self.assertEqual(parse_fetch([(b"1 (UID 7 FLAGS (\\Seen) BODY[] {20}", raw), b")"]), (raw, "SEEN"))
		self.assertEqual(parse_fetch([(b"1 (UID 7 BODY[] {20}", raw), b" FLAGS ())"]), (raw, "UNSEEN"))
		self.assertEqual(parse_fetch(None), (None, "UNSEEN"))
