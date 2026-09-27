from collections import deque


def record_changes(events, previous, current):
    """Append transitions once per sample. First sample establishes Git baseline."""
    for name, agent in current['agents'].items():
        before = previous.get('agents', {}).get(name)
        if (before is None and agent['online']) or (before is not None and before['online'] != agent['online']):
            append_event(events, current['timestamp'], name.upper(), 'ONLINE' if agent['online'] else 'OFFLINE')
    before = previous.get('git', {})
    after = current['git']
    if before.get('available') and after.get('available'):
        if before.get('_fingerprint') != after.get('_fingerprint'):
            append_event(events, current['timestamp'], 'GIT', 'WORKTREE CHANGED // %s CHANGES' % after['changes'])
        if before.get('commit') != after.get('commit'):
            append_event(events, current['timestamp'], 'GIT', 'COMMIT CHANGED // %s' % (after['commit'] or 'UNKNOWN'))


def append_event(events, timestamp, source, message):
    events.append({'id': events[-1]['id'] + 1 if events else 1,
                   'timestamp': timestamp, 'source': source, 'message': message})


def new_log():
    return deque(maxlen=50)
