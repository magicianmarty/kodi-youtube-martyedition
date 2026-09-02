# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    A SABR session.

    The shape of the protocol: POST a VideoPlaybackAbrRequest describing where
    the play head is and what is already buffered, read back a UMP stream of
    media for the formats asked for, then ask again from the new position.
    The server decides how much to send; the client only says what it wants
    and what it already has.

    Deliberately free of Kodi imports so the whole thing can be exercised
    against recorded responses.
"""

from base64 import urlsafe_b64decode

from . import messages as msg
from . import ump

# The server decides chunk sizes, but a request that asks for nothing new
# would spin, so a session that makes no progress this many times gives up.
MAX_IDLE_ROUNDS = 3

# Track type bitfield values, from ClientAbrState.
AUDIO_AND_VIDEO = msg.ClientAbrState.TRACKS_AUDIO_AND_VIDEO
AUDIO_ONLY = msg.ClientAbrState.TRACKS_AUDIO_ONLY
VIDEO_ONLY = msg.ClientAbrState.TRACKS_VIDEO_ONLY


class SabrError(Exception):
    pass


def decode_ustreamer_config(value):
    """The player response carries it base64url encoded, with padding stripped."""
    if isinstance(value, bytes):
        return value
    padding = '=' * (-len(value) % 4)
    return urlsafe_b64decode(value + padding)


class Format(object):
    """One selected stream, and what has been received for it so far."""

    def __init__(self, itag, last_modified, xtags=None, is_audio=False):
        self.itag = int(itag)
        self.last_modified = int(last_modified or 0)
        self.xtags = xtags or ''
        self.is_audio = bool(is_audio)
        # Whether we asked for this one, as opposed to the server sending it.
        self.requested = False
        self.mime_type = ''
        self.total_duration_ms = 0
        self.end_segment_number = 0
        # The init segment carries no sequence number and belongs at the
        # front of the stream regardless of what arrives later.
        self.init_segment = b''
        # Segments seen, keyed by sequence number, so a repeat is free.
        self.segments = {}
        self.buffered_ms = 0
        self.last_segment = -1

    @property
    def format_id(self):
        return msg.FormatId.encode(self.itag, self.last_modified, self.xtags)

    @property
    def contiguous_segments(self):
        """
        How many segments are available from the start with no gap.

        A missing segment is the end of what can be played, whatever arrived
        after it - so this, not the count, is what the buffered range should
        report. Claiming a gap as buffered makes the server believe that part
        is already delivered and it will never resend it.
        """
        sequence = 1
        while sequence in self.segments:
            sequence += 1
        return sequence - 1

    @property
    def segment_duration_ms(self):
        """
        Segments are a fixed length the server never states directly. It does
        say how long the whole thing is and how many segments that is, and
        the division comes out exact - 1750001ms over 175 segments is ten
        seconds a segment.
        """
        if self.end_segment_number and self.total_duration_ms:
            return self.total_duration_ms // self.end_segment_number
        return 0

    def accept(self, header, payload):
        """
        Commit one finished segment.

        A segment arrives as a MEDIA_HEADER followed by however many MEDIA
        parts the server felt like splitting it into, so this is only called
        once the run has been reassembled.
        """
        if header['is_init_seg']:
            if self.init_segment:
                return 0
            self.init_segment = payload
            return len(payload)

        sequence = header['sequence_number']
        if sequence in self.segments:
            return 0
        self.segments[sequence] = payload
        self.last_segment = max(self.last_segment, sequence)
        if header['duration_ms']:
            self.buffered_ms = max(self.buffered_ms,
                                   header['start_ms'] + header['duration_ms'])
        else:
            # No timings on the header; segments are uniform, so the count is
            # the clock.
            per_segment = self.segment_duration_ms
            if per_segment:
                self.buffered_ms = max(self.buffered_ms,
                                       self.last_segment * per_segment)
        return len(payload)

    def data(self):
        """Everything received, init segment first then sequence order."""
        return self.init_segment + b''.join(
            self.segments[key] for key in sorted(self.segments))

    def __repr__(self):
        return '<Format itag={0} segments={1} buffered={2}ms>'.format(
            self.itag, len(self.segments), self.buffered_ms)


class Session(object):
    """
    One playback session against a serverAbrStreamingUrl.

    `transport` is any callable taking (url, body, headers) and returning the
    response bytes, which is what keeps this testable without a network.
    """

    def __init__(self, url, ustreamer_config, client_info, transport,
                 po_token=None, formats=(), track_types=AUDIO_AND_VIDEO,
                 headers=None):
        self.url = url
        # Sent with every request. This is where the add-on's Authorization
        # goes: SABR is a separate endpoint from the player call, but it is
        # the same session and the same account, and a signed-in player that
        # streams anonymously is two different users to YouTube.
        self.headers = dict(headers or {})
        self.ustreamer_config = decode_ustreamer_config(ustreamer_config)
        self.client_info = client_info
        self.transport = transport
        self.po_token = po_token
        self.formats = list(formats)
        self.track_types = track_types
        self.player_time_ms = 0
        self.playback_cookie = None
        self.backoff_ms = 0
        self.resolution = 0
        self.finished = False
        # header_id is only meaningful within one response, so it is rebuilt
        # every round rather than kept.
        self._headers = {}
        self._chunks = {}
        self.rounds = 0
        self.parts_seen = {}
        # The server may serve tracks we never named; keep them rather than
        # dropping the bytes on the floor.
        self.adopt_unknown_formats = True

    def _by_itag(self, itag, last_modified=None, is_audio=None):
        """
        The format with this itag, registering it if the server has chosen
        one we did not ask for.

        The second half matters: SABR is server-adaptive, so the server picks
        the audio track and may switch video representation on its own.
        Demanding a specific audio itag - rather than naming a video
        preference and taking what arrives - gets policy parts and no media.
        """
        for fmt in self.formats:
            if fmt.itag == itag:
                return fmt
        if itag and self.adopt_unknown_formats:
            fmt = Format(itag, last_modified or 0,
                         is_audio=bool(is_audio))
            self.formats.append(fmt)
            return fmt
        return None

    @staticmethod
    def _key(header):
        """What identifies a segment across responses."""
        return (header['itag'], header['sequence_number'],
                bool(header['is_init_seg']))

    def _request_body(self):
        # A cold start says nothing about formats, buffers or position: it is
        # the difference between "I have played nothing" and "I am at 0ms",
        # and the server treats them differently.
        cold = self.rounds <= 1 and not any(f.segments for f in self.formats)
        state = msg.ClientAbrState.encode(
            self.player_time_ms, self.track_types,
            resolution=self.resolution, cold_start=cold)
        context = msg.StreamerContext.encode(
            self.client_info,
            po_token=self.po_token,
            playback_cookie=self.playback_cookie,
        )
        # Only report a range for a track whose segmentation the server
        # actually told us. Reporting a borrowed duration is worse than
        # reporting nothing: the server reads the time, not the segment
        # count, and answers by skipping whatever it believes is already
        # delivered - which is how the video track ended up missing a
        # segment it was never sent.
        buffered = []
        for fmt in self.formats:
            have = fmt.contiguous_segments
            per_segment = fmt.segment_duration_ms
            if not have or not per_segment:
                continue
            # Report what is still ahead of the play head, not everything
            # ever received. A player discards what it has played, and the
            # server caps how much it will hold for you - reporting from zero
            # keeps that window permanently full and stops the stream at a
            # minute.
            played = self.player_time_ms // per_segment
            start_segment = min(played + 1, have)
            start_ms = (start_segment - 1) * per_segment
            buffered.append(msg.BufferedRange.encode(
                fmt.format_id,
                start_ms,
                (have * per_segment) - start_ms,
                start_segment,
                have,
            ))
        selected = [] if cold else [f.format_id for f in self.formats
                                    if f.requested]
        return msg.VideoPlaybackAbrRequest.encode(
            state,
            self.ustreamer_config,
            context,
            player_time_ms=0 if cold else self.player_time_ms,
            selected_format_ids=selected,
            buffered_ranges=[] if cold else buffered,
            preferred_audio=[f.format_id for f in self.formats
                             if f.is_audio and f.requested],
            preferred_video=[f.format_id for f in self.formats
                             if not f.is_audio and f.requested],
        )

    def fetch(self):
        """
        One request/response round. Returns the bytes of media received.

        A round that receives nothing is not an error on its own - the server
        sends policy-only responses - but a run of them means the session is
        stuck, which the caller notices through `finished`.
        """
        self.rounds += 1
        self._headers = {}
        body = self._request_body()
        headers = dict(self.headers)
        headers['Content-Type'] = 'application/x-protobuf'
        raw = self.transport(self.url, body, headers)

        reader = ump.Reader()
        reader.feed(raw)
        received = 0
        for part_type, payload in reader:
            name = ump.name_of(part_type)
            self.parts_seen[name] = self.parts_seen.get(name, 0) + 1
            received += self._handle(part_type, payload)

        if reader.pending:
            # A part split across responses; the next round re-requests it.
            self.parts_seen['TRUNCATED'] = self.parts_seen.get('TRUNCATED', 0) + 1

        # Every track in a video shares one segmentation, but only the
        # tracks the server sent metadata for know what it is. Lend it to the
        # others, or a track without metadata reports nothing buffered and
        # pins the play head at zero - which the server reads as "they still
        # have not played anything" and answers with no media at all.
        for fmt in self.formats:
            if fmt.segments and fmt.segment_duration_ms:
                fmt.buffered_ms = (fmt.contiguous_segments
                                   * fmt.segment_duration_ms)

        return received

    @property
    def buffered_ms(self):
        """How far playback could continue: the least-buffered timed track."""
        timed = [f.buffered_ms for f in self.formats
                 if f.segment_duration_ms and f.contiguous_segments]
        return min(timed) if timed else 0

    @property
    def segment_duration_ms(self):
        """The segmentation this video uses, from whichever track said so."""
        for fmt in self.formats:
            if fmt.segment_duration_ms:
                return fmt.segment_duration_ms
        return 0

    def _handle(self, part_type, payload):
        if part_type == ump.MEDIA_HEADER:
            header = msg.MediaHeader.decode(payload)
            if not header['itag'] and header['format_id']:
                header['itag'] = header['format_id']['itag']
            self._headers[header['header_id']] = header
            # Keyed by what the segment *is*, not by the header id it came
            # under. Header ids restart at 1 in every response, so a segment
            # split across two responses would otherwise have its second half
            # appended to whatever unrelated segment reused that id.
            self._chunks.setdefault(self._key(header), bytearray())
            return 0

        if part_type == ump.MEDIA:
            header_id, pos = ump.read_varint(payload, 0)
            if header_id is None:
                return 0
            header = self._headers.get(header_id)
            if header is None:
                return 0
            self._chunks.setdefault(self._key(header), bytearray())
            self._chunks[self._key(header)] += payload[pos:]
            return 0

        if part_type == ump.MEDIA_END:
            header_id, _ = ump.read_varint(payload, 0)
            if header_id is None:
                return 0
            header = self._headers.get(header_id)
            if header is None:
                return 0
            body = self._chunks.pop(self._key(header), None)
            if not body:
                return 0
            fmt = self._by_itag(header['itag'], header['lmt'])
            if fmt is None:
                return 0
            return fmt.accept(header, bytes(body))

        if part_type == ump.FORMAT_INITIALIZATION_METADATA:
            meta = msg.FormatInitializationMetadata.decode(payload)
            if meta['format_id']:
                fmt = self._by_itag(meta['format_id']['itag'],
                                    meta['format_id']['last_modified'],
                                    is_audio=meta['mime_type'].startswith('audio'))
                if fmt is not None:
                    fmt.is_audio = meta['mime_type'].startswith('audio')
                    fmt.mime_type = meta['mime_type']
                    fmt.total_duration_ms = meta['end_time_ms']
                    fmt.end_segment_number = meta['end_segment_number']
            return 0

        if part_type == ump.NEXT_REQUEST_POLICY:
            policy = msg.NextRequestPolicy.decode(payload)
            if policy['playback_cookie']:
                self.playback_cookie = policy['playback_cookie']
            if policy['backoff_ms']:
                self.backoff_ms = policy['backoff_ms']
            return 0

        if part_type == ump.SABR_REDIRECT:
            url = msg.SabrRedirect.decode(payload)
            if url:
                self.url = url
            return 0

        if part_type == ump.STREAM_PROTECTION_STATUS:
            status = msg.StreamProtectionStatus.decode(payload)
            if status == msg.StreamProtectionStatus.ATTESTATION_REQUIRED:
                raise SabrError('attestation required - the proof-of-origin '
                                'token was rejected or is missing')
            return 0

        if part_type == ump.SABR_ERROR:
            raise SabrError('server returned SABR_ERROR')

        return 0

    def run(self, until_ms=None, max_rounds=200, lead_ms=30000):
        """
        Fill the buffer up to `until_ms`.

        The play head is playback position, not buffer end - a real player is
        always behind what it has downloaded. Reporting the two as equal says
        "I have played everything I have", and the server stops sending. So
        the head is walked forward to stay `lead_ms` behind the buffer, which
        is what a player does while it plays.
        """
        idle = 0
        while self.rounds < max_rounds:
            before = self.buffered_ms
            got = self.fetch()
            buffered = self.buffered_ms
            self.player_time_ms = max(0, buffered - lead_ms)
            if until_ms is not None and buffered >= until_ms:
                return True
            done = [f for f in self.formats
                    if f.total_duration_ms and f.buffered_ms >= f.total_duration_ms]
            if done and len(done) == len(self.formats):
                self.finished = True
                return True
            if not got and buffered <= before:
                idle += 1
                if idle >= MAX_IDLE_ROUNDS:
                    self.finished = True
                    return False
            else:
                idle = 0
        return False
