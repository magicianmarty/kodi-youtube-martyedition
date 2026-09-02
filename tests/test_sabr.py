# -*- coding: utf-8 -*-
"""
The SABR protocol layers.

These are the parts that can be pinned without a network: the two varint
encodings, the UMP container, and the message field maps. The wire format is
not ours and cannot be looked up when it breaks, so it is described here
rather than discovered again.
"""

import unittest

from youtube_plugin.sabr import client as sabr
from youtube_plugin.sabr import messages as msg
from youtube_plugin.sabr import protobuf as pb
from youtube_plugin.sabr import ump


def media_header(sequence, is_init=False, start_range=0, itag=394):
    """
    A header shaped like the ones MediaHeader.decode produces.

    Built from the full field set on purpose: a fixture that omits fields the
    real decoder always supplies passes tests the production path fails.
    """
    return {
        'header_id': sequence,
        'video_id': 'test',
        'itag': itag,
        'lmt': 1,
        'start_range': start_range,
        'compression': 0,
        'is_init_seg': is_init,
        'sequence_number': sequence,
        'start_ms': 0,
        'duration_ms': 0,
        'content_length': 0,
        'format_id': None,
    }


class TestProtobuf(unittest.TestCase):
    def test_the_canonical_example(self):
        """Field 1 = 150 is protobuf's own worked example: 08 96 01."""
        self.assertEqual(b'\x08\x96\x01', pb.encode([(1, 150)]))

    def test_varint_round_trip(self):
        for value in (0, 1, 127, 128, 300, 2 ** 31, 2 ** 63 - 1):
            self.assertEqual(value, pb.decode_varint(pb.encode_varint(value))[0])

    def test_strings_are_utf8_length_delimited(self):
        self.assertEqual(b'\x12\x02hi', pb.encode([(2, 'hi')]))

    def test_repeated_fields_are_just_repeated(self):
        encoded = pb.encode([(1, 10), (1, 20), (1, 30)])
        self.assertEqual([10, 20, 30], pb.decode(encoded)[1])

    def test_none_is_omitted_not_encoded(self):
        self.assertEqual(b'', pb.encode([(1, None)]))

    def test_decode_ignores_unknown_fields(self):
        """Anything we do not model is data we do not need, not an error."""
        fields = pb.decode(pb.encode([(1, 5), (999, b'junk')]))
        self.assertEqual(5, pb.first(fields, 1))
        self.assertIn(999, fields)

    def test_truncated_input_is_rejected(self):
        with self.assertRaises(ValueError):
            pb.decode(b'\x12\x05ab')


class TestUmpVarint(unittest.TestCase):
    def test_the_documented_example(self):
        """0x80 0x41 is 4160 - the worked example from the format notes."""
        self.assertEqual(4160, ump.read_varint(bytes((0x80, 0x41)))[0])

    def test_leading_bits_give_the_length(self):
        self.assertEqual(1, ump.varint_size(0x42))
        self.assertEqual(2, ump.varint_size(0x80))
        self.assertEqual(3, ump.varint_size(0xC0))
        self.assertEqual(4, ump.varint_size(0xE0))
        self.assertEqual(5, ump.varint_size(0xF0))

    def test_round_trip_across_every_width(self):
        for value in (0, 1, 127, 128, 4160, 5000, 100000, 20000000, 4000000000):
            encoded = ump.write_varint(value)
            self.assertEqual(value, ump.read_varint(encoded)[0],
                             'failed for {0}'.format(value))

    def test_it_is_not_protobufs_varint(self):
        """Same job, different encoding - confusing them silently misreads."""
        self.assertNotEqual(ump.write_varint(300), pb.encode_varint(300))

    def test_incomplete_input_asks_for_more_rather_than_guessing(self):
        self.assertEqual((None, 0), ump.read_varint(b'\x80'))
        self.assertEqual((None, 0), ump.read_varint(b''))


