import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from collectors.usage import SessionLog, UsageCollector, local_day, tokens


def usage(inp=100, out=10, cache=50):
    return {'input_tokens': inp, 'output_tokens': out, 'cached_input_tokens': cache,
            'cache_write_input_tokens': 0, 'total_tokens': inp + out}


def event(kind, payload, stamp):
    return {'type': kind, 'payload': payload,
            'timestamp': datetime.fromtimestamp(stamp, timezone.utc).isoformat()}


class UsageTests(unittest.TestCase):
    def test_cache_is_not_double_counted(self):
        self.assertEqual(tokens(usage(), 'codex')['total_tokens'], 110)
        claude = tokens({'input_tokens': 10, 'output_tokens': 3,
                         'cache_read_input_tokens': 50, 'cache_creation_input_tokens': 20}, 'claude')
        self.assertEqual(claude['input_tokens'], 80)
        self.assertEqual(claude['total_tokens'], 83)
        self.assertIsNone(tokens({'input_tokens': -1, 'output_tokens': 10}, 'codex'))
        self.assertIsNone(tokens({}, 'codex'))

    def test_codex_snapshots_and_new_record_do_not_double_count(self):
        log = SessionLog(Path('session.jsonl'), 'codex')
        now = int(time.time())
        first = event('event_msg', {'type': 'token_count', 'info': {'total_token_usage': usage()}}, now)
        log.consume(first)
        log.consume(first)
        log.consume(event('token_usage_record', {'thread_token_usage': usage()}, now))
        self.assertEqual(log.usage()['total_tokens'], 110)
        self.assertEqual(log.today(local_day(now))['total_tokens'], 110)
        log.consume(event('token_usage_record', {'thread_token_usage': usage(200, 30)}, now))
        self.assertEqual(log.today(local_day(now))['total_tokens'], 230)

    def test_daily_delta_excludes_previous_day(self):
        log = SessionLog(Path('session.jsonl'), 'codex')
        now = int(time.time())
        log.consume(event('token_usage_record', {'thread_token_usage': usage()}, now - 86400))
        log.consume(event('token_usage_record', {'thread_token_usage': usage(200, 30)}, now))
        self.assertEqual(log.today(local_day(now))['total_tokens'], 120)

    def test_delayed_lower_snapshot_cannot_double_daily_tokens(self):
        log = SessionLog(Path('session.jsonl'), 'codex')
        now = int(time.time())
        for inp in (200, 100, 200, 210):
            log.consume(event('token_usage_record', {'thread_token_usage': usage(inp, 10)}, now))
        self.assertEqual(log.today(local_day(now))['total_tokens'], 220)
        self.assertTrue(log.partial)

    def test_claude_multiple_blocks_one_response(self):
        log = SessionLog(Path('session.jsonl'), 'claude')
        stamp = datetime.now(timezone.utc).isoformat()
        record = {'type': 'assistant', 'timestamp': stamp, 'sessionId': 'session',
                  'message': {'id': 'response-1', 'usage': {'input_tokens': 20,
                  'output_tokens': 10, 'cache_read_input_tokens': 40,
                  'cache_creation_input_tokens': 5}, 'stop_reason': 'end_turn'}}
        log.consume(record)
        log.consume(record)
        self.assertEqual(log.usage()['total_tokens'], 75)
        record['message']['usage']['output_tokens'] = 15
        log.consume(record)
        self.assertEqual(log.usage()['total_tokens'], 80)
        self.assertEqual(log.state, 'IDLE')
        record['message']['stop_reason'] = 'tool_use'
        record['message']['content'] = [{'type': 'tool_use', 'name': 'AskUserQuestion', 'input': 'PRIVATE'}]
        log.consume(record)
        self.assertEqual(log.state, 'WAITING')
        self.assertNotIn('PRIVATE', repr(log.__dict__))

    def test_partial_line_append_corruption_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            record = event('token_usage_record', {'thread_token_usage': usage()}, int(time.time()))
            encoded = json.dumps(record).encode()
            path.write_bytes(encoded[:30])
            log = SessionLog(path, 'codex')
            log.read(10000)
            self.assertEqual(log.offset, 0)
            self.assertIsNone(log.usage())
            with path.open('ab') as stream:
                stream.write(encoded[30:] + b'\n')
            log.read(10000)
            self.assertEqual(log.usage()['total_tokens'], 110)
            log.read(10000)
            self.assertEqual(log.today(local_day(int(time.time())))['total_tokens'], 110)
            with path.open('ab') as stream:
                stream.write(b'{malformed}\n')
            log.read(10000)
            self.assertTrue(log.partial)
            path.write_bytes(b'{}\n')
            log.read(10000)
            self.assertIsNone(log.usage())

    def test_no_logs_remains_unknown(self):
        with tempfile.TemporaryDirectory() as directory, patch('collectors.usage.Path.home', return_value=Path(directory)), patch.dict(os.environ, {}, clear=True):
            result = UsageCollector().collect('codex', {})
            self.assertFalse(result['available'])
            self.assertIsNone(result['today_tokens'])

    def test_directory_matching_freshness_limits_and_private_fields(self):
        with tempfile.TemporaryDirectory() as directory, patch('collectors.usage.Path.home', return_value=Path(directory)), patch.dict(os.environ, {}, clear=True):
            root = Path(directory) / '.codex' / 'sessions'
            root.mkdir(parents=True)
            now = int(time.time())
            records = [event('session_meta', {'id': 'abc', 'cwd': directory}, now),
                       event('event_msg', {'type': 'task_started'}, now),
                       event('event_msg', {'type': 'token_count', 'info': {
                           'total_token_usage': usage(), 'last_token_usage': usage(),
                           'model_context_window': 1000}, 'rate_limits': {'primary': {
                           'used_percent': 40, 'window_minutes': 300, 'resets_at': now + 60}}}, now),
                       event('response_item', {'type': 'message', 'role': 'user', 'content': 'SECRET TEST TEXT'}, now)]
            (root / 'session.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
            collector = UsageCollector()
            process = {'online': True, '_directories': [directory]}
            fresh = collector.collect('codex', process, now)
            self.assertEqual(fresh['status'], 'WORKING')
            self.assertEqual(fresh['context_percent'], 10)
            self.assertFalse(fresh['limits_stale'])
            self.assertNotIn('SECRET TEST TEXT', json.dumps(fresh))
            self.assertTrue(collector.collect('codex', process, now + 70)['limits_stale'])
            stale = collector.collect('codex', process, now + 200)
            self.assertEqual(stale['status'], 'UNKNOWN')
            self.assertTrue(stale['stale'])
            mismatch = collector.collect('codex', {'online': True, '_directories': ['/other']}, now)
            self.assertEqual(mismatch['status'], 'UNKNOWN')
            self.assertEqual(mismatch['scope'], 'LATEST LOG')

    def test_claude_daily_deduplicates_copied_responses(self):
        with tempfile.TemporaryDirectory() as directory, patch('collectors.usage.Path.home', return_value=Path(directory)), patch.dict(os.environ, {}, clear=True):
            root = Path(directory) / '.claude' / 'projects'
            root.mkdir(parents=True)
            record = {'type': 'assistant', 'timestamp': datetime.now(timezone.utc).isoformat(),
                      'message': {'id': 'same-response', 'usage': {'input_tokens': 100, 'output_tokens': 10}}}
            for name in ('a', 'b'):
                record['sessionId'] = name
                (root / (name + '.jsonl')).write_text(json.dumps(record) + '\n')
            result = UsageCollector().collect('claude', {})
            self.assertEqual(result['today_tokens']['total_tokens'], 110)


if __name__ == '__main__':
    unittest.main()
