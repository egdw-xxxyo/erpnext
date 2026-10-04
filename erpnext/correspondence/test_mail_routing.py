import unittest

from erpnext.correspondence.mail_routing import (
	dedupe_key,
	matches,
	parse_patterns,
	plan_copies,
	route,
)

RULES = (
	{"name": "R1", "email_account": None, "patterns": ("@pumb.ua", "@fuib.com"), "recipients": ("ФІН",)},
	{"name": "R2", "email_account": None, "patterns": ("@court.gov.ua",), "recipients": ("ФІН", "КАД")},
	{"name": "R3", "email_account": None, "patterns": ("court.gov.ua",), "recipients": ("КАД",)},
	{"name": "R4", "email_account": "Gmail Box", "patterns": ("@dhl.com",), "recipients": ("ОД",)},
)


class TestParsePatterns(unittest.TestCase):
	def test_splits_on_spaces_commas_and_new_lines(self):
		self.assertEqual(
			parse_patterns(" @PUMB.ua, @fuib.com;\ninfo@pumb-pro-business.com.ua  "),
			("@pumb.ua", "@fuib.com", "info@pumb-pro-business.com.ua"),
		)

	def test_drops_duplicates_and_empty_input(self):
		self.assertEqual(parse_patterns("@a.ua @A.ua"), ("@a.ua",))
		self.assertEqual(parse_patterns(None), ())
		self.assertEqual(parse_patterns("  \n "), ())


class TestMatches(unittest.TestCase):
	def test_contains_ignoring_case(self):
		self.assertTrue(matches(("@pumb.ua",), "Manager@PUMB.ua"))
		self.assertFalse(matches(("@pumb.ua",), "manager@pumb-ua.com"))

	def test_empty_address_never_matches(self):
		self.assertFalse(matches(("",), ""))
		self.assertFalse(matches(("@a.ua",), None))


class TestRoute(unittest.TestCase):
	def test_unknown_sender_routes_nowhere(self):
		self.assertEqual(route(RULES, "someone@example.com", "Kalheon"), {})

	def test_one_sender_several_rules_gives_one_entry_per_recipient(self):
		self.assertEqual(
			route(RULES, "judge@court.gov.ua", "Kalheon"),
			{"ФІН": ("R2",), "КАД": ("R2", "R3")},
		)

	def test_rule_bound_to_another_mailbox_is_ignored(self):
		self.assertEqual(route(RULES, "x@dhl.com", "Kalheon"), {})
		self.assertEqual(route(RULES, "x@dhl.com", "Gmail Box"), {"ОД": ("R4",)})


class TestPlanCopies(unittest.TestCase):
	def test_recipients_sharing_an_email_get_one_copy(self):
		copies = plan_copies(
			{"ФІН": ("R1",), "КАД": ("R2",)},
			{
				"ФІН": {"email": "boss@kalheon.ua", "enabled": 1},
				"КАД": {"email": "Boss@Kalheon.ua ", "enabled": 1},
			},
		)
		self.assertEqual(
			copies, [{"recipient": "ФІН", "email": "boss@kalheon.ua", "rules": ("R1", "R2"), "skip": None}]
		)

	def test_unusable_recipients_are_kept_as_skipped(self):
		copies = plan_copies(
			{"ФІН": ("R1",), "КАД": ("R2",), "ОД": ("R3",)},
			{"ФІН": {"email": None, "enabled": 1}, "КАД": {"email": "k@kalheon.ua", "enabled": 0}},
		)
		self.assertEqual(
			[(copy["recipient"], copy["skip"]) for copy in copies],
			[
				("ФІН", "Recipient has no email"),
				("КАД", "Recipient is disabled"),
				("ОД", "Recipient not found"),
			],
		)


class TestDedupeKey(unittest.TestCase):
	def test_same_message_and_target_give_the_same_key_across_mailboxes(self):
		self.assertEqual(dedupe_key("abc@x", "COMM-1", "a@b.ua"), dedupe_key("ABC@x", "COMM-2", "A@b.ua"))

	def test_falls_back_to_communication_without_message_id(self):
		self.assertNotEqual(dedupe_key(None, "COMM-1", "a@b.ua"), dedupe_key(None, "COMM-2", "a@b.ua"))