class TestUmpReader(unittest.TestCase):
    @staticmethod
    def part(part_type, payload):
        return (ump.write_varint(part_type) + ump.write_varint(len(payload))
                + payload)

    def test_reads_consecutive_parts(self):
        reader = ump.Reader()
        reader.feed(self.part(20, b'header') + self.part(21, b'media'))
        self.assertEqual((20, b'header'), reader.read())
        self.assertEqual((21, b'media'), reader.read())
        self.assertIsNone(reader.read())

    def test_a_part_split_across_feeds_waits_for_the_rest(self):
        """
        Parts are not guaranteed to fit in one response, so a reader that
        returned half a part would hand corrupted media to the decoder.
        """
        whole = self.part(21, b'0123456789')
        reader = ump.Reader()
        reader.feed(whole[:6])
        self.assertIsNone(reader.read())
        reader.feed(whole[6:])
        self.assertEqual((21, b'0123456789'), reader.read())

    def test_pending_reports_what_is_held_back(self):
        reader = ump.Reader()
        reader.feed(self.part(21, b'abc')[:-1])
        self.assertIsNone(reader.read())
        self.assertTrue(reader.pending)

    def test_iterating_yields_only_complete_parts(self):
        reader = ump.Reader()
        reader.feed(self.part(20, b'a') + self.part(21, b'bb') + b'\x15')
        self.assertEqual([(20, b'a'), (21, b'bb')], list(reader))

    def test_unknown_part_types_are_named_not_dropped(self):
        self.assertEqual('MEDIA', ump.name_of(ump.MEDIA))
        self.assertEqual('PART_222', ump.name_of(222))


class TestMessages(unittest.TestCase):
    def test_format_id_round_trip(self):
        encoded = msg.FormatId.encode(313, 1788256282938590)
        decoded = msg.FormatId.decode(encoded)
        self.assertEqual(313, decoded['itag'])
        self.assertEqual(1788256282938590, decoded['last_modified'])

    def test_track_types_is_a_bitfield(self):
        """
        Named a bitfield and behaves like one: audio is bit 0, video bit 1.
        Sending 0 for "both" asks for no tracks at all, and the server
        answers with policy parts and no media whatsoever.
        """
        self.assertEqual(1, msg.ClientAbrState.TRACKS_AUDIO_ONLY)
        self.assertEqual(2, msg.ClientAbrState.TRACKS_VIDEO_ONLY)
        self.assertEqual(3, msg.ClientAbrState.TRACKS_AUDIO_AND_VIDEO)
        self.assertEqual(msg.ClientAbrState.TRACKS_AUDIO_AND_VIDEO,
                         msg.ClientAbrState.TRACKS_AUDIO_ONLY
                         | msg.ClientAbrState.TRACKS_VIDEO_ONLY)

    def test_media_header_decodes_the_fields_playback_needs(self):
        raw = pb.encode([
            (msg.MediaHeader.HEADER_ID, 3),
            (msg.MediaHeader.VIDEO_ID, 'kJQ89v9v5uM'),
            (msg.MediaHeader.ITAG, 394),
            (msg.MediaHeader.SEQUENCE_NUMBER, 7),
            (msg.MediaHeader.START_RANGE, 37919),
            (msg.MediaHeader.CONTENT_LENGTH, 52498),
        ])
        header = msg.MediaHeader.decode(raw)
        self.assertEqual(3, header['header_id'])
        self.assertEqual('kJQ89v9v5uM', header['video_id'])
        self.assertEqual(394, header['itag'])
        self.assertEqual(7, header['sequence_number'])
        self.assertFalse(header['is_init_seg'])

    def test_request_carries_the_config_and_context(self):
        state = msg.ClientAbrState.encode(0, 3)
        context = msg.StreamerContext.encode(
            msg.ClientInfo.encode(28, '1.65.10'), po_token=b'token')
        body = msg.VideoPlaybackAbrRequest.encode(
            state, b'config', context, player_time_ms=1234)
        fields = pb.decode(body)
        self.assertEqual(b'config',
                         pb.first(fields, msg.VideoPlaybackAbrRequest.USTREAMER_CONFIG))
        self.assertEqual(1234,
                         pb.first(fields, msg.VideoPlaybackAbrRequest.PLAYER_TIME_MS))


