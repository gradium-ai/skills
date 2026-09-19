import contextlib
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from test_runner import m, Agent

class SecurityTests(unittest.TestCase):
    def main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = m.main(argv)
        return code, out.getvalue()

    def test_default_does_not_start_browser(self):
        with patch.dict(sys.modules, {'jev_ultrafast': types.SimpleNamespace(Agent=lambda *a, **k: self.fail('browser started'))}):
            code, output = self.main(['--url', 'https://example.org', '--goal', 'Go'])
        self.assertEqual(code, 1)
        self.assertIn('exactly one', output)

    def test_default_omits_sensitive_content(self):
        secret = 'fixture-private-value'
        result = {'status':'done', 'verification':'passed', 'page':{'url':'https://example.org/'+secret, 'text':secret},
                  'controls':[{'value':secret}], 'inspection':{'frames':[{'url':secret}]},
                  'checks':[{'kind':'url','passed':True,'expected':secret}]}
        self.assertNotIn(secret, str(m.output_result(result)))

    def test_values_need_second_opt_in(self):
        result={'controls':[{'label':'Email','value':'person@example.org'}],
                'inspection':{'fields':[{'value':'person@example.org'}]}}
        self.assertNotIn('person@example.org', str(m.output_result(result, True)))
        self.assertIn('person@example.org', str(m.output_result(result, True, True)))
        self.assertIn('value', result['controls'][0])

    def test_url_parsing_rejects_ambiguous_inputs(self):
        for url in ['https://example.org\\@evil.test', 'https://@example.org',
                    'https://example.org\n/path', ' https://example.org',
                    'https://example.org:99999', 'file:///tmp/private', 'javascript:alert(1)']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                m.http_url(url)

    def test_frame_swap_stops_before_second_browser(self):
        args=m.parser().parse_args(['--url','https://example.org','--inspect-only',
                '--frame-index','0','--expect-frame-url','https://other.example/tickets'])
        created=[]
        def factory(*args, **kwargs):
            a=Agent(*args, **kwargs); created.append(a); return a
        with self.assertRaises(ValueError):
            m.run(args, factory)
        self.assertEqual(len(created),1)
        self.assertTrue(created[0].closed)
        self.assertEqual(created[0].ticks,0)

    def test_reject_cleartext_api_key_transport(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY':'fixture','TEXT_MODEL_API_KEY':'fixture',
                                   'TEXT_MODEL_BASE_URL':'http://example.org/v1'}):
            code, output=self.main(['--allow-actions','--url','https://example.org','--goal','Go'])
        self.assertEqual(code,1)
        self.assertIn('HTTPS', output)

    def test_private_file_not_duplicated_in_stdout(self):
        fake=types.SimpleNamespace(Agent=Agent)
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {'jev_ultrafast':fake}):
            path=Path(temp)/'result.json'
            code, output=self.main(['--inspect-only','--url','https://example.org',
                         '--include-page-content','--output',str(path)])
            self.assertEqual(code,0)
            self.assertNotIn('Current evidence',output)
            self.assertIn('Current evidence',path.read_text())
            if os.name=='posix':
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            previous=path.read_text()
            self.assertEqual(self.main(['--inspect-only','--url','https://example.org','--output',str(path)])[0],1)
            self.assertEqual(path.read_text(),previous)

    def test_symlink_output_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'target'; target.write_text('original')
            link=Path(temp)/'link'; link.symlink_to(target)
            self.assertEqual(self.main(['--inspect-only','--url','https://example.org','--output',str(link)])[0],1)
            self.assertEqual(target.read_text(),'original')

    def test_session_provider_error_not_echoed(self):
        def cdp(*a, **kw): raise ValueError('fixture-provider-secret')
        with patch.dict(sys.modules, {'browser_harness.helpers':types.SimpleNamespace(cdp=cdp)}):
            code, output=self.main(['--inspect-only','--session-id','test-session'])
        self.assertEqual(code,1)
        self.assertNotIn('fixture-provider-secret',output)

if __name__=='__main__': unittest.main()
