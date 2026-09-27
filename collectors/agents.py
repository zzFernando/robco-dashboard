"""Conservative process telemetry, not task/session-log inference."""
import ntpath
import time
from pathlib import Path

import psutil

AGENTS = ('codex', 'claude')


def identify_agent(name, cmdline):
    executable = ntpath.basename(name or '').lower()
    for agent in AGENTS:
        if executable in (agent, agent + '.exe'):
            return agent
    # Only inspect the script argument of a known runtime, never arbitrary text.
    if executable in ('node', 'node.exe', 'bun', 'bun.exe') and len(cmdline or []) > 1:
        script = cmdline[1].replace('\\', '/').lower()
        if script.endswith('/@openai/codex/bin/codex.js'):
            return 'codex'
        if script.endswith('/@anthropic-ai/claude-code/cli.js'):
            return 'claude'
    return None


def collect_agents(previous=None, now=None):
    now = int(time.time()) if now is None else now
    previous = previous or {}
    groups = {name: [] for name in AGENTS}
    for process in psutil.process_iter(['name', 'cmdline']):
        try:
            agent = identify_agent(process.info['name'], process.info['cmdline'])
            if not agent:
                continue
            item = {'pid': process.pid, 'started_at': None, 'cwd': None, 'cpu': None}
            for key, read in (
                ('started_at', process.create_time), ('cwd', process.cwd),
                ('cpu', lambda: sum(process.cpu_times()[:2])),
            ):
                try:
                    item[key] = read()
                except (psutil.Error, OSError):
                    pass
            groups[agent].append(item)
        except (psutil.Error, OSError):
            continue
    result = {}
    for agent, processes in groups.items():
        old = previous.get(agent, {})
        old_homes = old.get('_homes_by_pid', {})
        homes_by_pid = {}
        for process in processes:
            identity = (process['pid'], process['started_at'])
            if identity in old_homes:
                homes_by_pid[identity] = old_homes[identity]
                continue
            try:
                environment = psutil.Process(process['pid']).environ()
                key = 'CODEX_HOME' if agent == 'codex' else 'CLAUDE_CONFIG_DIR'
                home = environment.get(key)
                homes_by_pid[identity] = home if isinstance(home, str) else None
            except (psutil.Error, OSError):
                homes_by_pid[identity] = None
        old_samples = old.get('_samples', {})
        samples = {}
        activity = old.get('last_activity')
        for process in processes:
            identity = (process['pid'], process['started_at'])
            cpu = process['cpu']
            prior = old_samples.get(identity)
            if cpu is not None:
                samples[identity] = cpu
                if prior is not None and cpu > prior:
                    activity = now
        starts = [p['started_at'] for p in processes if p['started_at'] is not None]
        started = min(starts) if starts else None
        directories = {p['cwd'] for p in processes if p['cwd']}
        # Report a shared cwd only when every matching process can be inspected.
        cwd = next(iter(directories)) if len(directories) == 1 and all(p['cwd'] for p in processes) else None
        result[agent] = {
            'online': bool(processes),
            'status': 'UNKNOWN' if processes else 'OFFLINE',
            'project': Path(cwd).name if cwd else None,
            'working_directory': cwd,
            'action': None,
            'started_at': int(started) if started is not None else None,
            'session_seconds': max(0, int(now - started)) if started is not None else None,
            'last_activity': activity,
            'last_seen': now if processes else old.get('last_seen'),
            'process_count': len(processes),
            '_samples': samples,
            '_homes_by_pid': homes_by_pid,
            '_log_homes': sorted({home for home in homes_by_pid.values() if home}),
            '_directories': sorted(directories),
        }
    return result