class TestFormatBookkeeping(unittest.TestCase):
    def make(self):
        fmt = sabr.Format(394, 1)
        fmt.total_duration_ms = 1750001
        fmt.end_segment_number = 175
        return fmt

    def test_segment_duration_comes_from_the_metadata(self):
        """1750001ms over 175 segments is ten seconds each."""
        self.assertEqual(10000, self.make().segment_duration_ms)

    def test_unknown_segmentation_is_zero_not_a_guess(self):
        self.assertEqual(0, sabr.Format(394, 1).segment_duration_ms)

    def test_contiguous_stops_at_the_first_gap(self):
        """
        Playback stops at a missing segment however much arrived after it,
        so a gap must not be reported as buffered - the server would treat
        that range as delivered and never resend it.
        """
        fmt = self.make()
        for sequence in (1, 2, 4, 5, 6):
            fmt.accept(media_header(sequence), b'x')
        self.assertEqual(5, len(fmt.segments))
        self.assertEqual(2, fmt.contiguous_segments)

    def test_the_init_segment_is_kept_apart_and_comes_first(self):
        fmt = self.make()
        fmt.accept(media_header(0, is_init=True), b'INIT')
        fmt.accept(media_header(1), b'one')
        self.assertEqual(b'INITone', fmt.data())
        self.assertEqual(1, len(fmt.segments))

    def test_a_repeated_segment_is_not_counted_twice(self):
        fmt = self.make()
        header = media_header(1)
        self.assertEqual(3, fmt.accept(header, b'abc'))
        self.assertEqual(0, fmt.accept(header, b'abc'))


class TestUstreamerConfig(unittest.TestCase):
    def test_base64url_without_padding_is_accepted(self):
        """The player response strips the padding; feeding that to b64decode
        raises rather than returning short data, so it has to be restored."""
        self.assertEqual(b'\xfb\xff', sabr.decode_ustreamer_config('-_8'))

    def test_bytes_pass_through(self):
        self.assertEqual(b'raw', sabr.decode_ustreamer_config(b'raw'))


class TestBufferedRangeReporting(unittest.TestCase):
    """
    What the session claims to hold decides what the server sends next, so
    these are the rules that were learned by getting them wrong.
    """

    def session(self):
        return sabr.Session('http://example/abr', b'config', b'client-info',
                            lambda url, body, headers: b'')

    def timed(self, itag, segments, duration_ms=10000):
        fmt = sabr.Format(itag, 1)
        fmt.total_duration_ms = duration_ms * 100
        fmt.end_segment_number = 100
        for sequence in range(1, segments + 1):
            fmt.accept(media_header(sequence), b'x')
        return fmt

    def test_a_track_without_a_known_timeline_claims_nothing(self):
        """
        Borrowing another track's segment length looks helpful and is not:
        the server reads the time rather than the segment count, decides the
        range is delivered, and skips a segment it never sent. That is how
        the video track ended up with a permanent hole in it.
        """
        session = self.session()
        untimed = sabr.Format(394, 1)
        untimed.accept(media_header(1), b'x')
        session.formats = [untimed]
        body = session._request_body()
        fields = pb.decode(body)
        self.assertNotIn(msg.VideoPlaybackAbrRequest.BUFFERED_RANGES, fields)

    def test_a_timed_track_reports_a_range(self):
        session = self.session()
        session.formats = [self.timed(251, 3)]
        fields = pb.decode(session._request_body())
        self.assertIn(msg.VideoPlaybackAbrRequest.BUFFERED_RANGES, fields)

    def test_the_range_starts_at_the_play_head_not_at_zero(self):
        """A player reports what it still holds, having discarded what it
        played; reporting from zero keeps the server's window full."""
        session = self.session()
        session.formats = [self.timed(251, 6)]
        session.player_time_ms = 30000
        fields = pb.decode(session._request_body())
        span = pb.decode(
            fields[msg.VideoPlaybackAbrRequest.BUFFERED_RANGES][0])
        self.assertEqual(30000, pb.first(span, msg.BufferedRange.START_TIME_MS))
        self.assertEqual(4, pb.first(span, msg.BufferedRange.START_SEGMENT_INDEX))
        self.assertEqual(6, pb.first(span, msg.BufferedRange.END_SEGMENT_INDEX))

    def test_the_play_head_is_not_derived_from_the_buffer(self):
        """
        Head and buffer end being equal says "I have played everything I
        have", which no playing player ever reports - and the server stops.
        """
        session = self.session()
        session.formats = [self.timed(251, 6)]
        self.assertEqual(60000, session.buffered_ms)
        self.assertEqual(0, session.player_time_ms)


