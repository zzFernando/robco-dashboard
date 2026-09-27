"""One sampler thread owns collector history; HTTP requests read cached snapshots."""
import copy
import logging
import threading
import time

import psutil

from collectors.agents import collect_agents
from collectors.git import collect_git
from collectors.system import collect_system
from collectors.usage import UsageCollector
from collectors.weather import collect_weather
from collectors.media import collect_media
from services.events import new_log, record_changes

_lock = threading.Lock()
_ready = threading.Event()
_thread = None
_snapshot = None


def _sample_forever(root):
    global _snapshot
    previous = {}
    events = new_log()
    usage_collectors = {name: UsageCollector() for name in ('codex', 'claude')}
    psutil.cpu_percent(interval=None)  # Prime in the same thread as later samples.
    while True:
        started = time.monotonic()
        current = {'timestamp': int(time.time()), 'errors': []}
        for name, collect in (
            ('agents', lambda: collect_agents(previous.get('agents'))),
            ('git', lambda: collect_git(root)),
            ('system', lambda: collect_system(root)),
            ('weather', collect_weather),
        ):
            try:
                current[name] = collect()
            except Exception:
                logging.exception('Collector failed: %s', name)
                current[name] = previous.get(name, {})
                current['errors'].append(name)
        try:
            current['system']['media'] = collect_media()
        except Exception:
            current['system']['media'] = {'available': False, 'title': None, 'artist': None,
                                          'album': None, 'player': None, 'status': 'UNKNOWN'}
        for name, agent in current['agents'].items():
            try:
                agent['usage'] = usage_collectors[name].collect(name, agent, current['timestamp'])
                if agent['online'] and agent['usage']['status'] != 'UNKNOWN':
                    agent['status'] = agent['usage']['status']
            except Exception:
                logging.exception('Usage collector failed: %s', name)
                agent['usage'] = {'available': False, 'partial': True}
                current['errors'].append(name + '_usage')
        record_changes(events, previous, current)
        public = copy.deepcopy(current)
        for agent in public['agents'].values():
            for key in list(agent):
                if key.startswith('_'):
                    agent.pop(key)
        public['git'].pop('_fingerprint', None)
        public['events'] = list(events)
        with _lock:
            _snapshot = public
        _ready.set()
        previous = current
        time.sleep(max(0.1, 3 - (time.monotonic() - started)))


def get_state(root):
    global _thread
    with _lock:
        if _thread is None:
            _thread = threading.Thread(target=_sample_forever, args=(root,), daemon=True)
            _thread.start()
    if not _ready.wait(10):
        return None
    with _lock:
        return copy.deepcopy(_snapshot)
