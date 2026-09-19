import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('runner', Path(__file__).parents[1]/'scripts/run_task.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Agent:
    def __init__(self, url, goal, screenshots=False):
        self.url, self.closed, self.ticks = url, False, 0
        self.browser = self
        self.target, self.session = 'owned', 'session'
        self.state = {'page': {}}
        self.calls = []
    def evaluate(self, expression):
        return {'url': self.url, 'text': 'Current evidence', 'frames': [
            {'url': 'https://example.org/tickets', 'srcdoc': False}]}
    def observe(self, screenshot=False):
        return {'url': self.url, 'title': 'Tickets', 'text': 'Sunday full', 'actions': []}
    def snapshot(self):
        return {'status': 'ready', 'history': []}
    def command(self, name):
        self.ticks += 1
        return {'status': 'done', 'history': []}
    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
    def close(self):
        self.closed = True

class Tests(unittest.TestCase):
    def args(self, *extra):
        mode = [] if '--inspect-only' in extra else ['--allow-actions']
        return m.parser().parse_args(['--url', 'https://example.org', '--goal', 'Inspect Sunday', *mode, *extra])
    def test_inspection_has_no_decision_calls(self):
        a = Agent('https://example.org', '')
        result, code = m.run(self.args('--inspect-only'), lambda *x, **k: a)
        self.assertEqual((code, a.ticks, result['status']), (0, 0, 'inspected'))
        self.assertTrue(a.closed)
    def test_frame_handoff_and_viewport_refresh(self):
        agents = []
        def factory(*args, **kwargs):
            a = Agent(*args, **kwargs); agents.append(a); return a
        result, code = m.run(self.args('--frame-index', '0', '--expect-frame-url', 'https://example.org/tickets', '--viewport-height', '2400',
                                      '--inspect-only'), factory)
        self.assertEqual([a.url for a in agents], ['https://example.org', 'https://example.org/tickets'])
        self.assertTrue(all(a.closed for a in agents))
        self.assertEqual(agents[1].calls[0][1]['height'], 2400)
        self.assertEqual(agents[1].state['page']['text'], 'Sunday full')
        self.assertEqual(result['frame_handoff']['frame_index'], 0)
    def test_reject_non_navigable_frames(self):
        for frame in [{'url': 'javascript:alert(1)'}, {'url': ''},
                      {'url': 'https://user:pass@example.org'},
                      {'url': 'https://example.org', 'srcdoc': True}]:
            with self.assertRaises(ValueError):
                m.frame_url({'frames': [frame]}, 0)
        for index in [-1, 1]:
            with self.assertRaises(ValueError):
                m.frame_url({'frames': [{'url': 'https://example.org'}]}, index)
    def test_no_false_done(self):
        result, code = m.run(self.args('--expect-text', 'available'), Agent)
        self.assertEqual((code, result['verification']), (2, 'failed'))
    def test_fresh_checks_pass(self):
        result, code = m.run(self.args('--expect-text', 'Sunday full'), Agent)
        self.assertEqual((code, result['verification']), (0, 'passed'))
    def test_reject_session_mutation_before_import(self):
        self.assertEqual(m.main(['--inspect-only', '--session-id', 'unused', '--frame-index', '0', '--expect-frame-url', 'https://example.org/tickets']), 1)

if __name__ == '__main__':
    unittest.main()
