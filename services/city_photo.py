"""Small JPEG city photos served locally for legacy tablet browsers."""
import base64
import json
import re
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

_cache = {}


def city_photo(city, region):
    original_city = city
    if 'porto alegre' in city.casefold():
        city = 'Porto Alegre'
        region = 'Rio Grande do Sul'
    key = (city, region)
    if key in _cache and _cache[key][0] > time.time():
        return _cache[key][1]
    landmark = 'Usina do Gasometro' if city.casefold() == 'porto alegre' and region.casefold() == 'rio grande do sul' else ''
    subject = '"Usina do Gasometro"' if landmark else '"%s" "%s" (landmark OR panorama OR skyline OR monument OR cathedral OR waterfront)' % (city.replace('"', ''), region.replace('"', ''))
    query = subject + ' filetype:bitmap -flag -bandeira -brasao -coat -map -logo'
    params = dict(action='query', format='json', generator='search',
                  gsrnamespace=6, gsrlimit=10, gsrsearch=query,
                  prop='imageinfo', iiprop='url|mime|size', iiurlwidth=640)
    result = {'available': False}
    try:
        req = Request('https://commons.wikimedia.org/w/api.php?' + urlencode(params),
                      headers={'User-Agent': 'RobcoDashboard/1.0 (local city photo display)'})
        with urlopen(req, timeout=10) as response:
            pages = json.load(response).get('query', {}).get('pages', {}).values()
        for page in sorted(pages, key=lambda p: p.get('index', 999)):
            if re.search(r'flag|bandeira|bras[aã]o|coat.of.arms|mapa?|logo|seal', page.get('title', ''), re.I):
                continue
            info = (page.get('imageinfo') or [{}])[0]
            if info.get('mime') != 'image/jpeg' or info.get('width', 0) < info.get('height', 0):
                continue
            url = info.get('thumburl', '')
            if urlparse(url).hostname not in ('upload.wikimedia.org', 'thumb.wikimedia.org') or not url.startswith('https://'):
                continue
            try:
                with urlopen(Request(url, headers={'User-Agent': 'RobcoDashboard/1.0'}), timeout=8) as response:
                    content = response.read(1500001)
                if len(content) > 1500000 or not content.startswith(b'\xff\xd8\xff'):
                    continue
                result = {'available': True, 'photo': 'data:image/jpeg;base64,' + base64.b64encode(content).decode('ascii'),
                          'source': info.get('descriptionurl', ''), 'title': page['title'], 'landmark': landmark}
                break
            except (OSError, ValueError):
                continue
    except (OSError, ValueError, TypeError):
        pass
    if not result['available'] and region.casefold() == 'rio grande do sul' and city.casefold() != 'porto alegre':
        fallback = city_photo('Porto Alegre', 'Rio Grande do Sul')
        if fallback.get('available'):
            fallback = dict(fallback)
            fallback['landmark'] = 'Usina do Gasometro (referencia regional)'
            result = fallback
    if len(_cache) >= 32:
        _cache.clear()
    _cache[key] = (time.time() + (86400 if result['available'] else 60), result)
    return result
