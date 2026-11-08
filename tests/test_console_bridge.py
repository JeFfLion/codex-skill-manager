import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import patch
from manager import Manager
from server import create_server
from integration.sidebar.mcp_server import console_request


class ConsoleBridgeTests(unittest.TestCase):
    def test_embedded_read_plan_apply_and_detail_share_http_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'home'
            skill = home / '.agents/skills/demo'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: demo\ndescription: Test\n---\nHello')
            project = root / 'project'
            project.mkdir()
            manager = Manager(root / 'data', home)
            manager.register(str(project))
            server = create_server(0, manager)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with patch('launcher.ensure_console', return_value=f'http://127.0.0.1:{server.server_port}/'), patch('webbrowser.open') as browser:
                    state = console_request({'path': 'state'})
                    self.assertNotIn('token', state)
                    skill_id = state['skills'][0]['id']
                    plan = console_request({'path': 'plan', 'body': {'operation': 'install', 'skillId': skill_id, 'scope': 'project', 'project': str(project)}})
                    console_request({'path': 'apply', 'body': {'token': plan['token']}})
                    self.assertTrue((project / '.agents/skills/demo/SKILL.md').exists())
                    self.assertIn('Hello', console_request({'path': f'detail?id={skill_id}'})['content'])
                    with self.assertRaises(ValueError):
                        console_request({'path': 'detail?id=missing'})
                    browser.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_bridge_rejects_non_management_urls_and_invalid_methods(self):
        with patch('launcher.ensure_console') as ensure:
            for args in ({'path': 'http://example.com'}, {'path': '../auth.json'}, {'path': 'apply'}, {'path': 'state', 'body': {}}, {'path': 'detail?file=/secret'}):
                with self.assertRaises(ValueError):
                    console_request(args)
            ensure.assert_not_called()
