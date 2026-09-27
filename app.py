from pathlib import Path
import base64
from urllib.parse import urlencode

from flask import Flask, Response, jsonify, send_from_directory, request
from services.city_photo import city_photo
from services.local_weather import local_weather
import math

from collectors.media import control_media, get_album_art
from services.state import get_state


ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)


@app.get('/')
def index():
    response = send_from_directory(ROOT / 'web', 'index.html', max_age=0)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/static/<path:path>')
def static_files(path):
    response = send_from_directory(ROOT / 'web', path, max_age=0)
    response.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return response


@app.get('/api/album-art')
def album_art():
    data, content_type = get_album_art()
    if not data:
        return '', 404
    response = Response(data, mimetype=content_type)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/city-photo')
def photo():
    city = request.args.get('city', '').strip()
    region = request.args.get('region', '').strip()
    if not city or len(city) > 120 or len(region) > 120:
        return jsonify({'available': False}), 400
    result = dict(city_photo(city, region))
    if result.get('available'):
        result['image_url'] = '/api/city-photo/image?' + urlencode(dict(city=city, region=region))
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/city-photo/image')
def photo_image():
    city = request.args.get('city', '').strip()
    region = request.args.get('region', '').strip()
    if not city or len(city) > 120 or len(region) > 120:
        return '', 400
    result = city_photo(city, region)
    if not result.get('available'):
        return '', 404
    content = base64.b64decode(result['photo'].split(',', 1)[1])
    response = Response(content, mimetype='image/jpeg')
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@app.post('/api/media/<action>')
def media_control(action):
    if action not in ('play', 'pause', 'toggle', 'next', 'prev'):
        return jsonify({'ok': False, 'error': 'unknown action'}), 400
    ok = control_media(action)
    response = jsonify({'ok': ok})
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/local-weather')
def weather():
    lat = lon = None
    if 'lat' in request.args or 'lon' in request.args:
        try:
            lat, lon = float(request.args['lat']), float(request.args['lon'])
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError('Invalid coordinates')
            lat, lon = round(lat, 3), round(lon, 3)
        except (ValueError, KeyError):
            return jsonify({'available': False}), 400
    response = jsonify(local_weather(lat, lon))
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/status')
def status():
    state = get_state(ROOT)
    if state is not None:
        state = dict(state)
        weather_data = dict(local_weather())
        if weather_data.get('available'):
            weather_data['photo'] = '/api/city-photo/image?' + urlencode(dict(city=weather_data['location'], region=weather_data.get('region', '')))
        state['weather'] = weather_data
    response = jsonify(state if state is not None else {'error': 'INITIALIZING'})
    response.headers['Cache-Control'] = 'no-store'
    return response, 200 if state is not None else 503


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
