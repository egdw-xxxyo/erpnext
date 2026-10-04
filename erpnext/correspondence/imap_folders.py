import base64
import re
from collections.abc import Iterable
from typing import NamedTuple

LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delimiter>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$')
SHIFTED = re.compile(r"&([^-]*)-")

UNSELECTABLE = frozenset({"\\noselect", "\\nonexistent"})
EXCLUDED_SPECIAL_USE = frozenset(
	{"\\junk", "\\spam", "\\sent", "\\drafts", "\\trash", "\\all", "\\flagged", "\\important"}
)
EXCLUDED_NAMES = frozenset(
	{
		"spam",
		"junk",
		"junk e-mail",
		"bulk mail",
		"sent",
		"sent items",
		"sent mail",
		"sent messages",
		"drafts",
		"draft",
		"trash",
		"deleted",
		"deleted items",
		"deleted messages",
		"bin",
		"спам",
		"надіслані",
		"відправлені",
		"отправленные",
		"чернетки",
		"черновики",
		"видалені",
		"удаленные",
		"удалённые",
		"кошик",
		"корзина",
	}
)

ALL_FOLDERS = "All Folders"
GMAIL_ALL_MAIL = "Gmail All Mail"
MANUAL = "Manual"


class Folder(NamedTuple):
	name: str
	flags: frozenset[str]
	delimiter: str | None


def decode_modified_utf7(name: str) -> str:
	def decode(match: re.Match) -> str:
		chunk = match.group(1)
		if not chunk:
			return "&"
		padded = chunk.replace(",", "/") + "=" * (-len(chunk) % 4)
		return base64.b64decode(padded).decode("utf-16-be")

	return SHIFTED.sub(decode, name)


def unquote(value: bytes) -> str:
	text = value.decode("utf-8", errors="replace")
	if len(text) >= 2 and text[0] == text[-1] == '"':
		return re.sub(r"\\(.)", r"\1", text[1:-1])
	return text


def parse_list_entry(entry: bytes | tuple) -> Folder | None:
	line, literal = (entry[0], entry[1]) if isinstance(entry, tuple) else (entry, None)
	match = LIST_LINE.match(line.strip())
	if not match:
		return None
	delimiter = match.group("delimiter")
	return Folder(
		name=literal.decode("utf-8", errors="replace")
		if literal is not None
		else unquote(match.group("name")),
		flags=frozenset(flag.lower() for flag in match.group("flags").decode().split()),
		delimiter=None if delimiter == b"NIL" else unquote(delimiter),
	)


def parse_list_response(entries: Iterable[bytes | tuple | None]) -> list[Folder]:
	folders = (parse_list_entry(entry) for entry in entries if entry)
	return [folder for folder in folders if folder]


def display_name(folder: Folder) -> str:
	decoded = decode_modified_utf7(folder.name)
	return decoded.rsplit(folder.delimiter, 1)[-1] if folder.delimiter else decoded


def folder_key(name: str) -> str:
	return "INBOX" if name.upper() == "INBOX" else name


def is_user_folder(folder: Folder) -> bool:
	return (
		not folder.flags & (UNSELECTABLE | EXCLUDED_SPECIAL_USE)
		and display_name(folder).strip().lower() not in EXCLUDED_NAMES
	)


def select_folders(folders: Iterable[Folder], mode: str) -> list[str]:
	selectable = [folder for folder in folders if not folder.flags & UNSELECTABLE]
	if mode == GMAIL_ALL_MAIL:
		return [folder.name for folder in selectable if "\\all" in folder.flags]
	if mode == ALL_FOLDERS:
		chosen = [folder.name for folder in selectable if is_user_folder(folder)]
		return sorted(chosen, key=lambda name: folder_key(name) != "INBOX")
	return []
