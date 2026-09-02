# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    Answering the add-on's own stream proxy out of SABR.

    inputstream.adaptive asks the local proxy for byte ranges. Those used to
    be forwarded to googlevideo, which now serves about a minute and then
    answers 403. This serves the same ranges out of a SABR session instead,
    so nothing above it - the MPD, the player, the skin - has to change.

    The player response is fetched through the add-on's own client, which is
    what keeps the stream on the same signed-in account as everything else.
"""

from threading import RLock
from time import time

from . import adapter
from . import client as sabr
from .bytestream import ByteStream

PLAYER_URL = 'https://www.youtube.com/youtubei/v1/player'

# A renewal is a player request; attempting one per failed read is a
# request storm, and YouTube answers storms with a bot check.
RENEW_COOLDOWN_SECONDS = 5

# The client to stream as. It has to be one the add-on can authenticate, and
# one the player response offers serverAbrStreamingUrl for.
CLIENT_NAME = 'android_vr'


class StreamServer(object):
    """Byte ranges for (video, itag), backed by SABR sessions."""

    def __init__(self, client, po_token_source=None, log=None):
        self.client = client
        self.po_token_source = po_token_source
        self.log = log
        self._streams = {}
        self._lock = RLock()
        self._renew_not_before = 0.0

    @staticmethod
    def _json_hook(response=None, **_kwargs):
        """
        A response hook returns (etag, value) - returning the value alone
        unpacks the JSON's own keys and fails with "too many values".
        """
        response.raise_for_status()
        return response.headers.get('ETag'), response.json()

    @staticmethod
    def _bytes_hook(response=None, **_kwargs):
        response.raise_for_status()
        return response.headers.get('ETag'), response.content

    def _note(self, message):
        if self.log:
            self.log.info('SABR: {0}'.format(message))

    def _visitor_data(self, video_id):
        """
        The visitor id this session is known by.

        Taken from a player response rather than invented: the token has to
        be bound to the same identity the request carries, and the add-on's
        own visitor data is not exposed on the client spec.
        """
        held = getattr(self.client, '_visitor_data', None)
        if isinstance(held, dict):
            current = held.get(getattr(self.client, '_visitor_data_key',
                                       'current'))
            if current:
                return current
        response = self._player_response(video_id)
        if not response:
            return None
        return (response.get('responseContext') or {}).get('visitorData')

    def _player_response(self, video_id, po_token=None, visitor_data=None,
                         reload_token=None):
        """
        Ask for the player response as the add-on's authenticated client.

        Built through build_client so the Authorization header, api key and
        client identity are the add-on's rather than ours - a token copied
        out by hand is stale within the hour.
        """
        json_data = {'videoId': video_id}
        if po_token:
            json_data['serviceIntegrityDimensions'] = {'poToken': po_token}
        # contentPlaybackContext rides on every player request, not only on
        # reloads. Sending it for the first time *as part of* a reload
        # changes the shape of the session halfway through, and the answer to
        # that is LOGIN_REQUIRED - "sign in to confirm you're not a bot" -
        # which reads as an authentication problem and is not one.
        playback_context = {
            'contentPlaybackContext': {
                'html5Preference': 'HTML5_PREF_WANTS',
            },
        }
        if reload_token:
            playback_context['reloadPlaybackContext'] = {
                'reloadPlaybackParams': {'token': reload_token},
            }
        json_data['playbackContext'] = playback_context
        # Shaped exactly like the add-on's own player request. The pieces
        # that are easy to leave out are the ones that matter: without
        # _access_tokens, build_client has nothing to put in the
        # Authorization header, so the request goes out anonymous - and an
        # anonymous reload is answered with LOGIN_REQUIRED, which reads as a
        # bot check rather than as the missing credential it is.
        client_data = {
            'json': json_data,
            'url': getattr(self.client, 'V1_API_URL', PLAYER_URL),
            'method': 'POST',
            '_access_tokens': {
                'user': self.client._access_tokens.get('user'),
                'tv': self.client._access_tokens.get('tv'),
                'vr': self.client._access_tokens.get('vr'),
            },
            '_endpoint': 'player',
            '_cpn': self.client._generate_cpn(),
            '_visitor_data': visitor_data,
        }
        spec = self.client.build_client(CLIENT_NAME, client_data)
        if not spec:
            return None
        return self.client.request(
            response_hook=self._json_hook,
            error_title='SABR: failed to get player response',
            error_hook=self.client._player_error_hook,
            video_id=video_id,
            client_name=CLIENT_NAME,
            has_auth=spec.get('_has_auth'),
            visitor_data=spec.get('_visitor_data'),
            cache=False,
            pass_data=True,
            raise_exc=False,
            **spec
        )

    def _transport(self, headers):
        def send(url, body, request_headers):
            merged = dict(headers or {})
            merged.update(request_headers or {})
            response = self.client.request(
                url,
                method='POST',
                data=body,
                headers=merged,
                error_title='SABR: stream request failed',
                response_hook=self._bytes_hook,
                cache=False,
            )
            if response is None:
                raise sabr.SabrError('no response from the SABR endpoint')
            return response

        return send

    def stream_for(self, video_id, itag):
        """A ByteStream for this format, building the session on first use."""
        key = (video_id, int(itag))
        with self._lock:
            existing = self._streams.get(key)
            if existing is not None:
                return existing

            # The token has to be bound to whatever identifies this
            # session, and that is the visitor data - not the video id. A
            # token bound to the wrong thing is not rejected with an error;
            # the player response simply comes back LOGIN_REQUIRED, "sign in
            # to confirm you're not a bot", exactly as if no token were sent.
            visitor_data = self._visitor_data(video_id)
            po_token = None
            if self.po_token_source:
                try:
                    po_token = self.po_token_source(visitor_data or video_id)
                except Exception:
                    po_token = None

            response = self._player_response(video_id, po_token, visitor_data)
            spec = self.client.build_client(CLIENT_NAME) or {}
            if not response:
                self._note('no player response for {0}'.format(video_id))
                self._streams[key] = None
                return None
            if not adapter.supports_sabr(response):
                status = (response.get('playabilityStatus') or {}).get('status')
                self._note('{0}: no serverAbrStreamingUrl (status {1!r}, '
                           'token {2})'.format(video_id, status,
                                               'yes' if po_token else 'no'))
                self._streams[key] = None
                return None

            session = adapter.session_for(
                response,
                spec,
                self._transport(spec.get('headers')),
                po_token=po_token,
                headers={},
                itag=int(itag),
            )
            if session is None:
                self._streams[key] = None
                return None

            # Size and duration for this exact format, so the play head can
            # be derived from a byte offset even when the track never gets
            # its own segment metadata.
            content_length = duration_ms = 0
            for entry in (response.get('streamingData') or {}).get(
                    'adaptiveFormats') or ():
                if entry.get('itag') == int(itag):
                    content_length = int(entry.get('contentLength') or 0)
                    duration_ms = int(entry.get('approxDurationMs') or 0)
                    break
            if not duration_ms:
                duration_ms = int(1000 * float(
                    (response.get('videoDetails') or {}).get('lengthSeconds')
                    or 0))

            def renew(reload_token, _video_id=video_id, _pot=po_token,
                      _visitor=visitor_data):
                # Keep the session's original token: minting a fresh one
                # makes a new identity, which is the opposite of the
                # continuity a reload is asking for.
                #
                # And do not retry in a tight loop. Every failed read used to
                # attempt another renewal immediately - 172 player requests
                # in three minutes - and a request storm is precisely what
                # earns LOGIN_REQUIRED, so the retries caused the failure
                # they were retrying.
                now = time()
                if now < self._renew_not_before:
                    return None
                self._renew_not_before = now + RENEW_COOLDOWN_SECONDS

                # Mint a token for the reload. The first attempt at this made
                # things worse, but that was while every failed read fired
                # another renewal - the storm caused the refusals, not the
                # token. With the cooldown above, one fresh token per reload
                # is what the reference implementation does.
                if self.po_token_source:
                    try:
                        minted = self.po_token_source(_visitor or _video_id)
                        if minted:
                            _pot = minted
                    except Exception:
                        pass

                fresh = self._player_response(_video_id, _pot, _visitor,
                                              reload_token=reload_token)
                if not fresh or not adapter.supports_sabr(fresh):
                    status = ((fresh or {}).get('playabilityStatus')
                              or {}).get('status')
                    self._note('renewal refused for {0} (status {1!r})'
                               .format(_video_id, status))
                    return None
                self._note('renewed the stream for {0}'.format(_video_id))
                return (fresh['streamingData'][adapter.SERVER_ABR_URL],
                        adapter.ustreamer_config(fresh))

            def attest(sess, _visitor=visitor_data, _video_id=video_id):
                """Mint a fresh token when the server asks for one."""
                if not self.po_token_source:
                    return False
                try:
                    minted = self.po_token_source(_visitor or _video_id)
                except Exception:
                    return False
                if not minted:
                    return False
                sess.po_token = sabr.decode_po_token(minted)
                self._note('re-attested mid-stream for {0}'.format(_video_id))
                return True

            session.attest = attest

            stream = ByteStream(session, int(itag),
                                content_length=content_length,
                                duration_ms=duration_ms,
                                renew=renew)
            self._note('serving itag {0} of {1} over SABR '
                       '({2} bytes, {3}ms)'.format(itag, video_id,
                                                   content_length, duration_ms))
            self._streams[key] = stream
            return stream

    def read(self, video_id, itag, offset, length):
        """
        The requested bytes, or None when SABR cannot serve this at all -
        in which case the caller falls back to the old proxy path rather
        than failing the request.
        """
        try:
            stream = self.stream_for(video_id, itag)
            if stream is None:
                return None
            data = stream.read(offset, length)
            if not data:
                self._note('itag {0} returned nothing at offset {1}'
                           .format(itag, offset))
            return data
        except Exception:
            if self.log:
                self.log.exception('SABR: falling back to the range proxy')
            return None

    def close(self, video_id=None):
        with self._lock:
            if video_id is None:
                self._streams.clear()
                return
            for key in [k for k in self._streams if k[0] == video_id]:
                del self._streams[key]
