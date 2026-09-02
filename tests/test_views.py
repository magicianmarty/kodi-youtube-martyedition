# -*- coding: utf-8 -*-
"""
Which view a listing opens in.

The add-on hands Kodi a directory and the skin draws it, so the only lever it
has is to name a view id - and view ids belong to the skin, not to Kodi. That
makes "say nothing when you don't know the skin" the important behaviour here:
a wrong id silently switches the user to some unrelated layout.
"""

import os
import unittest

from . import REPO_ROOT
from youtube_plugin.kodion import views

SETTINGS_XML = os.path.join(REPO_ROOT, "resources", "settings.xml")
STRINGS_PO = os.path.join(REPO_ROOT, "resources", "language",
                          "resource.language.en_gb", "strings.po")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class TestViewFor(unittest.TestCase):
    def test_estuary_opens_videos_as_a_wall(self):
        self.assertEqual(500, views.view_for("skin.estuary", "videos"))

    def test_an_unknown_skin_gets_no_opinion(self):
        """A view id from one skin means something else in another."""
        self.assertIsNone(views.view_for("skin.arctic.horizon", "videos"))
        self.assertIsNone(views.view_for("skin.confluence", "videos"))

    def test_menus_keep_the_skin_default(self):
        """Menu entries are glyphs; a wall of those is worse than a list."""
        self.assertIsNone(views.view_for("skin.estuary", "files"))

    def test_missing_arguments_are_not_an_opinion(self):
        self.assertIsNone(views.view_for(None, "videos"))
        self.assertIsNone(views.view_for("skin.estuary", None))
        self.assertIsNone(views.view_for("", ""))

    def test_every_mapped_id_is_one_the_skin_offers(self):
        """
        Guards against a typo becoming a silent layout change. These are the
        ids skin.estuary lists in MyVideoNav.xml on Kodi 22.
        """
        offered = {504, 50, 51, 52, 53, 54, 55, 500, 501, 502}
        for content_type, view_id in views.VIEWS[views.ESTUARY].items():
            self.assertIn(view_id, offered,
                          "{0} maps to an id estuary does not offer".format(
                              content_type))


class TestTheSettingExists(unittest.TestCase):
    def test_the_toggle_is_declared(self):
        self.assertIn('id="kodion.view.default"', read(SETTINGS_XML))

    def test_it_is_on_by_default(self):
        """Off by default would mean the fix ships doing nothing."""
        settings = read(SETTINGS_XML)
        start = settings.index('id="kodion.view.default"')
        block = settings[start:settings.index("</setting>", start)]
        self.assertIn("<default>true</default>", block)

    def test_its_labels_resolve(self):
        strings = read(STRINGS_PO)
        for string_id in ("30825", "30826"):
            self.assertIn('msgctxt "#{0}"'.format(string_id), strings)


class TestLandscapeArt(unittest.TestCase):
    def test_every_item_builder_sets_landscape(self):
        """
        YouTube art is 16:9 and skins ask for 'landscape' when they want wide
        art. Each builder that sets a thumb should set it.
        """
        source = read(os.path.join(REPO_ROOT, "resources", "lib",
                                   "youtube_plugin", "kodion", "items",
                                   "xbmc", "xbmc_items.py"))
        self.assertEqual(source.count("art['thumb'] = image"),
                         source.count("art['landscape'] = image"))


class TestApplyContentWiring(unittest.TestCase):
    """
    The mapping being right is not the same as it reaching Kodi. This drives
    the real XbmcContext, which is what caught the first version of this
    change returning None for everything.
    """

    def context(self):
        from youtube_plugin.kodion.context.xbmc.xbmc_context import XbmcContext
        return XbmcContext(plugin_id="plugin.video.youtube")

    def test_a_video_listing_asks_for_the_wall(self):
        self.assertEqual(500, self.context().apply_content(content_type="videos"))

    def test_a_menu_asks_for_nothing(self):
        self.assertIsNone(self.context().apply_content(content_type="files"))

    def test_no_content_type_asks_for_nothing(self):
        self.assertIsNone(self.context().apply_content())

    def test_the_default_content_type_is_left_alone(self):
        """'default' means the caller explicitly wants Kodi's own behaviour."""
        self.assertIsNone(self.context().apply_content(content_type="default"))

    def test_turning_the_setting_off_stops_it(self):
        """
        Settings are cached per instance and only re-read on flush, which is
        how Kodi behaves too - so the flush is part of the behaviour under
        test, not a workaround for it.
        """
        from kodienv import ENV
        previous = ENV.settings.get("kodion.view.default")
        ENV.settings["kodion.view.default"] = "false"
        try:
            context = self.context()
            context.get_settings().flush(fill=True)
            self.assertIsNone(context.apply_content(content_type="videos"))
        finally:
            ENV.settings["kodion.view.default"] = previous
            self.context().get_settings().flush(fill=True)


class TestStubFidelity(unittest.TestCase):
    def test_unset_settings_report_their_declared_default(self):
        """
        Kodi answers an unset setting with the default from settings.xml. A
        stub that answers "" makes every unset boolean look deliberately
        disabled - which is how the wiring above first appeared to work and
        did not.
        """
        from kodienv import ENV
        self.assertEqual("true", ENV.settings.get("kodion.view.default"))
        self.assertTrue(len(ENV.settings) > 50)
