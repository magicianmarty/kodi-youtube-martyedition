# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    Just enough protobuf to talk to SABR.

    No schema compiler and no dependency: an add-on cannot pip install, and
    the wire format is small enough to write out. Messages are (field number,
    value) pairs and the caller says what each field means, which is the same
    thing generated code does with more ceremony.
"""

VARINT = 0
FIXED64 = 1
LENGTH = 2
FIXED32 = 5


def encode_varint(value):
    """Base 128, seven bits per byte, high bit means 'more to come'."""
    if value < 0:
        # Negative ints are transmitted as their unsigned 64-bit form.
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def decode_varint(data, pos=0):
    """Returns (value, new position)."""
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError('truncated varint')
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError('varint too long')


def zigzag(value):
    """sint32/sint64 encoding: small negatives stay small."""
    return (value << 1) ^ (value >> 63) if value < 0 else value << 1


def tag(field, wire_type):
    return encode_varint((field << 3) | wire_type)


def encode(fields):
    """
    Serialise [(field_number, value)] where value is an int, bytes, str, bool
    or a nested bytes message. Repeated fields are simply listed more than
    once, which is exactly how the wire format represents them.
    """
    out = bytearray()
    for field, value in fields:
        if value is None:
            continue
        if isinstance(value, bool):
            out += tag(field, VARINT) + encode_varint(1 if value else 0)
        elif isinstance(value, int):
            out += tag(field, VARINT) + encode_varint(value)
        else:
            if isinstance(value, str):
                value = value.encode('utf-8')
            out += tag(field, LENGTH) + encode_varint(len(value)) + value
    return bytes(out)


def decode(data):
    """
    Parse a message into {field_number: [values]}. Varints come back as ints,
    length-delimited fields as bytes; what those bytes mean is the caller's
    business, because the wire format does not say.
    """
    fields = {}
    pos = 0
    end = len(data)
    while pos < end:
        key, pos = decode_varint(data, pos)
        field, wire_type = key >> 3, key & 0x07
        if wire_type == VARINT:
            value, pos = decode_varint(data, pos)
        elif wire_type == LENGTH:
            length, pos = decode_varint(data, pos)
            if pos + length > end:
                raise ValueError('truncated length-delimited field')
            value = data[pos:pos + length]
            pos += length
        elif wire_type == FIXED64:
            value = data[pos:pos + 8]
            pos += 8
        elif wire_type == FIXED32:
            value = data[pos:pos + 4]
            pos += 4
        else:
            raise ValueError('unsupported wire type {0}'.format(wire_type))
        fields.setdefault(field, []).append(value)
    return fields


def first(fields, number, default=None):
    values = fields.get(number)
    return values[0] if values else default


def text(fields, number, default=''):
    value = first(fields, number)
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return default if value is None else value
