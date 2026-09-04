# -*- coding: utf-8 -*-
"""
Sponsor segment handling.

The network is stubbed out throughout. What matters here is what happens to
the answer: which segments survive, and whether a given playback position
lands in one - not whether the service is up.
"""

import json
import os
import sys
import unittest

from . import REPO_ROOT

sys.path.insert(0, os.path.join(REPO_ROOT, "resources", "lib",
                                "youtube_plugin", "kodion"))

import sponsorblock  # noqa: E402


class FakeResponse(object):
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload


class TestFetch(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._real = sponsorblock.urlopen

    def tearDown(self):
        sponsorblock.urlopen = self._real

    def _answer(self, payload):
        def fake(request, timeout=None):
            self.calls.append(request.full_url)
            return FakeResponse(payload)
        sponsorblock.urlopen = fake

    def test_private_lookup_never_sends_the_video_id(self):
        self._answer([{"videoID": "abcdefghijk",
                       "segments": [{"segment": [10.0, 40.0],
                                     "category": "sponsor"}]}])
        segments = sponsorblock.fetch("abcdefghijk")
        self.assertEqual([(10.0, 40.0, "sponsor")], segments)
        self.assertNotIn("abcdefghijk", self.calls[0])

    def test_private_lookup_ignores_other_videos_sharing_the_prefix(self):
        self._answer([
            {"videoID": "someoneelse", "segments": [{"segment": [0.0, 90.0],
                                                     "category": "sponsor"}]},
        ])
        self.assertEqual([], sponsorblock.fetch("abcdefghijk"))

    def test_direct_lookup_sends_the_video_id(self):
        self._answer([{"segment": [5.0, 25.0], "category": "selfpromo"}])
        segments = sponsorblock.fetch("abcdefghijk", private=False)
        self.assertEqual([(5.0, 25.0, "selfpromo")], segments)
        self.assertIn("abcdefghijk", self.calls[0])

    def test_very_short_segments_are_dropped(self):
        # Skipping two seconds is a stutter, not a saving.
        self._answer([{"segment": [10.0, 11.0], "category": "sponsor"},
                      {"segment": [20.0, 60.0], "category": "sponsor"}])
        self.assertEqual([(20.0, 60.0, "sponsor")],
                         sponsorblock.fetch("abcdefghijk", private=False))

    def test_malformed_segments_are_ignored(self):
        self._answer([{"segment": [10.0], "category": "sponsor"},
                      {"category": "sponsor"},
                      {"segment": [20.0, 60.0], "category": "sponsor"}])
        self.assertEqual([(20.0, 60.0, "sponsor")],
                         sponsorblock.fetch("abcdefghijk", private=False))

    def test_segments_come_back_in_order(self):
        self._answer([{"segment": [90.0, 120.0], "category": "sponsor"},
                      {"segment": [10.0, 40.0], "category": "interaction"}])
        segments = sponsorblock.fetch("abcdefghijk", private=False)
        self.assertEqual([10.0, 90.0], [s[0] for s in segments])

    def test_a_failure_is_simply_no_segments(self):
        # 404 is the normal answer for a video nobody has submitted, and a
        # video is not worth interrupting over a service being down either.
        def boom(request, timeout=None):
            raise IOError("404")
        sponsorblock.urlopen = boom
        self.assertEqual([], sponsorblock.fetch("abcdefghijk"))


class TestFind(unittest.TestCase):
    SEGMENTS = [(10.0, 40.0, "sponsor"), (90.0, 120.0, "selfpromo")]

    def test_inside_a_segment(self):
        self.assertEqual((10.0, 40.0, "sponsor"),
                         sponsorblock.find(self.SEGMENTS, 25.0))

    def test_between_segments(self):
        self.assertIsNone(sponsorblock.find(self.SEGMENTS, 60.0))

    def test_just_before_a_segment_still_counts(self):
        # Playback is sampled once a second, so the position has usually
        # passed the start by the time anything looks at it.
        self.assertEqual((10.0, 40.0, "sponsor"),
                         sponsorblock.find(self.SEGMENTS, 9.5))

    def test_the_end_of_a_segment_is_not_in_it(self):
        # Otherwise skipping to the end would land inside it again and loop.
        self.assertIsNone(sponsorblock.find(self.SEGMENTS, 40.0))

    def test_nothing_to_find(self):
        self.assertIsNone(sponsorblock.find([], 25.0))


if __name__ == "__main__":
    unittest.main()
