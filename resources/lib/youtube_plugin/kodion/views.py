# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 kodi-youtube-martyedition

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.

    Which view a listing should open in.

    A plugin hands Kodi a directory and the skin decides how it looks, so this
    add-on has never expressed a preference - a wall of YouTube thumbnails and
    a list of filenames are the same thing to it. They are not: every item
    carries one 16:9 image, which is what a wall view exists for.

    View ids belong to the skin rather than to Kodi, so the mapping is per
    skin, and a skin that is not listed gets no opinion at all instead of a
    wrong one.
"""

ESTUARY = 'skin.estuary'

# Read off skin.estuary's own MyVideoNav.xml on the Kodi 22 box rather than
# remembered: <views>504,50,51,52,53,54,55,500,501,502</views>
#   504 MediaList   50 List      51 Poster    52 IconWall   53 Shift
#   54  InfoWall    55 WideList  500 Wall     501 Banner    502 FanArt
VIEWS = {
    ESTUARY: {
        # Videos only. Menus are glyphs rather than artwork, and a wall of
        # glyphs is worse than the list it replaced, so they keep the skin's
        # own default until there is a reason to think otherwise.
        'videos': 500,
    },
}


def view_for(skin_id, content_type):
    """The view id to open this content in, or None to leave the skin alone."""
    if not skin_id or not content_type:
        return None
    return VIEWS.get(skin_id, {}).get(content_type)