class TestNextRequestPolicy(unittest.TestCase):
    def test_the_playback_cookie_is_carried_forward(self):
        """Continuity, not advice: a session that drops it looks new on
        every request."""
        raw = pb.encode([
            (msg.NextRequestPolicy.BACKOFF_TIME_MS, 15000),
            (msg.NextRequestPolicy.PLAYBACK_COOKIE, b'cookie-bytes'),
        ])
        policy = msg.NextRequestPolicy.decode(raw)
        self.assertEqual(b'cookie-bytes', policy['playback_cookie'])
        self.assertEqual(15000, policy['backoff_ms'])

    def test_a_policy_without_a_cookie_is_not_an_error(self):
        policy = msg.NextRequestPolicy.decode(pb.encode([(1, 15000)]))
        self.assertIsNone(policy['playback_cookie'])


class TestAdapter(unittest.TestCase):
    """Building a session from what the add-on already holds."""

    RESPONSE = {
        'streamingData': {
            'serverAbrStreamingUrl': 'https://example/videoplayback/abr',
            'adaptiveFormats': [
                {'itag': 394, 'lastModified': '111', 'mimeType': 'video/mp4'},
                {'itag': 251, 'lastModified': '222', 'mimeType': 'audio/webm',
                 'xtags': 'abc'},
            ],
        },
        'playerConfig': {'mediaCommonConfig': {
            'mediaUstreamerRequestConfig': {
                'videoPlaybackUstreamerConfig': 'Zm9v'}}},
    }

    CLIENT = {
        '_id': {'client_id': 28, 'client_version': '1.65.10'},
        'json': {'context': {'client': {
            'clientName': 'ANDROID_VR', 'clientVersion': '1.65.10',
            'osName': 'Android', 'osVersion': '14',
            'deviceMake': 'Oculus', 'deviceModel': 'Quest 3',
            'androidSdkVersion': '34'}}},
    }

    def adapter(self):
        from youtube_plugin.sabr import adapter
        return adapter

    def test_a_response_without_the_endpoint_is_not_streamable(self):
        self.assertFalse(self.adapter().supports_sabr({'streamingData': {}}))
        self.assertFalse(self.adapter().supports_sabr({}))

    def test_a_complete_response_is(self):
        self.assertTrue(self.adapter().supports_sabr(self.RESPONSE))

    def test_only_a_video_preference_is_named(self):
        """
        SABR picks the audio track itself. Naming a specific audio itag gets
        policy parts and no media, which is the failure this guards.
        """
        formats = self.adapter().pick_formats(self.RESPONSE, itag=394)
        self.assertEqual([394], [f.itag for f in formats])

    def test_audio_is_named_only_when_explicitly_asked_for(self):
        formats = self.adapter().pick_formats(self.RESPONSE, itag=394,
                                              audio_itag=251)
        self.assertEqual([394, 251], [f.itag for f in formats])
        self.assertTrue([f for f in formats if f.itag == 251][0].is_audio)

    def test_the_session_carries_the_add_ons_headers(self):
        """
        Authorization has to reach the SABR endpoint too. A player call made
        while signed in and a stream fetched anonymously are two different
        users as far as YouTube is concerned.
        """
        session = self.adapter().session_for(
            self.RESPONSE, self.CLIENT, lambda url, body, headers: b'',
            headers={'Authorization': 'Bearer xyz'}, itag=394)
        self.assertEqual('Bearer xyz', session.headers['Authorization'])

    def test_the_transport_receives_those_headers(self):
        seen = {}

        def transport(url, body, headers):
            seen.update(headers)
            return b''

        session = self.adapter().session_for(
            self.RESPONSE, self.CLIENT, transport,
            headers={'Authorization': 'Bearer xyz'}, itag=394)
        session.fetch()
        self.assertEqual('Bearer xyz', seen['Authorization'])
        self.assertEqual('application/x-protobuf', seen['Content-Type'])

    def test_the_ustreamer_config_is_decoded_from_base64(self):
        session = self.adapter().session_for(
            self.RESPONSE, self.CLIENT, lambda url, body, headers: b'',
            itag=394)
        self.assertEqual(b'foo', session.ustreamer_config)

    def test_an_unstreamable_response_yields_no_session(self):
        self.assertIsNone(self.adapter().session_for(
            {'streamingData': {}}, self.CLIENT, lambda u, b, h: b''))


