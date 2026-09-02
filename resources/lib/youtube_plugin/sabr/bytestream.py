# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    Serving byte ranges out of a SABR session.

    inputstream.adaptive speaks DASH and asks for byte ranges of a file. SABR
    delivers numbered segments. They meet because a media header carries
    `start_range`, the segment's offset in that same file, and the segments
    are contiguous - the init segment at 0, then each one where the last
    ended. So the file the old range-request world would have served can be
    reassembled from them, and nothing above this has to know the difference.
"""

from bisect import bisect_right


class ByteStream(object):
    """
    One format of one video, addressable by byte offset.

    Deliberately not a cache of the whole file: segments are kept as they
    arrive and looked up by offset, so a seek fetches what it needs rather
    than everything before it.
    """

    def __init__(self, session, itag, max_rounds=40,
                 content_length=0, duration_ms=0):
        self.session = session
        self.itag = itag
        self.max_rounds = max_rounds
        # From the player response. These make the play head derivable from a
        # byte offset alone, which matters because a video track often gets
        # no FormatInitializationMetadata and so has no segment length of its
        # own to count in.
        self.content_length = int(content_length or 0)
        self.duration_ms = int(duration_ms or 0)

    @property
    def format(self):
        for fmt in self.session.formats:
            if fmt.itag == self.itag:
                return fmt
        return None

    def _pieces(self):
        fmt = self.format
        return fmt.offsets if fmt is not None else {}

    def available(self, offset):
        """
        How many contiguous bytes are held from `offset`, if any.

        Zero means the piece containing that offset has not arrived, which is
        the signal to fetch rather than to return a short read - a short read
        would be indistinguishable from end of file.
        """
        pieces = self._pieces()
        if not pieces:
            return 0
        starts = sorted(pieces)
        index = bisect_right(starts, offset) - 1
        if index < 0:
            return 0
        end = 0
        start = starts[index]
        if start + len(pieces[start]) <= offset:
            return 0
        # Walk forward while the pieces join up.
        end = start + len(pieces[start])
        for following in starts[index + 1:]:
            if following != end:
                break
            end += len(pieces[following])
        return end - offset

    def _read_available(self, offset, length):
        pieces = self._pieces()
        if not pieces:
            return b''
        starts = sorted(pieces)
        index = bisect_right(starts, offset) - 1
        if index < 0:
            # The offset falls before anything held. Negative indices are
            # perfectly legal on a list and would silently read from the
            # wrong end of the stream.
            return b''
        out = bytearray()
        position = offset
        while index < len(starts) and len(out) < length:
            start = starts[index]
            piece = pieces[start]
            if start > position:
                break
            inside = position - start
            if inside >= len(piece):
                index += 1
                continue
            take = piece[inside:inside + (length - len(out))]
            out += take
            position += len(take)
            index += 1
        return bytes(out)

    def read(self, offset, length):
        """
        `length` bytes from `offset`, fetching until they are here.

        Returns short only at the end of the stream, which is what a reader
        needs in order to tell "not yet" from "no more".
        """
        rounds = 0
        while self.available(offset) < length and rounds < self.max_rounds:
            before = self.available(offset)
            # Keep the play head behind the data being asked for, or the
            # server considers the request already satisfied.
            self.session.player_time_ms = self.position_ms(offset)
            self.session.fetch()
            rounds += 1
            if self.available(offset) <= before and self.session.finished:
                break
            if self.available(offset) <= before and rounds > 3:
                break
        return self._read_available(offset, length)

    def position_ms(self, offset):
        """
        Where `offset` falls in playback time.

        The server sends relative to the play head, so a reader asking for
        bytes has to say where that is in seconds. Getting this wrong does
        not fail loudly: the head stays at zero, the server decides the
        opening grant is unconsumed and sends nothing more, and the track
        quietly starves. When that track is the video one and audio has a
        working timeline of its own, the picture freezes while the sound and
        the position counter carry on - which is exactly the bug this is
        here to prevent.

        Byte-proportional first, because it needs nothing but the player
        response: a track that never receives FormatInitializationMetadata
        has no segment length to count in.
        """
        if self.content_length and self.duration_ms:
            position = int(self.duration_ms * offset / self.content_length)
            return max(0, min(position, self.duration_ms))

        fmt = self.format
        per_segment = 0
        if fmt is not None:
            per_segment = fmt.segment_duration_ms or self.session.segment_duration_ms
        if not per_segment or fmt is None or not fmt.offsets:
            return 0
        starts = sorted(fmt.offsets)
        index = bisect_right(starts, offset) - 1
        if index < 1:
            return 0
        # Piece 0 is the init segment, so the nth piece is segment n.
        return max(0, (index - 1) * per_segment)
