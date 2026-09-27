"""Live browser smoke check for local weather and decoded city photograph."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1024, 'height': 748})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8080')
    page.wait_for_timeout(12000)
    print(page.evaluate('''() => {
      var img = document.getElementById('location-map');
      return {weather: Object.keys(window.robcoWeather()), location: window.robcoWeather().location,
        width: img.naturalWidth, className: img.className, display: getComputedStyle(img).display,
        src: img.src.slice(0,80), bounds: img.getBoundingClientRect().toJSON()};
    }'''))
    print('Errors:', errors)
    page.screenshot(path='artifacts/city-photo-check.png')
    assert page.locator('#location-map').evaluate('(img) => img.naturalWidth > 0')
    assert page.locator('#location-map').is_visible()
    assert not errors
    # If the optional location script fails, the primary telemetry must still
    # display weather and decode a real JPEG, as required on the old tablet.
    fallback = browser.new_page(viewport={'width': 1024, 'height': 748})
    fallback.route('**/static/location.js*', lambda route: route.abort())
    fallback.goto('http://127.0.0.1:8080')
    fallback.wait_for_function("document.getElementById('location-map').naturalWidth > 0", timeout=45000)
    assert fallback.locator('#location-map').is_visible()
    assert fallback.locator('[data-field="weather.location"]').first.inner_text() != 'LOCALIZANDO...'
    print('PASS: photo and city also load with location.js blocked')
    browser.close()