class TestColdStart(unittest.TestCase):
    def test_the_first_request_omits_position_and_buffers(self):
        """
        "I have played nothing" and "I am at 0ms" are different statements,
        and the server treats them differently.
        """
        session = sabr.Session('http://example', b'cfg', b'ci',
                               lambda url, body, headers: b'')
        fields = pb.decode(session._request_body())
        self.assertNotIn(msg.VideoPlaybackAbrRequest.SELECTED_FORMAT_IDS, fields)
        self.assertNotIn(msg.VideoPlaybackAbrRequest.BUFFERED_RANGES, fields)

    def test_later_requests_name_the_selected_format(self):
        session = sabr.Session('http://example', b'cfg', b'ci',
                               lambda url, body, headers: b'')
        fmt = sabr.Format(394, 1)
        fmt.requested = True
        fmt.accept(media_header(1), b'x')
        session.formats = [fmt]
        session.rounds = 2
        fields = pb.decode(session._request_body())
        self.assertIn(msg.VideoPlaybackAbrRequest.SELECTED_FORMAT_IDS, fields)


class TestByteStream(unittest.TestCase):
    """
    Where SABR meets inputstream.adaptive: segments in, byte ranges out.
    """

    def stream(self, pieces, segment_ms=10000):
        from youtube_plugin.sabr import bytestream
        fmt = sabr.Format(394, 1)
        fmt.total_duration_ms = segment_ms * 10
        fmt.end_segment_number = 10
        fmt.offsets = dict(pieces)
        session = sabr.Session('http://example', b'cfg', b'ci',
                               lambda url, body, headers: b'')
        session.formats = [fmt]
        return bytestream.ByteStream(session, 394)

    def test_reads_within_one_piece(self):
        stream = self.stream({0: b'0123456789'})
        self.assertEqual(b'234', stream.read(2, 3))

    def test_reads_across_touching_pieces(self):
        """The init segment then segment one, as they arrive."""
        stream = self.stream({0: b'AAAA', 4: b'BBBB'})
        self.assertEqual(b'AABBB', stream.read(2, 5))

    def test_a_gap_is_not_silently_stitched(self):
        """
        Pieces that do not join must not be concatenated - that would hand
        the decoder bytes from the wrong offset and look like corruption
        rather than a missing segment.
        """
        stream = self.stream({0: b'AAAA', 8: b'CCCC'})
        self.assertEqual(4, stream.available(0))
        self.assertEqual(0, stream.available(4))

    def test_available_is_zero_before_anything_arrives(self):
        self.assertEqual(0, self.stream({}).available(0))

    def test_available_is_zero_past_the_end_of_a_piece(self):
        self.assertEqual(0, self.stream({0: b'AAAA'}).available(4))

    def test_offsets_map_to_playback_time(self):
        """
        A seek arrives as a byte offset and the server only understands
        seconds, so the two have to be related.
        """
        stream = self.stream({0: b'init', 4: b'one', 7: b'two', 10: b'three'})
        self.assertEqual(0, stream.position_ms(0))
        self.assertEqual(0, stream.position_ms(4))
        self.assertEqual(10000, stream.position_ms(7))
        self.assertEqual(20000, stream.position_ms(10))

    def test_reading_asks_the_session_for_what_is_missing(self):
        from youtube_plugin.sabr import bytestream
        calls = []

        fmt = sabr.Format(394, 1)
        fmt.total_duration_ms = 100000
        fmt.end_segment_number = 10
        fmt.offsets = {0: b'AAAA'}

        session = sabr.Session('http://example', b'cfg', b'ci',
                               lambda url, body, headers: b'')
        session.formats = [fmt]

        def fetch():
            calls.append(1)
            if len(calls) == 2:
                fmt.offsets[4] = b'BBBB'
            return 0

        session.fetch = fetch
        stream = bytestream.ByteStream(session, 394)
        self.assertEqual(b'AAAABBBB', stream.read(0, 8))
        self.assertTrue(calls)

    def test_a_read_at_the_end_returns_what_there_is(self):
        """Short only at the end, so a reader can tell it from "not yet"."""
        stream = self.stream({0: b'AAAA'})
        stream.max_rounds = 1
        self.assertEqual(b'AAAA', stream.read(0, 100))


