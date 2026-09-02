# -*- coding: utf-8 -*-
"""

    Copyright (C) 2014-2016 bromix (plugin.video.youtube)
    Copyright (C) 2016-2025 plugin.video.youtube

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.
"""


from . import logging
from .constants import (
    ABORT_FLAG,
    ARTIST,
    BOOKMARK_ID,
    BUSY_FLAG,
    CHANNEL_ID,
    CONTAINER_ID,
    CONTAINER_POSITION,
    CURRENT_ITEM,
    FOLDER_URI,
    MARK_AS_LABEL,
    PLAYLIST_ID,
    PLAYLIST_ITEM_ID,
    PLAY_COUNT,
    PLUGIN_SLEEPING,
    SERVICE_RUNNING_FLAG,
    SUBSCRIPTION_ID,
    TEMP_PATH,
    TITLE,
    URI,
    VIDEO_ID,
)
from .context import XbmcContext
from .monitors import PlayerMonitor, ServiceMonitor
from .utils.file_system import rm_dir
from ..youtube.provider import Provider


__all__ = ('run',)



def _install_sabr(context, provider):
    """
    Point the stream proxy at SABR, using the add-on's own signed-in client.

    Everything here is best effort. If it cannot be set up the proxy simply
    keeps forwarding range requests, which is what it did before - a broken
    session should cost the extra minutes of playback, not playback itself.
    """
    settings = context.get_settings()
    if not settings.use_sabr():
        return

    try:
        from ..sabr.proxy import StreamServer
        from .network.http_server import RequestHandler
    except ImportError:
        logging.exception('SABR: not available')
        return

    provider_url = settings.pot_provider_url()

    def fetch_po_token(video_id):
        """
        Mint a token bound to this video.

        Minting runs Google's BotGuard payload and is slow - tens of seconds
        on a first call - so failure returns None and playback proceeds
        without one rather than blocking.
        """
        if not provider_url:
            return None
        from json import dumps, loads
        from urllib.request import Request, urlopen
        request = Request(
            provider_url.rstrip('/') + '/get_pot',
            data=dumps({'content_binding': video_id}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urlopen(request, timeout=120) as response:
                return loads(response.read().decode('utf-8')).get('poToken')
        except Exception:
            logging.exception('SABR: could not mint a proof-of-origin token')
            return None

    try:
        client = provider.get_client(context)
    except Exception:
        logging.exception('SABR: no client, leaving the range proxy in place')
        return

    RequestHandler._sabr_server = StreamServer(
        client,
        po_token_source=fetch_po_token if provider_url else None,
        log=logging.getLogger(__name__),
    )
    logging.info('SABR: stream proxy enabled (POT provider: {url!r})',
                 url=provider_url or 'none')


def run():
    context = XbmcContext()
    provider = Provider()

    monitor = ServiceMonitor(context=context)
    player = PlayerMonitor(provider=provider,
                           context=context,
                           monitor=monitor)

    _install_sabr(context, provider)

    system_version = context.get_system_version()
    logging.info(('Starting v{version}',
                  'Kodi:    v{kodi}',
                  'Python:  v{python}'),
                 version=context.get_version(),
                 kodi=str(system_version),
                 python=system_version.get_python_version())

    ui = context.get_ui()
    get_container = ui.get_container
    get_container_info = ui.get_container_info
    get_listitem_info = ui.get_listitem_info
    get_listitem_property = ui.get_listitem_property
    clear_property = ui.clear_property
    set_property = ui.set_property

    localize = context.localize

    clear_property(ABORT_FLAG)
    if ui.get_property(SERVICE_RUNNING_FLAG) == BUSY_FLAG:
        monitor.refresh_container()
    set_property(SERVICE_RUNNING_FLAG)

    # wipe add-on temp folder on updates/restarts (subtitles, and mpd files)
    rm_dir(TEMP_PATH)

    loop_period = 10
    loop_period_ms = loop_period * 1000

    httpd_idle_time_ms = 0
    httpd_idle_timeout_ms = 30000
    httpd_ping_period_ms = 60000
    httpd_restart_attempts = 0
    httpd_max_restarts = 5

    plugin_is_idle = False
    plugin_idle_time_ms = 0
    plugin_idle_timeout_ms = 30000

    active_interval_ms = 100
    idle_interval_ms = 1000

    def _get_mark_as_label(_name,
                           container_id,
                           unwatched_label=localize('history.mark.unwatched'),
                           watched_label=localize('history.mark.watched')):
        if get_listitem_info(PLAY_COUNT, container_id):
            return unwatched_label
        return watched_label

    container_id = None
    container_path = None
    container_position = None
    item_has_id = None
    plugin_item_details = {
        VIDEO_ID: {'getter': get_listitem_property, 'value': None},
        BOOKMARK_ID: {'getter': get_listitem_property, 'value': None},
        CHANNEL_ID: {'getter': get_listitem_property, 'value': None},
        PLAYLIST_ID: {'getter': get_listitem_property, 'value': None},
        PLAYLIST_ITEM_ID: {'getter': get_listitem_property, 'value': None},
        SUBSCRIPTION_ID: {'getter': get_listitem_property, 'value': None},
        '__has_id__': {'getter': None, 'value': TypeError},
        URI: {'getter': get_listitem_info, 'value': None},
        TITLE: {'getter': get_listitem_info, 'value': None},
        ARTIST: {'getter': get_listitem_info, 'value': None},
        MARK_AS_LABEL: {'getter': _get_mark_as_label, 'value': None},
    }

    while not monitor.abortRequested():
        is_idle = monitor.system_idle or monitor.get_idle_time() >= loop_period
        is_asleep = monitor.system_sleep

        if is_asleep:
            plugin_idle_time_ms = 0
            if not plugin_is_idle:
                plugin_is_idle = set_property(PLUGIN_SLEEPING)
        elif is_idle:
            if plugin_idle_time_ms >= plugin_idle_timeout_ms:
                plugin_idle_time_ms = 0
                if not plugin_is_idle:
                    plugin_is_idle = set_property(PLUGIN_SLEEPING)
        else:
            plugin_idle_time_ms = 0
            if plugin_is_idle:
                plugin_is_idle = clear_property(PLUGIN_SLEEPING)

        if not monitor.httpd:
            httpd_idle_time_ms = 0
        elif is_asleep:
            httpd_idle_time_ms = 0
            monitor.shutdown_httpd(on_idle=True, player=player)
        elif is_idle:
            if monitor.httpd_sleep_allowed:
                if httpd_idle_time_ms >= httpd_idle_timeout_ms:
                    httpd_idle_time_ms = 0
                    monitor.shutdown_httpd(on_idle=True, player=player)
            elif monitor.httpd_sleep_allowed is None:
                monitor.httpd_sleep_allowed = True
                httpd_idle_time_ms = 0
        else:
            if httpd_idle_time_ms >= httpd_ping_period_ms:
                httpd_idle_time_ms = 0
                if monitor.ping_httpd():
                    httpd_restart_attempts = 0
                elif httpd_restart_attempts < httpd_max_restarts:
                    monitor.restart_httpd()
                    httpd_restart_attempts += 1
                else:
                    monitor.shutdown_httpd(terminate=True)

        container = get_container(container_type=False)
        check_item = not plugin_is_idle and all(container.values())
        if check_item:
            wait_interval_ms = active_interval_ms
        else:
            wait_interval_ms = idle_interval_ms
        wait_interval = wait_interval_ms / 1000
        wait_time_ms = 0

        while not monitor.abortRequested():
            if (not monitor.httpd
                    and not monitor.system_sleep
                    and not (monitor.system_idle
                             or monitor.get_idle_time() >= loop_period)):
                monitor.system_idle = False
                monitor.system_sleep = False
                monitor.interrupt = True

            if monitor.refresh and all(container.values()):
                monitor.refresh_container(force=True)
                break

            if (monitor.interrupt
                    or (not check_item and wait_time_ms >= idle_interval_ms)):
                monitor.interrupt = False
                container = get_container(container_type=False)
                if check_item != all(container.values()):
                    check_item = not check_item
                    if check_item:
                        wait_interval_ms = active_interval_ms
                    else:
                        wait_interval_ms = idle_interval_ms
                    wait_interval = wait_interval_ms / 1000

            if check_item:
                _id = container['id']
                if container_id != _id:
                    container_id = _id
                    set_property(CONTAINER_ID, container_id)
                    container_position = None

                _path = container[FOLDER_URI]
                if container_path != _path:
                    container_path = _path
                    container_position = None

                _position = get_container_info(CURRENT_ITEM, container_id)
                if _position and _position != container_position:
                    _item_has_id = None
                    for name, detail in plugin_item_details.items():
                        value = detail['value']
                        if value is TypeError:
                            if _item_has_id is None:
                                container = get_container(container_type=False)
                                if check_item != all(container.values()):
                                    check_item = not check_item
                                    break
                                _item_has_id = False
                            continue
                        if _item_has_id is not False:
                            new_value = detail['getter'](name, container_id)
                        else:
                            new_value = None
                        if new_value:
                            if new_value != value:
                                detail['value'] = new_value
                                set_property(name, new_value)
                            _item_has_id = True
                        elif value:
                            detail['value'] = None
                            clear_property(name)
                    else:
                        container_position = _position
                        if _item_has_id:
                            set_property(CONTAINER_POSITION, container_position)
                        elif item_has_id:
                            clear_property(CONTAINER_POSITION)
                        item_has_id = _item_has_id

            elif not plugin_is_idle and not container['is_plugin']:
                plugin_is_idle = set_property(PLUGIN_SLEEPING)

            monitor.waitForAbort(wait_interval)
            wait_time_ms += wait_interval_ms
            httpd_idle_time_ms += wait_interval_ms
            plugin_idle_time_ms += wait_interval_ms

            if wait_time_ms >= loop_period_ms:
                break
        else:
            break

    set_property(ABORT_FLAG)
    clear_property(SERVICE_RUNNING_FLAG)

    # clean up any/all playback monitoring threads
    player.cleanup_threads(only_ended=False)

    # shutdown http server
    if monitor.httpd:
        monitor.shutdown_httpd(terminate=True)

    provider.tear_down()
    context.tear_down()
