"""Read-only, incremental adapters for local Codex/Claude JSONL telemetry.

Only numerical usage and allowlisted metadata survive parsing. Conversation text,
tool arguments, results, credentials and raw records are never retained or served.
"""
import copy
import json
import math
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

TOKEN_KEYS = ('input_tokens', 'output_tokens', 'cached_input_tokens',
              'cache_write_input_tokens', 'total_tokens')
MAX_FILES = 512
READ_BUDGET = 8 * 1024 * 1024
MAX_LINE = 4 * 1024 * 1024
FRESH_SECONDS = 120
_CLAUDE_USAGE_CACHE = {'at': 0, 'limits': None}


def claude_usage_command(now):
    """Read Claude's official /usage summary, at most once per minute."""
    if now - _CLAUDE_USAGE_CACHE['at'] < 60:
        return _CLAUDE_USAGE_CACHE['limits']
    _CLAUDE_USAGE_CACHE['at'] = now
    try:
        completed = subprocess.run(['claude', '-p', '/usage', '--output-format', 'json'], capture_output=True, text=True, timeout=20, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        summary = (payload.get('result') or '').replace('\\n', '\n')
        matches = re.findall(r'(Current session|Current week[^:]*):\s*(\d+)% used · resets ([^\n]+)', summary, re.I)
        matches = re.findall(r'(Current session|Current week[^:]*):\s*(\d+)% used .* resets ([^\n]+)', summary, re.I)
        limits = {}
        for index, match in enumerate(matches[:2]):
            stamp = None
            try:
                reset = match[2].split(' (')[0] + ' ' + str(datetime.now().year)
                stamp = int(time.mktime(time.strptime(reset, '%b %d, %I:%M%p %Y')))
            except (ValueError, OverflowError):
                pass
            limits['primary' if index == 0 else 'secondary'] = {'used_percent': float(match[1]), 'window_minutes': 300 if index == 0 else 10080, 'resets_at': stamp}
        _CLAUDE_USAGE_CACHE['limits'] = limits or None
        return _CLAUDE_USAGE_CACHE['limits']
    except (OSError, ValueError, TypeError, IndexError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return _CLAUDE_USAGE_CACHE['limits']


def timestamp(value):
    try:
        if isinstance(value, str):
            return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
        if isinstance(value, (int, float)) and math.isfinite(value):
            return int(value)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def tokens(raw, agent):
    if not isinstance(raw, dict):
        return None
    inp, out = number(raw.get('input_tokens')), number(raw.get('output_tokens'))
    if inp is None or out is None:
        return None
    cached = number(raw.get('cache_read_input_tokens' if agent == 'claude' else 'cached_input_tokens'))
    written = number(raw.get('cache_creation_input_tokens' if agent == 'claude' else 'cache_write_input_tokens'))
    if agent == 'claude':
        # Claude's input excludes cache; Codex input already includes it.
        inp += (cached or 0) + (written or 0)
    return dict(zip(TOKEN_KEYS, (inp, out, cached, written, inp + out)))


def add_tokens(items):
    items = [item for item in items if item is not None]
    if not items:
        return None
    return {key: sum(item[key] for item in items) if all(item[key] is not None for item in items) else None
            for key in TOKEN_KEYS}


def local_day(stamp):
    return datetime.fromtimestamp(stamp).date().isoformat()


def safe_text(value):
    if isinstance(value, str):
        return ''.join(c for c in value if c.isprintable())[:256]
    return None


class SessionLog:
    """One append cursor and compact metadata accumulator per session file."""
    def __init__(self, path, agent):
        self.path, self.agent = path, agent
        self.offset = 0
        self.signature = None
        self.session_id = path.stem
        self.cwd = self.model = self.started = self.updated = None
        self.state = 'UNKNOWN'
        self.state_at = None
        self.total = self.last_usage = self.context_limit = None
        self.usage_at = None
        self.limits = None
        self.limits_at = None
        self.messages = {}
        self.daily = {}
        self.partial = False
        self.caught_up = False
        self.seen_usage = False
        self.skip_line = False
        self.forked = False
        self.subagent = 'subagents' in path.parts

    def read(self, budget):
        stat = self.path.stat()
        signature = (stat.st_dev, stat.st_ino)
        if self.signature != signature or stat.st_size < self.offset:
            self.__init__(self.path, self.agent)
            self.signature = signature
        consumed = 0
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            while consumed < budget:
                line_start = stream.tell()
                line = stream.readline(min(MAX_LINE + 1, budget - consumed))
                if not line:
                    break
                consumed += len(line)
                if self.skip_line:
                    self.skip_line = not line.endswith(b'\n')
                    self.offset = stream.tell()
                    continue
                if len(line) > MAX_LINE:
                    self.partial = True
                    self.skip_line = not line.endswith(b'\n')
                    self.offset = stream.tell()
                    continue
                if not line.endswith(b'\n'):
                    # Writer may be mid-record, or this sample exhausted its budget.
                    self.offset = line_start
                    break
                self.offset = stream.tell()
                try:
                    record = json.loads(line)
                    if isinstance(record, dict):
                        self.consume(record)
                except (ValueError, TypeError, AttributeError, KeyError):
                    self.partial = True
        self.caught_up = self.offset == stat.st_size
        return consumed

    def transition(self, state, stamp):
        if stamp is not None and (self.state_at is None or stamp >= self.state_at):
            self.state, self.state_at = state, stamp

    def consume(self, record):
        stamp = timestamp(record.get('timestamp'))
        if stamp is not None:
            self.updated = max(self.updated or stamp, stamp)
        if self.agent == 'codex':
            self.codex(record, stamp)
        else:
            self.claude(record, stamp)

    def codex(self, record, stamp):
        kind = record.get('type')
        payload = record.get('payload') or {}
        if kind == 'session_meta':
            self.session_id = safe_text(payload.get('id')) or self.session_id
            self.cwd = safe_text(payload.get('cwd'))
            self.started = timestamp(payload.get('timestamp'))
            self.forked = bool(payload.get('forked_from_id'))
            self.partial = self.partial or self.forked
        elif kind == 'turn_context':
            self.model = safe_text(payload.get('model')) or self.model
        elif kind == 'event_msg':
            event = payload.get('type')
            states = {'task_started': 'WORKING', 'task_complete': 'IDLE',
                      'turn_aborted': 'IDLE', 'request_user_input': 'WAITING'}
            if event in states:
                self.transition(states[event], stamp)
            if event == 'token_count':
                info = payload.get('info') or {}
                usage = tokens(info.get('total_token_usage'), 'codex')
                if usage is not None:
                    self.update_codex_tokens(usage, stamp)
                self.last_usage = tokens(info.get('last_token_usage'), 'codex') or self.last_usage
                self.context_limit = number(info.get('model_context_window')) or self.context_limit
                limits = payload.get('rate_limits')
                if isinstance(limits, dict) and limits.get('limit_id') in (None, 'codex'):
                    cleaned = {}
                    for name in ('primary', 'secondary'):
                        window = limits.get(name)
                        if isinstance(window, dict) and number(window.get('used_percent')) is not None:
                            cleaned[name] = {key: number(window.get(key)) for key in
                                             ('used_percent', 'window_minutes', 'resets_at')}
                    if cleaned:
                        self.limits, self.limits_at = cleaned, stamp
        elif kind == 'token_usage_record':
            # Newer Codex logs record cumulative totals here too. Replacing the
            # total (not summing snapshots) avoids counting both formats twice.
            usage = tokens(payload.get('thread_token_usage'), 'codex')
            if usage is not None:
                self.update_codex_tokens(usage, stamp)
            self.last_usage = tokens(payload.get('usage'), 'codex') or self.last_usage
        elif kind == 'response_item':
            event = payload.get('type')
            if event in ('function_call', 'custom_tool_call'):
                waiting = payload.get('name') in ('request_user_input', 'functions.request_user_input')
                self.transition('WAITING' if waiting else 'WORKING', stamp)
            elif event in ('function_call_output', 'custom_tool_call_output'):
                self.transition('WORKING', stamp)
            elif event == 'message' and payload.get('role') == 'assistant' and payload.get('phase') == 'final':
                self.transition('IDLE', stamp)

    def update_codex_tokens(self, usage, stamp):
        previous = self.total
        if previous is not None and usage['total_tokens'] < previous['total_tokens']:
            # Ignore a delayed/lower snapshot. Replacing the baseline here would
            # count its recovery again. A true reset remains explicitly partial.
            self.partial = True
            return
        self.total, self.usage_at, self.seen_usage = usage, stamp, True
        if stamp is None or self.forked:
            return
        delta = {key: max(0, usage[key] - (previous[key] or 0)) if previous and usage[key] is not None
                 else usage[key] for key in TOKEN_KEYS}
        day = local_day(stamp)
        self.daily[day] = add_tokens([self.daily.get(day), delta])

    def claude(self, record, stamp):
        self.session_id = safe_text(record.get('sessionId')) or self.session_id
        self.cwd = safe_text(record.get('cwd')) or self.cwd
        if stamp is not None:
            self.started = min(self.started or stamp, stamp)
        kind = record.get('type')
        message = record.get('message') or {}
        if kind == 'assistant':
            self.model = safe_text(message.get('model')) or self.model
            usage = tokens(message.get('usage'), 'claude')
            identity = message.get('id')
            if usage is not None and isinstance(identity, str):
                # One API response may be logged as several content blocks.
                old = self.messages.get(identity)
                if old is None or usage['total_tokens'] >= old[0]['total_tokens']:
                    self.messages[identity] = (usage, stamp)
                self.last_usage, self.usage_at, self.seen_usage = usage, stamp, True
            reason = message.get('stop_reason')
            if reason in ('end_turn', 'stop_sequence'):
                self.transition('IDLE', stamp)
            elif reason == 'tool_use':
                content = message.get('content') or []
                waiting = any(isinstance(block, dict) and block.get('type') == 'tool_use'
                              and block.get('name') == 'AskUserQuestion' for block in content)
                self.transition('WAITING' if waiting else 'WORKING', stamp)
        elif kind == 'user' and not record.get('isMeta'):
            self.transition('WORKING', stamp)
        elif kind == 'system' and record.get('subtype') == 'turn_duration':
            self.transition('IDLE', stamp)

    def usage(self):
        return add_tokens([item[0] for item in self.messages.values()]) if self.agent == 'claude' else self.total

    def today(self, day):
        if self.agent == 'claude':
            return add_tokens([usage for usage, stamp in self.messages.values()
                               if stamp is not None and local_day(stamp) == day])
        return self.daily.get(day)


class UsageCollector:
    """Caches discovery and append offsets; owned by the single sampler thread."""
    def __init__(self):
        self.logs = {}
        self.discovered_at = 0
        self.roots = None
        self.discovery_partial = False

    def collect(self, agent, process, now=None):
        now = int(time.time()) if now is None else now
        variable = 'CODEX_HOME' if agent == 'codex' else 'CLAUDE_CONFIG_DIR'
        suffix = 'sessions' if agent == 'codex' else 'projects'
        homes = [Path.home() / ('.codex' if agent == 'codex' else '.claude')]
        homes += [Path(value) for value in process.get('_log_homes', [])]
        if os.environ.get(variable):
            homes.append(Path(os.environ[variable]))
        roots = tuple(sorted({str(home / suffix) for home in homes}))
        if roots != self.roots or now - self.discovered_at >= 30:
            self.discover(roots, agent)
            self.roots, self.discovered_at = roots, now
        budget, readable, partial = READ_BUDGET, [], self.discovery_partial
        for log in self.logs.values():
            try:
                if budget > 0:
                    budget -= log.read(budget)
                else:
                    log.caught_up = log.offset == log.path.stat().st_size
                readable.append(log)
                partial = partial or log.partial or not log.caught_up
            except OSError:
                partial = True
        # Mirrored homes may contain the same session. Choose one copy.
        unique = {}
        for log in readable:
            old = unique.get(log.session_id)
            if old is None or (log.updated or 0) > (old.updated or 0):
                unique[log.session_id] = log
        logs = list(unique.values())
        day = local_day(now)
        if agent == 'claude':
            # Forked/resumed transcripts can repeat a response across files too.
            messages = {}
            for log in logs:
                for identity, item in log.messages.items():
                    old = messages.get(identity)
                    if old is None or item[0]['total_tokens'] >= old[0]['total_tokens']:
                        messages[identity] = item
            daily = add_tokens([usage for usage, stamp in messages.values()
                                if stamp is not None and local_day(stamp) == day])
        else:
            daily = add_tokens([log.today(day) for log in logs])
        if daily is None and any(log.seen_usage for log in logs) and not partial:
            daily = {key: 0 for key in TOKEN_KEYS}
        paths = {os.path.normcase(os.path.normpath(p)) for p in process.get('_directories', [])}
        eligible = [log for log in logs if not log.subagent and log.updated is not None]
        matching = [log for log in eligible if log.cwd and os.path.normcase(os.path.normpath(log.cwd)) in paths]
        selected = max(matching or eligible, key=lambda log: log.updated or 0, default=None)
        result = {'available': selected is not None, 'source': agent + ' local JSONL',
                  'scope': 'MATCHED DIRECTORY' if matching else 'LATEST LOG',
                  'partial': bool(partial), 'session_id': None, 'session_tokens': None,
                  'today_tokens': daily, 'today_date': day,
                  'today_sessions': sum(log.today(day) is not None for log in logs),
                  'observed_working_sessions': None, 'model': None, 'project': None,
                  'updated_at': None, 'stale': True, 'status': 'UNKNOWN',
                  'context_used': None, 'context_limit': None, 'context_percent': None,
                  'rate_limits': None, 'limits_updated_at': None, 'limits_stale': True}
        if selected is None:
            return result
        recent = selected.updated is not None and 0 <= now - selected.updated <= FRESH_SECONDS
        matched = selected in matching and process.get('online') and selected.caught_up
        fallback_model = selected.model or next((log.model for log in sorted(logs, key=lambda item: item.updated or 0, reverse=True) if log.model), None)
        fallback_cwd = selected.cwd or next((log.cwd for log in sorted(logs, key=lambda item: item.updated or 0, reverse=True) if log.cwd), None)
        result.update(session_id=selected.session_id, session_tokens=selected.usage(),
                      model=fallback_model, project=Path(fallback_cwd).name if fallback_cwd else None,
                      updated_at=selected.updated, stale=not recent,
                      status=selected.state if matched and recent else 'UNKNOWN',
                      context_used=selected.last_usage['input_tokens'] if selected.last_usage else None,
                      context_limit=selected.context_limit,
                      rate_limits=copy.deepcopy(selected.limits), limits_updated_at=selected.limits_at)
        if agent == 'claude':
            official_limits = claude_usage_command(now)
            if official_limits:
                result['rate_limits'] = official_limits
                result['limits_updated_at'] = now
        if matched:
            result['observed_working_sessions'] = sum(log.state == 'WORKING' and log.caught_up
                and log.updated is not None and 0 <= now - log.updated <= FRESH_SECONDS for log in matching)
        if result['context_used'] is not None and result['context_limit']:
            result['context_percent'] = round(100 * result['context_used'] / result['context_limit'], 1)
        # Historical percentages remain visible but explicitly marked stale.
        result['limits_stale'] = selected.limits_at is None or now - selected.limits_at > 600 or any(
            window.get('resets_at') is not None and window['resets_at'] <= now
            for window in (selected.limits or {}).values())
        return result

    def discover(self, roots, agent):
        candidates, self.discovery_partial = {}, False
        def failed(error):
            if not isinstance(error, FileNotFoundError):
                self.discovery_partial = True
        for root in roots:
            for directory, _, files in os.walk(root, onerror=failed):
                for name in files:
                    if name.endswith('.jsonl'):
                        path = Path(directory) / name
                        try:
                            candidates[str(path.resolve())] = (path, path.stat().st_mtime)
                        except OSError:
                            self.discovery_partial = True
        ordered = sorted(candidates.values(), key=lambda item: item[1], reverse=True)
        self.discovery_partial = self.discovery_partial or len(ordered) > MAX_FILES
        self.logs = {str(path): self.logs.get(str(path)) or SessionLog(path, agent)
                     for path, _ in ordered[:MAX_FILES]}
