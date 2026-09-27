"""Optional browser verification: pip install playwright; uses installed Chrome.

Run the Flask server first, then python tests/check_browser.py.
No browser library or test fixture is shipped to the display client.
"""
import copy
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = 'http://127.0.0.1:8080'


def check_fit(page, height=768):
    dimensions = page.evaluate('''() => ({
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
        viewport: innerHeight,
        outside: Array.from(document.querySelectorAll('.view:not(.hidden) .row, .view:not(.hidden) h2, .view:not(.hidden) .event, .view:not(.hidden) .note, .view:not(.hidden) .pager')).filter(n => {
          const b = n.getBoundingClientRect(), c = document.getElementById('content').getBoundingClientRect();
          return b.bottom > c.bottom + 1 || b.right > c.right + 1;
        }).map(n => n.textContent)
    })''')
    assert dimensions['width'] == 1024 and dimensions['height'] == height, dimensions
    assert not dimensions['outside'], dimensions


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    context = browser.new_context(viewport={'width': 1024, 'height': 768}, has_touch=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(URL)
    page.wait_for_selector('#boot', state='hidden')
    page.wait_for_function("document.getElementById('connection').textContent === 'CONNECTION [ONLINE]'")
    snapshot = context.request.get(URL + '/api/status').json()
    fixture = copy.deepcopy(snapshot)
    fixture['events'] = [{'id': i, 'timestamp': snapshot['timestamp'] + i,
                          'source': 'TEST', 'message': 'FIXTURE TRANSITION %s' % i} for i in range(50)]
    fixture['agents']['codex']['project'] = 'very-long-project-name-' * 8
    page.route('**/api/status?*', lambda route: route.fulfill(json=fixture))
    page.wait_for_function("document.getElementById('log-count').textContent.indexOf('50 RECORDS') === 0")
    assert page.locator('#recent-events .event').count() == 6
    for height in (768, 672):
        page.set_viewport_size({'width': 1024, 'height': height})
        for name in ('status', 'agents', 'system', 'log'):
            page.locator('#tab-' + name).tap()
            assert page.locator('#view-' + name).is_visible()
            check_fit(page, height)
        print('All four screens fit 1024x%s, including full event fixtures' % height)
    page.set_viewport_size({'width': 1024, 'height': 768})
    for key, name in enumerate(('status', 'agents', 'system', 'log'), 1):
        page.keyboard.press('F%s' % key)
        assert page.locator('#view-' + name).is_visible()
    page.locator('#log-older').click()
    assert 'PAGE 2 /' in page.locator('#log-page').inner_text()
    page.locator('#theme').click()
    assert page.locator('body').get_attribute('class') == 'amber'
    page.reload()
    page.wait_for_selector('#boot', state='hidden')
    assert page.locator('body').get_attribute('class') == 'amber'
    page.locator('#theme').click()
    page.unroute('**/api/status?*')
    host = page.locator('[data-field="system.host"]').first.inner_text()
    page.route('**/api/status?*', lambda route: route.abort())
    page.wait_for_function("document.getElementById('connection').textContent === 'CONNECTION [LOST]'")
    assert page.locator('[data-field="system.host"]').first.inner_text() == host
    page.locator('#tab-system').click()
    assert page.locator('#view-system').is_visible()
    page.unroute('**/api/status?*')
    page.wait_for_function("document.getElementById('connection').textContent === 'CONNECTION [ONLINE]'")
    page.locator('#fullscreen').click()
    page.wait_for_function('!!document.fullscreenElement')
    page.locator('#fullscreen').click()
    page.wait_for_function('!document.fullscreenElement')
    print('Touch, F1-F4, log paging, theme persistence, offline retention, reconnect, fullscreen: PASS')
    page.locator('#tab-status').click()
    Path('artifacts').mkdir(exist_ok=True)
    page.screenshot(path='artifacts/terminal-1024x768.png')
    page.locator('#tab-agents').click()
    check_fit(page)
    page.screenshot(path='artifacts/agents-1024x768.png')
    # Simulate unavailable legacy APIs and storage without altering production code.
    legacy = context.new_page()
    legacy.on('pageerror', lambda error: errors.append(str(error)))
    legacy.add_init_script('''
      Object.defineProperty(window, 'localStorage', {get: function(){throw new Error('Storage unavailable');}});
      Object.defineProperty(navigator, 'wakeLock', {value: undefined});
      Element.prototype.requestFullscreen = undefined;
      Element.prototype.webkitRequestFullscreen = undefined;
      Element.prototype.webkitRequestFullScreen = undefined;
    ''')
    legacy.goto(URL)
    legacy.wait_for_selector('#boot', state='hidden')
    legacy.locator('#fullscreen').click()
    assert legacy.locator('#display-help').is_visible()
    assert 'Tela de Início' in legacy.locator('#display-reason').inner_text()
    legacy.locator('#display-help-close').click()
    legacy.locator('#awake').click()
    assert 'bloqueio' in legacy.locator('#display-reason').inner_text()
    legacy.locator('#display-help-close').click()
    legacy.locator('#theme').click()
    assert legacy.locator('body').get_attribute('class') == 'amber'
    print('Unavailable fullscreen/wake lock/localStorage fallbacks: PASS')
    assert not errors, errors
    print('JavaScript runtime errors: 0')
    browser.close()
