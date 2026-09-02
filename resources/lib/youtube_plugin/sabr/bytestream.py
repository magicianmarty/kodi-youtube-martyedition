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

    def __init__(self, session, itag, max_rounds=40):
        self.session = session
        self.itag = itag
        self.max_rounds = max_rounds

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
        starts = sorted(pieces)
        index = bisect_right(starts, offset) - 1
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

        The server sends relative to the play head, so a reader seeking into
        the middle of a file has to say so in seconds, not bytes.
        """
        fmt = self.format
        if fmt is None or not fmt.segment_duration_ms:
            return 0
        pieces = fmt.offsets
        if not pieces:
            return 0
        starts = sorted(pieces)
        index = bisect_right(starts, offset) - 1
        if index < 1:
            return 0
        # Piece 0 is the init segment, so the nth piece is segment n.
        return max(0, (index - 1) * fmt.segment_duration_ms)
