# -*- coding: utf-8 -*-
"""

    Copyright (C) 2023-2025 plugin.video.youtube

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.
"""

__all__ = (
    'BaseHTTPRequestHandler',
    'StringIO',
    'TCPServer',
    'ThreadingMixIn',
    'available_cpu_count',
    'datetime_infolabel',
    'entity_escape',
    'generate_hash',
    'parse_qs',
    'parse_qsl',
    'pickle',
    'quote',
    'quote_plus',
    'range_type',
    'string_type',
    'to_str',
    'to_unicode',
    'unescape',
    'unquote',
    'unquote_plus',
    'urlencode',
    'urljoin',
    'urlsplit',
    'urlunsplit',
    'xbmc',
    'xbmcaddon',
    'xbmcgui',
    'xbmcplugin',
    'xbmcvfs',
)

import _pickle as pickle
from hashlib import md5
from html import unescape
from http.server import BaseHTTPRequestHandler
from io import StringIO
from os import process_cpu_count
from socketserver import TCPServer, ThreadingMixIn
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote,
    quote_plus,
    unquote,
    unquote_plus,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs


range_type = (range, list)

string_type = str
to_str = str


def to_unicode(text):
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='ignore')
    return text


def entity_escape(text,
                  entities=str.maketrans({
                      '&': '&amp;',
                      '"': '&quot;',
                      '<': '&lt;',
                      '>': '&gt;',
                      '\'': '&#x27;',
                  })):
    return text.translate(entities)


def generate_hash(*args, **kwargs):
    return md5(''.join(
        map(str, args or kwargs.get('iter'))
    ).encode('utf-8')).hexdigest()


SAFE_CHARS = frozenset(
    b'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    b'abcdefghijklmnopqrstuvwxyz'
    b'0123456789'
    b'_.-~'
    b'/'  # safe character by default
)
reserved = {
    chr(ordinal): '%%%x' % ordinal
    for ordinal in range(0, 128)
    if ordinal not in SAFE_CHARS
}
reserved_plus = reserved.copy()
reserved_plus.update((
    ('/', '%2f'),
    (' ', '+'),
))
reserved = str.maketrans(reserved)
reserved_plus = str.maketrans(reserved_plus)
non_ascii = str.maketrans({
    chr(ordinal): '%%%x' % ordinal
    for ordinal in range(128, 256)
})


def datetime_infolabel(datetime_obj, *_args, **_kwargs):
    return datetime_obj.replace(microsecond=0, tzinfo=None).isoformat()


def available_cpu_count():
    return process_cpu_count() or 1