class TestPlayHeadFromBytes(unittest.TestCase):
    """
    The play head has to be derivable from a byte offset alone.

    A track that never receives FormatInitializationMetadata has no segment
    length to count in. If that leaves the head at zero the server treats its
    opening grant as unconsumed and sends nothing further, and the track
    starves silently - which, when it is the video track and audio has a
    working timeline, is a frozen picture over continuing sound.
    """

    def stream(self, **kwargs):
        from youtube_plugin.sabr import bytestream
        fmt = sabr.Format(394, 1)
        fmt.offsets = {0: b'init', 4: b'one'}
        session = sabr.Session('http://example', b'cfg', b'ci',
                               lambda url, body, headers: b'')
        session.formats = [fmt]
        return bytestream.ByteStream(session, 394, **kwargs)

    def test_byte_offsets_map_to_time_without_any_segment_metadata(self):
        stream = self.stream(content_length=1000, duration_ms=100000)
        self.assertEqual(0, stream.position_ms(0))
        self.assertEqual(25000, stream.position_ms(250))
        self.assertEqual(50000, stream.position_ms(500))

    def test_the_head_never_runs_past_the_end(self):
        stream = self.stream(content_length=1000, duration_ms=100000)
        self.assertEqual(100000, stream.position_ms(5000))

    def test_without_size_or_duration_it_falls_back_to_segments(self):
        stream = self.stream()
        stream.session.formats[0].total_duration_ms = 100000
        stream.session.formats[0].end_segment_number = 10
        self.assertEqual(0, stream.position_ms(4))

    def test_a_track_with_no_timeline_of_its_own_borrows_the_sessions(self):
        """
        Video regularly gets no metadata while audio does; the segmentation
        is shared, so the video track can count in the audio track's units.
        """
        from youtube_plugin.sabr import bytestream
        video = sabr.Format(394, 1)
        video.offsets = {0: b'init', 4: b'one', 8: b'two'}
        audio = sabr.Format(251, 1)
        audio.total_duration_ms = 100000
        audio.end_segment_number = 10
        session = sabr.Session('http://example', b'cfg', b'ci',
                               lambda url, body, headers: b'')
        session.formats = [video, audio]
        stream = bytestream.ByteStream(session, 394)
        self.assertEqual(0, video.segment_duration_ms)
        self.assertEqual(10000, session.segment_duration_ms)
        self.assertEqual(10000, stream.position_ms(8))


class TestReadingBeforeAnythingArrives(unittest.TestCase):
    """
    The first read of a stream happens before a single segment exists, so
    that path has to be correct or SABR never serves at all - it throws, the
    proxy falls back, and playback quietly reverts to the 60s ceiling while
    looking like the bug it was meant to fix.
    """

    def stream(self, pieces=None):
        from youtube_plugin.sabr import bytestream
        fmt = sabr.Format(394, 1)
        fmt.offsets = dict(pieces or {})
        session = sabr.Session('http://example', b'cfg', b'ci',
                               lambda url, body, headers: b'')
        session.formats = [fmt]
        stream = bytestream.ByteStream(session, 394)
        stream.max_rounds = 0
        return stream

    def test_reading_an_empty_stream_returns_nothing(self):
        self.assertEqual(b'', self.stream().read(0, 100))

    def test_reading_before_the_first_piece_returns_nothing(self):
        """
        Not the last piece: a negative list index is legal Python and would
        read from the wrong end of the stream.
        """
        self.assertEqual(b'', self.stream({100: b'later'}).read(0, 10))

    def test_reading_from_the_first_piece_still_works(self):
        self.assertEqual(b'later', self.stream({100: b'later'}).read(100, 5))
