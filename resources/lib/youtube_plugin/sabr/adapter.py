# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    Building a SABR session out of what the add-on already has.

    The add-on knows how to be signed in: it holds four token types, picks
    the one that matches the client it is impersonating, and refreshes them.
    None of that should be reimplemented here - a token scraped once goes
    stale in an hour and answers 401. So this takes the player response and
    the add-on's own authenticated headers and returns a session.
"""

from . import client as sabr
from . import messages as msg

# Where the pieces live in a player response.
STREAMING_DATA = 'streamingData'
SERVER_ABR_URL = 'serverAbrStreamingUrl'
ADAPTIVE_FORMATS = 'adaptiveFormats'


def ustreamer_config(player_response):
    """The opaque blob the server needs handed back on every request."""
    return (player_response
            .get('playerConfig', {})
            .get('mediaCommonConfig', {})
            .get('mediaUstreamerRequestConfig', {})
            .get('videoPlaybackUstreamerConfig'))


def supports_sabr(player_response):
    """Whether this response offers the SABR endpoint at all."""
    streaming = player_response.get(STREAMING_DATA) or {}
    return bool(streaming.get(SERVER_ABR_URL) and ustreamer_config(player_response))


def client_info_from(client):
    """
    A StreamerContext.ClientInfo from one of the add-on's client configs.

    The identity here has to match the one the player request was made with;
    a session that says it is a VR headset while the player response was
    fetched as something else is two clients to the server.
    """
    context = ((client.get('json') or {}).get('context') or {}).get('client') or {}
    return msg.ClientInfo.encode(
        client_name=client.get('_id', {}).get('client_id', 0),
        client_version=context.get('clientVersion', ''),
        os_name=context.get('osName'),
        os_version=context.get('osVersion'),
        device_make=context.get('deviceMake'),
        device_model=context.get('deviceModel'),
        android_sdk=context.get('androidSdkVersion'),
    )


def pick_formats(player_response, itag=None, audio_itag=None):
    """
    Which formats to name in the request.

    Only a video preference is named. SABR is server-adaptive and picks the
    audio track itself; demanding a specific audio itag gets policy parts and
    no media at all.
    """
    streaming = player_response.get(STREAMING_DATA) or {}
    formats = []
    for entry in streaming.get(ADAPTIVE_FORMATS) or ():
        mime = str(entry.get('mimeType') or '')
        is_audio = mime.startswith('audio/')
        if itag and not is_audio and entry.get('itag') != itag:
            continue
        if audio_itag and is_audio and entry.get('itag') != audio_itag:
            continue
        if is_audio and not audio_itag:
            continue
        fmt = sabr.Format(entry.get('itag'), entry.get('lastModified'),
                          xtags=entry.get('xtags'), is_audio=is_audio)
        fmt.requested = True
        formats.append(fmt)
    return formats


def session_for(player_response, client, transport, po_token=None,
                headers=None, itag=None, audio_itag=None,
                track_types=sabr.AUDIO_AND_VIDEO):
    """
    A ready session, or None when this response cannot be streamed by SABR.

    `headers` should be the add-on's own request headers for this client,
    Authorization included - that is what keeps the stream on the same
    account as the player call.
    """
    if not supports_sabr(player_response):
        return None
    streaming = player_response[STREAMING_DATA]
    return sabr.Session(
        streaming[SERVER_ABR_URL],
        ustreamer_config(player_response),
        client_info_from(client),
        transport,
        po_token=po_token,
        formats=pick_formats(player_response, itag, audio_itag),
        track_types=track_types,
        headers=headers,
    )
