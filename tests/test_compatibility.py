# -*- coding: utf-8 -*-
"""
What `kodion.compatibility` promises, pinned.

This module exists to paper over Python 2 and Kodi 18. Piers is neither, so
most of it is unreachable - but "unreachable" is a claim, and deleting two
hundred lines on a claim is how add-ons break in the field. These tests
describe the behaviour callers actually depend on, so the deletion has to
reproduce it rather than merely compile.
"""

import datetime
import unittest

from youtube_plugin.kodion import compatibility as compat


class TestExports(unittest.TestCase):
    def test_everything_it_advertises_exists(self):
        missing = [name for name in compat.__all__ if not hasattr(compat, name)]
        self.assertEqual([], missing)


class TestText(unittest.TestCase):
    def test_to_unicode_decodes_bytes_and_passes_text_through(self):
        self.assertEqual(u"café", compat.to_unicode(b"caf\xc3\xa9"))
        self.assertEqual(u"café", compat.to_unicode(u"café"))

    def test_to_unicode_survives_undecodable_bytes(self):
        self.assertEqual(u"ab", compat.to_unicode(b"a\xffb"))

    def test_to_str_stringifies_non_text(self):
        self.assertEqual("7", compat.to_str(7))
        self.assertEqual("None", compat.to_str(None))

    def test_entity_escape_covers_the_five_xml_entities(self):
        self.assertEqual(
            "&amp;&quot;&lt;&gt;&#x27;",
            compat.entity_escape("&\"<>'"),
        )

    def test_unescape_is_the_inverse_for_named_entities(self):
        self.assertEqual("a & b", compat.unescape("a &amp; b"))


class TestHash(unittest.TestCase):
    def test_generate_hash_is_md5_of_the_arguments_joined(self):
        import hashlib
        expected = hashlib.md5(b"ab1").hexdigest()
        self.assertEqual(expected, compat.generate_hash("a", "b", 1))

    def test_generate_hash_accepts_an_iterable_by_keyword(self):
        self.assertEqual(
            compat.generate_hash("a", "b"),
            compat.generate_hash(iter=["a", "b"]),
        )

    def test_generate_hash_is_stable_across_runs(self):
        self.assertEqual(
            "900150983cd24fb0d6963f7d28e17f72",
            compat.generate_hash("a", "b", "c"),
        )


class TestUrls(unittest.TestCase):
    def test_parse_qsl_keeps_order_and_decodes(self):
        self.assertEqual(
            [("a", "1"), ("b", "two words")],
            compat.parse_qsl("a=1&b=two+words"),
        )

    def test_parse_qs_groups_repeats(self):
        self.assertEqual({"a": ["1", "2"]}, compat.parse_qs("a=1&a=2"))

    def test_quote_leaves_slashes_alone_by_default(self):
        self.assertEqual("a/b%20c", compat.quote("a/b c"))

    def test_quote_plus_encodes_slashes_and_spaces(self):
        self.assertEqual("a%2Fb+c", compat.quote_plus("a/b c"))

    def test_unquote_round_trips(self):
        self.assertEqual("a/b c", compat.unquote(compat.quote("a/b c")))
        self.assertEqual("a/b c", compat.unquote_plus(compat.quote_plus("a/b c")))

    def test_urlencode_encodes_a_mapping(self):
        self.assertEqual("a=1&b=x+y", compat.urlencode({"a": 1, "b": "x y"}))

    def test_urlsplit_and_urlunsplit_round_trip(self):
        url = "https://example.com/a/b?c=1#d"
        self.assertEqual(url, compat.urlunsplit(compat.urlsplit(url)))

    def test_urljoin_resolves_relative(self):
        self.assertEqual(
            "https://example.com/a/c",
            compat.urljoin("https://example.com/a/b", "c"),
        )


class TestKodiFacing(unittest.TestCase):
    def test_datetime_infolabel_is_iso_without_microseconds(self):
        when = datetime.datetime(2026, 9, 2, 13, 45, 6, 123456)
        self.assertEqual("2026-09-02T13:45:06", compat.datetime_infolabel(when))

    def test_datetime_infolabel_drops_the_timezone(self):
        when = datetime.datetime(2026, 9, 2, 13, 45, 6,
                                 tzinfo=datetime.timezone.utc)
        self.assertEqual("2026-09-02T13:45:06", compat.datetime_infolabel(when))

    def test_available_cpu_count_is_a_positive_int(self):
        count = compat.available_cpu_count()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 1)


class TestTypes(unittest.TestCase):
    def test_range_type_matches_a_range_and_a_list(self):
        self.assertIsInstance(range(3), compat.range_type)
        self.assertIsInstance([1], compat.range_type)

    def test_string_type_is_str(self):
        self.assertIs(str, compat.string_type)

    def test_stringio_is_a_context_manager(self):
        with compat.StringIO() as handle:
            handle.write(u"x")
            self.assertEqual(u"x", handle.getvalue())

    def test_pickle_round_trips(self):
        self.assertEqual(
            {"a": [1, 2]},
            compat.pickle.loads(compat.pickle.dumps({"a": [1, 2]})),
        )
