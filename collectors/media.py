"""Best-effort Windows media session reader.

The Windows session API may be unavailable in a service, headless session, or
older Windows build. In that case the collector returns UNKNOWN and never fails
the main telemetry sample.
"""
import asyncio
import threading

_art_lock = threading.Lock()
_art_cache = {'key': None, 'data': None, 'content_type': None}


async def _read_thumbnail(thumbnail_ref):
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
    stream = await thumbnail_ref.open_read_async()
    size = stream.size
    if not size:
        return None, None
    buffer = Buffer(size)
    await stream.read_async(buffer, size, InputStreamOptions.READ_AHEAD)
    reader = DataReader.from_buffer(buffer)
    data = bytearray(size)
    reader.read_bytes(data)
    return bytes(data), stream.content_type or 'image/jpeg'


async def _get_session():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    return manager.get_current_session()


async def _read_session():
    session = await _get_session()
    if session is None:
        return None
    properties = await session.try_get_media_properties_async()
    playback = session.get_playback_info()
    timeline = session.get_timeline_properties()
    status_value = getattr(playback, 'playback_status', None)
    status = getattr(status_value, 'name', None) or str(status_value or 'UNKNOWN').split('.')[-1].upper()
    title = properties.title or None
    artist = properties.artist or properties.album_artist or None
    has_art = False
    key = (title, artist)
    with _art_lock:
        cached_key = _art_cache['key']
    if properties.thumbnail is not None:
        if cached_key == key and _art_cache['data'] is not None:
            has_art = True
        else:
            try:
                data, content_type = await _read_thumbnail(properties.thumbnail)
            except Exception:
                data, content_type = None, None
            if data:
                with _art_lock:
                    _art_cache['key'] = key
                    _art_cache['data'] = data
                    _art_cache['content_type'] = content_type
                has_art = True
    else:
        with _art_lock:
            if cached_key == key:
                has_art = _art_cache['data'] is not None
    duration_s = timeline.end_time.total_seconds() - timeline.start_time.total_seconds()
    return {
        'available': True,
        'title': title,
        'artist': artist,
        'album': properties.album_title or None,
        'player': session.source_app_user_model_id or None,
        'status': status,
        'has_art': has_art,
        'position_seconds': timeline.position.total_seconds(),
        'duration_seconds': duration_s if duration_s > 0 else None,
        'can_play_pause': True,
    }


def collect_media():
    try:
        value = asyncio.run(_read_session())
        if value is not None:
            return value
    except (ImportError, OSError, RuntimeError, AttributeError, TypeError):
        pass
    return {'available': False, 'title': None, 'artist': None, 'album': None,
            'player': None, 'status': 'UNKNOWN', 'has_art': False,
            'position_seconds': None, 'duration_seconds': None, 'can_play_pause': False}


async def _control(action):
    session = await _get_session()
    if session is None:
        return False
    methods = {
        'play': 'try_play_async', 'pause': 'try_pause_async',
        'toggle': 'try_toggle_play_pause_async',
        'next': 'try_skip_next_async', 'prev': 'try_skip_previous_async',
    }
    method = getattr(session, methods.get(action, ''), None)
    if method is None:
        return False
    return bool(await method())


def control_media(action):
    try:
        return asyncio.run(_control(action))
    except (ImportError, OSError, RuntimeError, AttributeError, TypeError):
        return False


def get_album_art():
    """Return (bytes, content_type) for the most recently cached album art, or (None, None)."""
    with _art_lock:
        return _art_cache['data'], _art_cache['content_type']
