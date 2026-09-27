import copy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import psutil

from collectors.agents import collect_agents, identify_agent
from collectors.git import collect_git
from services.events import new_log, record_changes


class AgentTests(unittest.TestCase):
    def test_exact_process_names_and_known_runtime_scripts(self):
        self.assertEqual(identify_agent('codex.exe', []), 'codex')
        self.assertEqual(identify_agent('node', ['node', '/x/@anthropic-ai/claude-code/cli.js']), 'claude')
        self.assertIsNone(identify_agent('python.exe', ['python', 'codex-report.py']))
        self.assertIsNone(identify_agent('powershell.exe', ['powershell', 'echo claude']))
        self.assertIsNone(identify_agent('node', ['node', 'server.js', 'codex']))

    def process(self, cpu=1, started=100, pid=12):
        process = Mock(pid=pid, info={'name': 'codex.exe', 'cmdline': []})
        process.create_time.return_value = started
        process.cwd.return_value = str(Path.cwd())
        process.cpu_times.return_value = (cpu, 0)
        return process

    def test_activity_requires_observed_cpu_delta(self):
        process = self.process()
        with patch('collectors.agents.psutil.process_iter', return_value=[process]):
            first = collect_agents(now=200)
            self.assertIsNone(first['codex']['last_activity'])
            self.assertEqual(first['codex']['session_seconds'], 100)
            self.assertEqual(first['codex']['status'], 'UNKNOWN')
            self.assertIsNone(first['codex']['action'])
            same = collect_agents(first, now=203)
            self.assertIsNone(same['codex']['last_activity'])
            process.cpu_times.return_value = (2, 0)
            active = collect_agents(same, now=206)
            self.assertEqual(active['codex']['last_activity'], 206)
            process.create_time.return_value = 205
            restarted = collect_agents(first, now=209)
            self.assertIsNone(restarted['codex']['last_activity'])

    def test_denied_metadata_does_not_hide_presence(self):
        process = self.process()
        process.cwd.side_effect = psutil.AccessDenied(12)
        process.create_time.side_effect = psutil.AccessDenied(12)
        with patch('collectors.agents.psutil.process_iter', return_value=[process]):
            agent = collect_agents(now=200)['codex']
        self.assertTrue(agent['online'])
        self.assertIsNone(agent['project'])
        self.assertIsNone(agent['session_seconds'])

    def test_multiple_directories_are_not_reported_as_one_project(self):
        first, second = self.process(), self.process(pid=13)
        second.cwd.return_value = '/different'
        with patch('collectors.agents.psutil.process_iter', return_value=[first, second]):
            agent = collect_agents(now=200)['codex']
        self.assertEqual(agent['process_count'], 2)
        self.assertIsNone(agent['working_directory'])


class EventTests(unittest.TestCase):
    def state(self):
        return {'timestamp': 100, 'agents': {'codex': {'online': True}},
                'git': {'available': True, '_fingerprint': 'a', 'changes': 1, 'commit': 'a'}}

    def test_initial_online_without_fake_git_transitions_and_no_duplicates(self):
        events, state = new_log(), self.state()
        record_changes(events, {}, state)
        record_changes(events, state, state)
        self.assertEqual([event['message'] for event in events], ['ONLINE'])

    def test_same_count_different_worktree_and_commit_and_offline(self):
        events, old = new_log(), self.state()
        new = copy.deepcopy(old)
        new['agents']['codex']['online'] = False
        new['git'].update(_fingerprint='b', commit='b')
        record_changes(events, old, new)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]['message'], 'OFFLINE')
        record_changes(events, new, new)
        self.assertEqual(len(events), 3)

    def test_log_is_bounded_and_ids_do_not_repeat(self):
        events, state = new_log(), self.state()
        for number in range(70):
            next_state = copy.deepcopy(state)
            next_state['agents']['codex']['online'] = not state['agents']['codex']['online']
            record_changes(events, state, next_state)
            state = next_state
        self.assertEqual(len(events), 50)
        self.assertEqual(events[0]['id'], 21)
        self.assertEqual(events[-1]['id'], 70)


class GitTests(unittest.TestCase):
    def test_failed_status_is_not_clean(self):
        with patch('collectors.git._git', side_effect=['main', None, 'abc']):
            self.assertFalse(collect_git('.') ['available'])

    def test_unborn_repository_is_available_with_null_commit(self):
        with patch('collectors.git._git', side_effect=['main', '?? file.py', None]):
            result = collect_git('.')
        self.assertTrue(result['available'])
        self.assertIsNone(result['commit'])
        self.assertEqual(result['changes'], 1)


class RouteTests(unittest.TestCase):
    def test_api_and_assets(self):
        from app import app
        with app.test_client() as client:
            for route in ('/', '/static/terminal.css', '/static/terminal.js'):
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
                response.close()
            response = client.get('/api/status')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            data = response.get_json()
            self.assertIn('uptime_seconds', data['system'])
            self.assertIn('temperature_c', data['system'])
            self.assertIn('media', data['system'])
            self.assertIn('weather', data)
            self.assertIn('events', data)
            self.assertNotIn('_fingerprint', data['git'])
            for agent in data['agents'].values():
                self.assertNotIn('_samples', agent)
                self.assertIsNone(agent['action'])


if __name__ == '__main__':
    unittest.main()
