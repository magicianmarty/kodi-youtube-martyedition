![](resources/media/icon.png)

# YouTube — Marty Edition

A fork of [plugin.video.youtube](https://github.com/anxdpanic/plugin.video.youtube)
that targets **Kodi 22 (Piers) and nothing else**.

![License](https://img.shields.io/badge/license-GPL--2.0--only-success.svg)
![Kodi Version](https://img.shields.io/badge/kodi-22%20(piers)-success.svg)

## This is a separate project

The original is by **anxdpanic**, **bromix** and **MoojMidge**, and is where
essentially all of this code comes from. It supports Kodi 18 through 22 and
Python 2.7 through 3.14, it is the version most people should install, and it
is the one to support:

* [anxdpanic/plugin.video.youtube](https://github.com/anxdpanic/plugin.video.youtube)
* [Support thread](https://ytaddon.page.link/forum) · [Wiki](https://github.com/anxdpanic/plugin.video.youtube/wiki)

This edition is maintained separately by **magicianmarty**. Bugs here are not
upstream's problem — report them here. Fixes that are not specific to Piers get
offered upstream, because that is where they help everyone.

## What it is for

Supporting five Kodi releases and two major Python versions costs the upstream
project a compatibility layer in every module. This fork spends that budget on
one box instead: a CoreELEC 22 machine on a television, driven by a remote.

That means shims for Kodi versions this will never run on are deleted rather
than maintained, and the tests only have to describe one Python.

## What's different so far

| | |
|---|---|
| **Piers only** | `kodion/compatibility` went from 352 lines to 128. The Python 2 half and the Kodi 18/19 date branch cannot execute on Piers, which ships Python 3.14 — so `os.process_cpu_count()` replaces the old `sched_getaffinity`/`cpu_count` ladder, and 102 dead `from __future__` imports are gone. |
| **A test suite** | Upstream has six CI workflows and no tests. There are 29 here, run on Python 3.14 against Kodi stubs, plus a workflow to run them on every push. |
| **A `NameError` on channel URLs** | Resolving a channel by URL called `match.group(CHANNEL_ID)` with a name that was never imported in that file, so it raised every time. Fixed, and worth sending upstream. |

## Requirements

Kodi 22 (Piers) or newer. Older Kodi will not run this — install upstream instead.

## Development

The add-on is importable off a Kodi box, which is what makes the suite possible:
`tests/kodistubs/` stands in for `xbmc` and friends, and `tests/__init__.py`
puts them on the path before anything under `resources/lib` is imported.

```sh
pip install -r requirements-test.txt
python3 -m pytest tests -q
python3 -m flake8 --count .
```

Two things worth knowing before adding to it:

* **A stub that lies about the Kodi version is worse than no stub.** The first
  version of `tests/kodistubs/xbmcgui.py` had no `ListItem.setDateTime`, which
  is exactly the attribute `kodion.compatibility` probes to tell Kodi 20+ from
  Kodi 18. The tests would have pinned the wrong date format and looked green.
* **flake8 is set to runtime faults only** — undefined names, syntax, duplicate
  definitions. Unused imports and locals are upstream's business; rewriting
  them costs merge conflicts and buys nothing on the box. That narrow gate is
  what caught the `CHANNEL_ID` bug.

## Credits

Everything of substance here is upstream's work, by **anxdpanic**, **bromix**
and **MoojMidge**, and the contributors to
[plugin.video.youtube](https://github.com/anxdpanic/plugin.video.youtube).

## License

[GPL-2.0-only](LICENSE), the same as upstream. GPL-2.0-**only** cannot be
relicensed under GPL-3.0, so this fork keeps it.
