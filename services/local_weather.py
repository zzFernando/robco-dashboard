"""Host-side weather and city lookup for legacy tablets."""
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from collectors.weather import collect_weather

_places = {}

def local_weather(latitude=None, longitude=None):
    key = (latitude, longitude)
    try:
        cached = _places.get(key)
        if cached and cached[0] > time.time():
            place = cached[1]
        else:
            url = 'https://ipwho.is/' if latitude is None else 'https://nominatim.openstreetmap.org/reverse?' + urlencode(dict(lat=latitude, lon=longitude, format='jsonv2', zoom=10))
            with urlopen(Request(url, headers={'User-Agent': 'RobcoDashboard/1.0 (personal weather display)'}), timeout=8) as response:
                data = json.load(response)
            if latitude is None:
                if not data.get('success') or not data.get('city'):
                    raise ValueError('Location unavailable')
                place = dict(city=data['city'], region=data.get('region', ''), latitude=data['latitude'], longitude=data['longitude'])
            else:
                address = data.get('address', {})
                city = address.get('city') or address.get('town') or address.get('village') or address.get('municipality')
                if not city:
                    raise ValueError('City unavailable')
                place = dict(city=city, region=address.get('state', ''), latitude=latitude, longitude=longitude)
            if len(_places) > 64:
                _places.clear()
            _places[key] = (time.time() + 3600, place)
        weather = collect_weather(latitude=place['latitude'], longitude=place['longitude'], name=place['city'])
        return dict(weather, region=place['region'], approximate=latitude is None)
    except (OSError, ValueError, TypeError, KeyError):
        return {'available': False, 'location': 'LOCAL INDISPONIVEL'}
