# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    The UMP container that SABR responses arrive in.

    A response is a flat sequence of parts, each one a variable-length type,
    a variable-length size, then that many bytes. The catch is that a part is
    not guaranteed to fit in the response that started it, so this is written
    as a streaming reader: feed it whatever arrived and take out the parts
    that are complete.

    Note the varint here is *not* protobuf's. The leading bits of the first
    byte give the total length, and the remaining bits of that byte are the
    low bits of the value.
"""

# Part types, from the reverse-engineered format description.
ONESIE_HEADER = 10
ONESIE_DATA = 11
MEDIA_HEADER = 20
MEDIA = 21
MEDIA_END = 22
LIVE_METADATA = 31
FORMAT_INITIALIZATION_METADATA = 42
NEXT_REQUEST_POLICY = 35
SABR_REDIRECT = 43
SABR_ERROR = 44
SABR_SEEK = 45
RELOAD_PLAYER_RESPONSE = 46
PLAYBACK_START_POLICY = 47
STREAM_PROTECTION_STATUS = 58
SABR_CONTEXT_UPDATE = 57
SNACKBAR_MESSAGE = 66

NAMES = {
    ONESIE_HEADER: 'ONESIE_HEADER',
    ONESIE_DATA: 'ONESIE_DATA',
    MEDIA_HEADER: 'MEDIA_HEADER',
    MEDIA: 'MEDIA',
    MEDIA_END: 'MEDIA_END',
    LIVE_METADATA: 'LIVE_METADATA',
    NEXT_REQUEST_POLICY: 'NEXT_REQUEST_POLICY',
    FORMAT_INITIALIZATION_METADATA: 'FORMAT_INITIALIZATION_METADATA',
    SABR_REDIRECT: 'SABR_REDIRECT',
    SABR_ERROR: 'SABR_ERROR',
    SABR_SEEK: 'SABR_SEEK',
    RELOAD_PLAYER_RESPONSE: 'RELOAD_PLAYER_RESPONSE',
    PLAYBACK_START_POLICY: 'PLAYBACK_START_POLICY',
    SABR_CONTEXT_UPDATE: 'SABR_CONTEXT_UPDATE',
    STREAM_PROTECTION_STATUS: 'STREAM_PROTECTION_STATUS',
    SNACKBAR_MESSAGE: 'SNACKBAR_MESSAGE',
}


def name_of(part_type):
    return NAMES.get(part_type, 'PART_{0}'.format(part_type))


def varint_size(first_byte):
    """How many bytes this varint occupies, from its first byte alone."""
    if first_byte < 0x80:
        return 1
    if first_byte < 0xC0:
        return 2
    if first_byte < 0xE0:
        return 3
    if first_byte < 0xF0:
        return 4
    return 5


def read_varint(data, pos=0):
    """
    Returns (value, new position), or (None, pos) when more bytes are needed.

    The first byte carries both the length and the low bits of the value -
    except in the five byte form, where its bits are ignored entirely and the
    value is a plain little-endian uint32.
    """
    if pos >= len(data):
        return None, pos
    first_byte = data[pos]
    size = varint_size(first_byte)
    if pos + size > len(data):
        return None, pos
    if size == 1:
        return first_byte, pos + 1
    if size == 5:
        return int.from_bytes(data[pos + 1:pos + 5], 'little'), pos + 5
    bits = 8 - size
    value = first_byte & ((1 << bits) - 1)
    for index in range(1, size):
        value |= data[pos + index] << (bits + 8 * (index - 1))
    return value, pos + size


def write_varint(value):
    """The inverse, which only the tests need - YouTube never reads ours."""
    if value < 0:
        raise ValueError('varint cannot be negative')
    if value < 0x80:
        return bytes((value,))
    for size in (2, 3, 4):
        bits = 8 - size
        if value < (1 << (bits + 8 * (size - 1))):
            prefix = (0xFF << (bits + 1)) & 0xFF
            out = bytearray((prefix | (value & ((1 << bits) - 1)),))
            remainder = value >> bits
            for _ in range(size - 1):
                out.append(remainder & 0xFF)
                remainder >>= 8
            return bytes(out)
    if value > 0xFFFFFFFF:
        raise ValueError('varint too large')
    return b'\xf0' + value.to_bytes(4, 'little')


class Reader(object):
    """
    Accumulates bytes and hands back whole parts.

    Kept deliberately dumb: it knows nothing about what any part means, so
    the protocol logic upstairs can be tested against recorded bytes.
    """

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data):
        if data:
            self._buffer += data

    def __iter__(self):
        return self

    def __next__(self):
        part = self.read()
        if part is None:
            raise StopIteration
        return part

    next = __next__

    def read(self):
        """The next complete (type, payload), or None if it has not all arrived."""
        part_type, pos = read_varint(self._buffer, 0)
        if part_type is None:
            return None
        size, pos = read_varint(self._buffer, pos)
        if size is None:
            return None
        if len(self._buffer) - pos < size:
            return None
        payload = bytes(self._buffer[pos:pos + size])
        del self._buffer[:pos + size]
        return part_type, payload

    @property
    def pending(self):
        """Bytes held back waiting for the rest of a part."""
        return len(self._buffer)
