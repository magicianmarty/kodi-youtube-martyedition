# -*- coding: utf-8 -*-
"""
Sponsor segment lookup, for skipping the read in the middle of a video.

YouTube's own "most replayed" graph would be the obvious source, since a
trough in it is where people skip. It is not reachable: neither the InnerTube
next endpoint nor the watch page carries heatMarkers for an unauthenticated
client, on a small channel or on a video with a billion views. Reaching it
would need a signed-in first-party session, which this add-on's OAuth token
does not buy - it answers 401 against InnerTube.

SponsorBlock is better information anyway. A heatmap trough is an inference
that a sponsor might be there; SponsorBlock is a person saying this span is
one, with a category attached.
"""

import json
from hashlib import sha256
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = 'https://sponsor.ajay.app/api/skipSegments'
TIMEOUT = 10

# Skipped by default: a paid read, a plug for the creator's own things, and
# "like and subscribe". Intros, outros and music sections are deliberately not
# here - those are part of the video someone chose to watch.
DEFAULT_CATEGORIES = ('sponsor', 'selfpromo', 'interaction')

# The whole point of a sponsor segment is that it is long enough to sit
# through. Skipping a two second one is just a stutter.
MIN_SEGMENT = 3.0


def _request(url):
    request = Request(url, headers={
        'Accept': 'application/json',
        # A plain python user-agent gets fingerprint-blocked by more than one
        # CDN, and a 403 there reads like a permissions problem rather than
        # what it is.
        'User-Agent': 'plugin.video.youtube (Kodi)',
    })
    return json.loads(urlopen(request, timeout=TIMEOUT).read().decode('utf-8'))


def fetch(video_id, categories=DEFAULT_CATEGORIES, private=True):
    """
    Sponsor segments for one video, as a list of (start, end, category).

    private sends only the first four characters of the video id's hash and
    picks this video out of the answer here, so the service is never told
    which video is being watched. It costs a larger response - a few hundred
    videos share a prefix - and nothing else.

    An empty list is the normal answer for most videos. The service replies
    404 when nothing has been submitted, which is not an error.
    """
    query = {'categories': json.dumps(list(categories))}

    if private:
        prefix = sha256(video_id.encode('utf-8')).hexdigest()[:4]
        url = '{0}/{1}?{2}'.format(API, prefix, urlencode(query))
    else:
        query['videoID'] = video_id
        url = '{0}?{1}'.format(API, urlencode(query))

    try:
        data = _request(url)
    except Exception:
        # No segments, no network, service down - all the same here. Playback
        # carries on either way, so nothing is worth interrupting it for.
        return []

    if private:
        found = [entry for entry in data if entry.get('videoID') == video_id]
        data = found[0].get('segments') or [] if found else []

    segments = []
    for entry in data:
        span = entry.get('segment') or []
        if len(span) != 2:
            continue
        start, end = float(span[0]), float(span[1])
        if end - start < MIN_SEGMENT:
            continue
        segments.append((start, end, entry.get('category') or 'sponsor'))

    segments.sort()
    return segments


def find(segments, position):
    """
    The segment containing this position, if any.

    A small lead-in is allowed because playback is only sampled once a second,
    so the position has usually passed the start by the time it is seen.
    """
    for start, end, category in segments:
        if start - 1.0 <= position < end - 1.0:
            return start, end, category
    return None
