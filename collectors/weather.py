import json
import os
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_LAT = -23.5505
DEFAULT_LON = -46.6333
_cache = {'value': None, 'expires': 0}
_local_caches = {}


def _number(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def collect_weather(now=None, latitude=None, longitude=None, name=None):
    now = int(time.time()) if now is None else now
    if latitude is None:
        latitude = _number('WEATHER_LAT', DEFAULT_LAT)
        longitude = _number('WEATHER_LON', DEFAULT_LON)
        name = os.environ.get('WEATHER_NAME', 'SAO PAULO')
        cache = _cache
    else:
        key = (latitude, longitude, name)
        if len(_local_caches) > 64:
            _local_caches.clear()
        cache = _local_caches.setdefault(key, {'value': None, 'expires': 0})
    if cache['value'] is not None and now < cache['expires']:
        return cache['value']
    result = {'available': False, 'location': name, 'temperature_c': None,
              'feels_like_c': None, 'condition': 'UNKNOWN', 'humidity_percent': None,
              'wind_kmh': None, 'rain_mm': None, 'updated_at': None,
              'high_c': None, 'low_c': None,
              'latitude': latitude, 'longitude': longitude}
    try:
        query = urlencode({'latitude': latitude, 'longitude': longitude,
                           'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m',
                           'daily': 'temperature_2m_max,temperature_2m_min',
                           'forecast_days': 1, 'timezone': 'auto'})
        request = Request('https://api.open-meteo.com/v1/forecast?%s' % query,
                          headers={'User-Agent': 'ROBCO-Dashboard/1.0'})
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode('utf-8'))
        current = payload.get('current') or {}
        daily = payload.get('daily') or {}
        codes = {0: 'CLEAR', 1: 'MAINLY CLEAR', 2: 'PARTLY CLOUDY', 3: 'OVERCAST',
                 45: 'FOG', 48: 'RIME FOG', 51: 'DRIZZLE', 53: 'DRIZZLE', 55: 'DRIZZLE',
                 61: 'RAIN', 63: 'RAIN', 65: 'HEAVY RAIN', 71: 'SNOW', 73: 'SNOW',
                 75: 'HEAVY SNOW', 80: 'SHOWERS', 81: 'SHOWERS', 82: 'HEAVY SHOWERS',
                 95: 'THUNDERSTORM', 96: 'THUNDERSTORM', 99: 'THUNDERSTORM'}
        result.update({'available': True, 'temperature_c': current.get('temperature_2m'),
                       'feels_like_c': current.get('apparent_temperature'),
                       'condition': codes.get(current.get('weather_code'), 'UNKNOWN'),
                       'humidity_percent': current.get('relative_humidity_2m'),
                       'wind_kmh': current.get('wind_speed_10m'),
                       'rain_mm': current.get('precipitation'), 'updated_at': now,
                       'high_c': (daily.get('temperature_2m_max') or [None])[0],
                       'low_c': (daily.get('temperature_2m_min') or [None])[0]})
        cache.update(value=result, expires=now + 600)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        if cache['value'] is not None:
            return dict(cache['value'], stale=True)
    return result
