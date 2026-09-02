# -*- coding: utf-8 -*-
"""
This add-on targets Kodi 22 (Piers) and nothing older.

Upstream carries shims for Kodi 18 and Python 2.7. Piers ships Python 3.14,
so that code is unreachable - and unreachable code is worse than absent code,
because it still has to be read, and it makes the modern branch look optional.
These tests are what stops it coming back on the next merge from upstream.
"""

import ast
import os
import unittest

from . import REPO_ROOT

LIB = os.path.join(REPO_ROOT, "resources", "lib")


def source_files():
    for root, dirs, names in os.walk(LIB):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def relative(path):
    return os.path.relpath(path, REPO_ROOT)


class TestNoPython2(unittest.TestCase):
    def test_no_future_imports(self):
        offenders = [
            relative(path) for path in source_files()
            if "from __future__" in read(path)
        ]
        self.assertEqual([], offenders)

    def test_no_python2_only_builtins(self):
        """basestring, unicode, xrange and friends cannot resolve on 3.14."""
        gone = {"basestring", "unicode", "xrange", "unichr", "raw_input", "long"}
        offenders = []
        for path in source_files():
            tree = ast.parse(read(path), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in gone:
                    offenders.append("{0}:{1} {2}".format(
                        relative(path), node.lineno, node.id))
        self.assertEqual([], offenders)

    def test_no_python2_module_imports(self):
        gone = {"cPickle", "StringIO", "urlparse", "BaseHTTPServer",
                "SocketServer", "urllib2", "kodi_six", "six"}
        offenders = []
        for path in source_files():
            tree = ast.parse(read(path), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    if name in gone:
                        offenders.append("{0}:{1} {2}".format(
                            relative(path), node.lineno, name))
        self.assertEqual([], offenders)

    def test_compatibility_has_no_fallback_branch(self):
        """
        The point of the module is now naming, not branching. An ImportError
        handler around the imports would mean the Python 2 half had returned.
        """
        path = os.path.join(LIB, "youtube_plugin", "kodion",
                            "compatibility", "__init__.py")
        tree = ast.parse(read(path), filename=path)
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
        self.assertEqual([], handlers)


class TestEveryModuleParses(unittest.TestCase):
    def test_all_of_it_parses_on_this_python(self):
        """
        Most of the add-on needs a running Kodi and is never imported by the
        suite, so parsing is the cheapest guard against shipping a file that
        cannot even be read on the target.
        """
        for path in source_files():
            try:
                ast.parse(read(path), filename=path)
            except SyntaxError as error:
                self.fail("{0} does not parse: {1}".format(
                    relative(path), error))
