import unittest

from erpnext.correspondence.imap_uids import FolderState, first_uid, new_uids, parse_fetch, parse_status


class TestImapUids(unittest.TestCase):
	def test_status_response_is_parsed(self):
		self.assertEqual(parse_status(b'"Banks" (UIDVALIDITY 1696 UIDNEXT 42)'), FolderState("1696", 42))

	def test_known_folder_continues_from_its_own_counter(self):
		self.assertEqual(first_uid("1696", "17", FolderState("1696", 42), 100), 17)

	def test_new_folder_starts_with_the_backlog(self):
		self.assertEqual(first_uid(None, None, FolderState("1696", 420), 100), 320)
		self.assertEqual(first_uid("", "", FolderState("1696", 42), 100), 1)

	def test_changed_uidvalidity_drops_the_counter(self):
		self.assertEqual(first_uid("1", "900", FolderState("2", 150), 100), 50)

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
