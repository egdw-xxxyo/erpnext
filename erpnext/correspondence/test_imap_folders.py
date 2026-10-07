import unittest

from erpnext.correspondence.imap_folders import (
	ALL_FOLDERS,
	GMAIL_ALL_MAIL,
	MANUAL,
	decode_modified_utf7,
	parse_list_response,
	select_folders,
)

UKR_NET_LIST = [
	b'(\\HasNoChildren) "/" INBOX',
	b'(\\HasNoChildren \\Sent) "/" "&BB0EMAQ0BFYEQQQ7BDAEPQRW-"',
	b'(\\HasNoChildren) "/" "&BCcENQRABD0ENQRCBDoEOA-"',
	b'(\\HasNoChildren) "/" Spam',
	b'(\\HasNoChildren) "/" Trash',
	b'(\\HasNoChildren) "/" "&BBEEMAQ9BDoEOA-"',
	b'(\\HasChildren) "/" "&BB8EPgRBBEIEMARHBDAEOwRMBD0EOAQ6BDg-"',
	b'(\\HasNoChildren) "/" "&BB8EPgRBBEIEMARHBDAEOwRMBD0EOAQ6BDg-/DHL &- Co"',
]

UKR_NET_LIVE_LIST = [
	b'(\\Inbox) "/" Inbox',
	b'() "/" "&BBoEMARBBEIEPgQ8-"',
	b'(\\Sent) "/" Sent',
	b'(\\Drafts) "/" Drafts',
	b'(\\Spam) "/" Quarantine',
	b'(\\Trash) "/" Trash',
]

GMAIL_LIST = [
	b'(\\HasNoChildren) "/" "INBOX"',
	b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
	b'(\\All \\HasNoChildren) "/" "[Gmail]/&BBIEQQRP- &BD8EPgRHBEIEMA-"',
	b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
	b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
	b'(\\HasNoChildren \\Important) "/" "[Gmail]/Important"',
	b'(\\HasNoChildren) "/" "Banks"',
]


class TestModifiedUtf7(unittest.TestCase):
	def test_decodes_cyrillic_and_ampersand(self):
		self.assertEqual(decode_modified_utf7("&BB0EMAQ0BFYEQQQ7BDAEPQRW-"), "Надіслані")
		self.assertEqual(decode_modified_utf7("[Gmail]/&BBIEQQRP- &BD8EPgRHBEIEMA-"), "[Gmail]/Вся почта")
		self.assertEqual(decode_modified_utf7("A &- B"), "A & B")
		self.assertEqual(decode_modified_utf7("INBOX"), "INBOX")


class TestParseList(unittest.TestCase):
	def test_reads_flags_delimiter_and_name(self):
		folder = parse_list_response([b'(\\HasNoChildren \\Sent) "/" "Sent Items"'])[0]
		self.assertEqual(folder.name, "Sent Items")
		self.assertEqual(folder.delimiter, "/")
		self.assertEqual(folder.flags, frozenset({"\\hasnochildren", "\\sent"}))

	def test_reads_literal_names_and_skips_garbage(self):
		folders = parse_list_response([(b'(\\HasNoChildren) "/" {7}', b"Reports"), None, b"garbage"])
		self.assertEqual([folder.name for folder in folders], ["Reports"])


class TestSelectFolders(unittest.TestCase):
	def test_all_folders_skips_system_ones_by_flag_and_by_name(self):
		self.assertEqual(
			select_folders(parse_list_response(UKR_NET_LIST), ALL_FOLDERS),
			[
				"INBOX",
				"&BBEEMAQ9BDoEOA-",
				"&BB8EPgRBBEIEMARHBDAEOwRMBD0EOAQ6BDg-",
				"&BB8EPgRBBEIEMARHBDAEOwRMBD0EOAQ6BDg-/DHL &- Co",
			],
		)

	def test_ukr_net_inbox_comes_first_and_spam_flag_is_skipped(self):
		self.assertEqual(
			select_folders(parse_list_response(UKR_NET_LIVE_LIST), ALL_FOLDERS),
			["Inbox", "&BBoEMARBBEIEPgQ8-"],
		)

	def test_gmail_reads_only_all_mail_whatever_its_language(self):
		self.assertEqual(
			select_folders(parse_list_response(GMAIL_LIST), GMAIL_ALL_MAIL),
			["[Gmail]/&BBIEQQRP- &BD8EPgRHBEIEMA-"],
		)

	def test_all_folders_on_gmail_skips_virtual_and_parent_folders(self):
		self.assertEqual(select_folders(parse_list_response(GMAIL_LIST), ALL_FOLDERS), ["INBOX", "Banks"])

	def test_manual_selects_nothing(self):
		self.assertEqual(select_folders(parse_list_response(UKR_NET_LIST), MANUAL), [])
