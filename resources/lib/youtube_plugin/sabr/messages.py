# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    The SABR messages, as field numbers.

    Only the fields that are actually needed are named. Everything else on the
    wire is ignored rather than guessed at - an unknown field is data we do
    not need, not an error.
"""

from . import protobuf as pb


class FormatId(object):
    ITAG = 1
    LAST_MODIFIED = 2
    XTAGS = 3

    @staticmethod
    def encode(itag, last_modified=None, xtags=None):
        return pb.encode([
            (FormatId.ITAG, int(itag)),
            (FormatId.LAST_MODIFIED, int(last_modified) if last_modified else None),
            (FormatId.XTAGS, xtags or None),
        ])

    @staticmethod
    def decode(raw):
        fields = pb.decode(raw)
        return {
            'itag': pb.first(fields, FormatId.ITAG, 0),
            'last_modified': pb.first(fields, FormatId.LAST_MODIFIED, 0),
            'xtags': pb.text(fields, FormatId.XTAGS, ''),
        }


class ClientAbrState(object):
    PLAYER_TIME_MS = 28
    ELAPSED_WALL_TIME_MS = 36
    ENABLED_TRACK_TYPES = 40
    TIME_SINCE_LAST_SEEK = 29
    PLAYBACK_RATE = 35
    VISIBILITY = 34
    BANDWIDTH_ESTIMATE = 23

    # What the player is asking the server to send. The field name says
    # bitfield and it means it: audio is bit 0, video is bit 1, and zero
    # asks for nothing - which the server answers with policy parts, no
    # media, and an invitation to reload the player response.
    TRACKS_AUDIO_ONLY = 1
    TRACKS_VIDEO_ONLY = 2
    TRACKS_AUDIO_AND_VIDEO = 3

    STICKY_RESOLUTION = 21
    LAST_MANUAL_SELECTED_RESOLUTION = 16
    VISIBILITY = 34
    DRC_ENABLED = 46

    @staticmethod
    def encode(player_time_ms, track_types, bandwidth=None, resolution=None,
               cold_start=False):
        """
        A cold start omits the play head: the first request has not played
        anything, and saying "I am at 0ms" is not the same as saying nothing.
        """
        return pb.encode([
            (ClientAbrState.LAST_MANUAL_SELECTED_RESOLUTION,
             int(resolution) if resolution else None),
            (ClientAbrState.BANDWIDTH_ESTIMATE,
             int(bandwidth) if bandwidth else None),
            (ClientAbrState.STICKY_RESOLUTION,
             int(resolution) if resolution else None),
            (ClientAbrState.PLAYER_TIME_MS,
             None if cold_start else int(player_time_ms)),
            (ClientAbrState.VISIBILITY, 0),
            (ClientAbrState.ENABLED_TRACK_TYPES, int(track_types)),
        ])


class BufferedRange(object):
    FORMAT_ID = 1
    START_TIME_MS = 2
    DURATION_MS = 3
    START_SEGMENT_INDEX = 4
    END_SEGMENT_INDEX = 5

    @staticmethod
    def encode(format_id, start_time_ms, duration_ms, start_segment, end_segment):
        return pb.encode([
            (BufferedRange.FORMAT_ID, format_id),
            (BufferedRange.START_TIME_MS, int(start_time_ms)),
            (BufferedRange.DURATION_MS, int(duration_ms)),
            (BufferedRange.START_SEGMENT_INDEX, int(start_segment)),
            (BufferedRange.END_SEGMENT_INDEX, int(end_segment)),
        ])


class ClientInfo(object):
    HL = 1
    GL = 2
    DEVICE_MAKE = 12
    DEVICE_MODEL = 13
    # The visitor this session belongs to. The proof-of-origin token is bound
    # to it, so a request that omits it cannot be matched to the token it
    # carries - and an unmatched token is answered with ATTESTATION_REQUIRED,
    # which looks exactly like a rejected token rather than an unidentified
    # session.
    VISITOR_DATA = 14
    USER_AGENT = 15
    CLIENT_NAME = 16
    CLIENT_VERSION = 17
    OS_NAME = 18
    OS_VERSION = 19
    ACCEPT_LANGUAGE = 21
    ACCEPT_REGION = 22
    ANDROID_SDK_VERSION = 64

    @staticmethod
    def encode(client_name, client_version, os_name=None, os_version=None,
               device_make=None, device_model=None, android_sdk=None,
               visitor_data=None, user_agent=None, language=None, region=None):
        return pb.encode([
            (ClientInfo.HL, language or None),
            (ClientInfo.GL, region or None),
            (ClientInfo.DEVICE_MAKE, device_make or None),
            (ClientInfo.DEVICE_MODEL, device_model or None),
            (ClientInfo.VISITOR_DATA, visitor_data or None),
            (ClientInfo.USER_AGENT, user_agent or None),
            (ClientInfo.CLIENT_NAME, int(client_name)),
            (ClientInfo.CLIENT_VERSION, client_version),
            (ClientInfo.OS_NAME, os_name or None),
            (ClientInfo.OS_VERSION, os_version or None),
            (ClientInfo.ANDROID_SDK_VERSION,
             int(android_sdk) if android_sdk else None),
        ])


class StreamerContext(object):
    CLIENT_INFO = 1
    PO_TOKEN = 2
    PLAYBACK_COOKIE = 3

    SABR_CONTEXTS = 5
    UNSENT_SABR_CONTEXTS = 6

    @staticmethod
    def encode(client_info, po_token=None, playback_cookie=None,
               sabr_contexts=(), unsent_sabr_contexts=()):
        fields = [
            (StreamerContext.CLIENT_INFO, client_info),
            (StreamerContext.PO_TOKEN, po_token or None),
            (StreamerContext.PLAYBACK_COOKIE, playback_cookie or None),
        ]
        for context_type, value in sabr_contexts:
            fields.append((StreamerContext.SABR_CONTEXTS, pb.encode([
                (1, int(context_type)),
                (2, value),
            ])))
        for context_type in unsent_sabr_contexts:
            fields.append((StreamerContext.UNSENT_SABR_CONTEXTS,
                           int(context_type)))
        return pb.encode(fields)


class VideoPlaybackAbrRequest(object):
    CLIENT_ABR_STATE = 1
    SELECTED_FORMAT_IDS = 2
    BUFFERED_RANGES = 3
    PLAYER_TIME_MS = 4
    USTREAMER_CONFIG = 5
    PREFERRED_AUDIO_FORMAT_IDS = 16
    PREFERRED_VIDEO_FORMAT_IDS = 17
    STREAMER_CONTEXT = 19

    @staticmethod
    def encode(client_abr_state, ustreamer_config, streamer_context,
               player_time_ms=0, selected_format_ids=(), buffered_ranges=(),
               preferred_audio=(), preferred_video=()):
        fields = [(VideoPlaybackAbrRequest.CLIENT_ABR_STATE, client_abr_state)]
        fields += [(VideoPlaybackAbrRequest.SELECTED_FORMAT_IDS, f)
                   for f in selected_format_ids]
        fields += [(VideoPlaybackAbrRequest.BUFFERED_RANGES, r)
                   for r in buffered_ranges]
        fields.append((VideoPlaybackAbrRequest.PLAYER_TIME_MS, int(player_time_ms)))
        fields.append((VideoPlaybackAbrRequest.USTREAMER_CONFIG, ustreamer_config))
        fields += [(VideoPlaybackAbrRequest.PREFERRED_AUDIO_FORMAT_IDS, f)
                   for f in preferred_audio]
        fields += [(VideoPlaybackAbrRequest.PREFERRED_VIDEO_FORMAT_IDS, f)
                   for f in preferred_video]
        fields.append((VideoPlaybackAbrRequest.STREAMER_CONTEXT, streamer_context))
        return pb.encode(fields)


class MediaHeader(object):
    HEADER_ID = 1
    VIDEO_ID = 2
    ITAG = 3
    LMT = 4
    START_RANGE = 6
    COMPRESSION = 7
    IS_INIT_SEG = 8
    SEQUENCE_NUMBER = 9
    START_MS = 11
    DURATION_MS = 12
    FORMAT_ID = 13
    CONTENT_LENGTH = 14

    @staticmethod
    def decode(raw):
        fields = pb.decode(raw)
        format_id = pb.first(fields, MediaHeader.FORMAT_ID)
        return {
            'header_id': pb.first(fields, MediaHeader.HEADER_ID, 0),
            'video_id': pb.text(fields, MediaHeader.VIDEO_ID),
            'itag': pb.first(fields, MediaHeader.ITAG, 0),
            'lmt': pb.first(fields, MediaHeader.LMT, 0),
            'start_range': pb.first(fields, MediaHeader.START_RANGE, 0),
            'compression': pb.first(fields, MediaHeader.COMPRESSION, 0),
            'is_init_seg': bool(pb.first(fields, MediaHeader.IS_INIT_SEG, 0)),
            'sequence_number': pb.first(fields, MediaHeader.SEQUENCE_NUMBER, 0),
            'start_ms': pb.first(fields, MediaHeader.START_MS, 0),
            'duration_ms': pb.first(fields, MediaHeader.DURATION_MS, 0),
            'content_length': pb.first(fields, MediaHeader.CONTENT_LENGTH, 0),
            'format_id': FormatId.decode(format_id) if format_id else None,
        }


class FormatInitializationMetadata(object):
    VIDEO_ID = 1
    FORMAT_ID = 2
    END_TIME_MS = 3
    END_SEGMENT_NUMBER = 4
    MIME_TYPE = 5
    DURATION_UNITS = 9
    DURATION_TIMESCALE = 10

    @staticmethod
    def decode(raw):
        fields = pb.decode(raw)
        format_id = pb.first(fields, FormatInitializationMetadata.FORMAT_ID)
        return {
            'video_id': pb.text(fields, FormatInitializationMetadata.VIDEO_ID),
            'mime_type': pb.text(fields, FormatInitializationMetadata.MIME_TYPE),
            'end_time_ms': pb.first(fields, FormatInitializationMetadata.END_TIME_MS, 0),
            'end_segment_number': pb.first(
                fields, FormatInitializationMetadata.END_SEGMENT_NUMBER, 0),
            'duration_units': pb.first(
                fields, FormatInitializationMetadata.DURATION_UNITS, 0),
            'duration_timescale': pb.first(
                fields, FormatInitializationMetadata.DURATION_TIMESCALE, 0),
            'format_id': FormatId.decode(format_id) if format_id else None,
        }


class SabrRedirect(object):
    URL = 1

    @staticmethod
    def decode(raw):
        return pb.text(pb.decode(raw), SabrRedirect.URL)


class StreamProtectionStatus(object):
    STATUS = 1
    OK = 1
    ATTESTATION_PENDING = 2
    ATTESTATION_REQUIRED = 3

    @staticmethod
    def decode(raw):
        return pb.first(pb.decode(raw), StreamProtectionStatus.STATUS, 0)


class NextRequestPolicy(object):
    """
    What the server wants the client to do next.

    Field 7 is the playback cookie. It is not advice: it is continuity, and
    a client that does not echo it back looks like a new session on every
    request. That is what stops the stream once the opening grant is spent.
    """

    BACKOFF_TIME_MS = 1
    PLAYBACK_COOKIE = 7

    @staticmethod
    def decode(raw):
        fields = pb.decode(raw)
        return {
            'backoff_ms': pb.first(fields, NextRequestPolicy.BACKOFF_TIME_MS, 0),
            'playback_cookie': pb.first(fields, NextRequestPolicy.PLAYBACK_COOKIE),
        }


class ReloadPlayerResponse(object):
    """
    The server telling the client its player response has expired.

    This is the whole reason a stream stops after about a minute. It is not a
    grant being exhausted and nothing to do with how the request is shaped:
    the serverAbrStreamingUrl and its ustreamer config go stale, and the
    server hands back a token to mint fresh ones with. A client that ignores
    it simply stops being sent media.
    """

    CONTEXT = 1
    TOKEN = 1

    @staticmethod
    def decode(raw):
        context = pb.first(pb.decode(raw), ReloadPlayerResponse.CONTEXT)
        if not context:
            return ''
        token = pb.first(pb.decode(context), ReloadPlayerResponse.TOKEN)
        if isinstance(token, bytes):
            return token.decode('utf-8', 'replace')
        return token or ''


class SabrContextUpdate(object):
    """
    State the server hands the client to hand back.

    This is the part that makes a session a session. The server issues
    contexts and expects them echoed in StreamerContext on every subsequent
    request; a client that drops them looks stateless, and a stateless client
    is asked to attest over and over because there is nothing to attest
    against.
    """

    TYPE = 1
    SCOPE = 2
    VALUE = 3
    SEND_BY_DEFAULT = 4
    WRITE_POLICY = 5

    OVERWRITE = 1
    KEEP_EXISTING = 2

    @staticmethod
    def decode(raw):
        fields = pb.decode(raw)
        return {
            'type': pb.first(fields, SabrContextUpdate.TYPE, 0),
            'scope': pb.first(fields, SabrContextUpdate.SCOPE, 0),
            'value': pb.first(fields, SabrContextUpdate.VALUE),
            'send_by_default': bool(pb.first(
                fields, SabrContextUpdate.SEND_BY_DEFAULT, 0)),
            'write_policy': pb.first(fields, SabrContextUpdate.WRITE_POLICY, 0),
        }


class SabrContextSendingPolicy(object):
    """Which contexts to start sending, stop sending, or throw away."""

    START = 1
    STOP = 2
    DISCARD = 3

    @staticmethod
    def decode(raw):
        fields = pb.decode(raw)
        return {
            'start': list(fields.get(SabrContextSendingPolicy.START) or ()),
            'stop': list(fields.get(SabrContextSendingPolicy.STOP) or ()),
            'discard': list(fields.get(SabrContextSendingPolicy.DISCARD) or ()),
        }
