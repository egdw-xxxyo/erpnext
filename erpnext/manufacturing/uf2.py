"""UF2 images for boards that take firmware through a USB drive (RP2040 BOOTSEL).

A UF2 block can target any flash address, so a board's serial number is written by appending one
block that lands in a sector the firmware never touches. Plain firmware updates leave that sector
alone, which is why a reflashed board keeps its serial.

Pure functions, no database: the layout comes from a `Flashing Profile` and is passed in.
"""

import hashlib
import re
import struct

import frappe
from frappe import _

UF2_MAGIC0 = 0x0A324655
UF2_MAGIC1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID = 0x00002000
BLOCK_SIZE = 512
PAYLOAD_SIZE = 256


def sha256(data):
	return hashlib.sha256(data).hexdigest()


def read_blocks(data):
	"""Split UF2 bytes into `(flags, address, family, payload)` tuples, checking the framing."""
	if not data or len(data) % BLOCK_SIZE:
		frappe.throw(_("Not a UF2 file: its size is not a multiple of {0}").format(BLOCK_SIZE))

	blocks = []
	for offset in range(0, len(data), BLOCK_SIZE):
		chunk = data[offset : offset + BLOCK_SIZE]
		magic0, magic1, flags, address, size, _number, _total, family = struct.unpack_from("<8I", chunk)
		(magic_end,) = struct.unpack_from("<I", chunk, BLOCK_SIZE - 4)
		if (magic0, magic1, magic_end) != (UF2_MAGIC0, UF2_MAGIC1, UF2_MAGIC_END):
			frappe.throw(_("Not a UF2 file: bad block at offset {0}").format(offset))
		blocks.append((flags, address, family, chunk[32 : 32 + size]))
	return blocks


def _pack_block(flags, address, family, payload, number, total):
	body = payload.ljust(476, b"\x00")
	head = struct.pack("<8I", UF2_MAGIC0, UF2_MAGIC1, flags, address, len(payload), number, total, family)
	return head + body + struct.pack("<I", UF2_MAGIC_END)


def check_firmware(data, family_id, record_address):
	"""Throw unless `data` is a UF2 of this chip family that stays clear of the serial record."""
	blocks = read_blocks(data)
	families = {family for _flags, _address, family, _payload in blocks}
	if families != {family_id}:
		frappe.throw(
			_("The firmware is built for family {0}, the profile expects {1}").format(
				", ".join(f"0x{f:08X}" for f in sorted(families)), f"0x{family_id:08X}"
			)
		)

	top = max(address + len(payload) for _flags, address, _family, payload in blocks)
	if top > record_address:
		frappe.throw(
			_("The firmware reaches 0x{0}, overlapping the serial sector at 0x{1}").format(
				f"{top:08X}", f"{record_address:08X}"
			)
		)
	return {"blocks": len(blocks), "top": top}


def normalize_serial(serial, max_length, magic):
	serial = (serial or "").strip().upper()
	if not re.fullmatch(r"[A-Z0-9][A-Z0-9 .\-:/_+]{0,%d}" % (max_length - 1), serial):
		frappe.throw(
			_("Serial {0} cannot be written to the board: 1-{1} characters, A-Z 0-9 . - : / _ +").format(
				frappe.bold(serial), max_length
			)
		)
	if len(magic + serial.encode("ascii")) + 1 > PAYLOAD_SIZE:
		frappe.throw(_("Serial record is longer than {0} bytes").format(PAYLOAD_SIZE))
	return serial


def build_image(firmware, serial, family_id, record_address, magic, max_length):
	"""Firmware UF2 plus one block that writes `serial` at `record_address`.

	The gap between the end of the firmware and the record is padded with 0xFF pages, so the
	boot ROM writes one contiguous range. `firmware=None` builds a serial-only image for a board
	that already runs the firmware.
	"""
	serial = normalize_serial(serial, max_length, magic)
	payload = (magic + serial.encode("ascii") + b"\x00").ljust(PAYLOAD_SIZE, b"\xff")

	blocks = []
	if firmware is not None:
		check_firmware(firmware, family_id, record_address)
		blocks = read_blocks(firmware)
		blocks.sort(key=lambda block: block[1])
		top = max(address + len(chunk) for _flags, address, _family, chunk in blocks)
		start = (top + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE * PAYLOAD_SIZE
		blocks += [
			(UF2_FLAG_FAMILY_ID, address, family_id, b"\xff" * PAYLOAD_SIZE)
			for address in range(start, record_address, PAYLOAD_SIZE)
		]
	blocks.append((UF2_FLAG_FAMILY_ID, record_address, family_id, payload))

	total = len(blocks)
	return b"".join(
		_pack_block(flags, address, family, chunk, number, total)
		for number, (flags, address, family, chunk) in enumerate(blocks)
	)
