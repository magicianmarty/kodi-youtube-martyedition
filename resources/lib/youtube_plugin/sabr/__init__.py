# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    SABR - the protocol YouTube actually streams with.

    Classic range requests against a googlevideo URL now serve roughly the
    first 60 seconds of any stream and then answer 403, whatever the client,
    quality, headers or proof-of-origin token. Measured, not assumed: a 19
    second video returns in full, a 3m33s video stops at 66s, a 29 minute
    video stops at 61s, and audio is capped exactly like video.

    The official players do not use range requests. They POST a protobuf
    VideoPlaybackAbrRequest to the serverAbrStreamingUrl and read back a UMP
    stream of media chunks, telling the server on each request what they have
    buffered and where the play head is. That is what this package implements.
"""
