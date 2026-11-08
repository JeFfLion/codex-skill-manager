from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from integration.sidebar import mcp_server
from setup_sidebar import ROOT, build, register, MARKET, PLUGIN
from server import create_server


class SidebarTests(unittest.TestCase):
    def test_console_port_cannot_be_claimed_by_second_server(self):
        server = create_server(0)
        try:
            with self.assertRaises(OSError):
                create_server(server.server_port)
        finally:
            server.server_close()

    def test_global_entrypoint_and_private_launch_tool(self):
        with patch.object(mcp_server, 'launch') as launch:
            result = mcp_server.dispatch('tools/list', {})
            mcp_server.dispatch('resources/read', {'uri': mcp_server.URI})
            mcp_server.dispatch('tools/call', {'name': mcp_server.TOOL})
            launch.assert_not_called()
        self.assertEqual(result['tools'][0]['_meta']['openai/ui']['entrypoints'], [{'type': 'global'}])
        self.assertEqual(result['tools'][1]['_meta']['ui']['visibility'], ['app'])

    def test_launch_only_on_explicit_tool_call_and_no_arbitrary_arguments(self):
        with patch.object(mcp_server, 'launch', return_value='http://127.0.0.1:8765/') as launch:
            result = mcp_server.dispatch('tools/call', {'name': mcp_server.LAUNCH})
            self.assertIn('url', result['structuredContent'])
            launch.assert_called_once()
            with self.assertRaises(ValueError):
                mcp_server.dispatch('tools/call', {'name': mcp_server.LAUNCH, 'arguments': {'command': 'other'}})

    def test_existing_tabs_can_read_fixed_ui_using_previous_resource_uri(self):
        for uri in mcp_server.LEGACY_URIS:
            result = mcp_server.dispatch('resources/read', {'uri': uri})
            resource = result['contents'][0]
            self.assertEqual(resource['uri'], uri)
            self.assertEqual(resource['text'], mcp_server.dispatch('resources/read', {'uri': mcp_server.URI})['contents'][0]['text'])

    def test_stdio_discovery_is_valid_json_without_side_effects(self):
        messages = [dict(jsonrpc='2.0', id=1, method='initialize', params={'protocolVersion': '2025-06-18'}),
                    dict(jsonrpc='2.0', method='notifications/initialized'),
                    dict(jsonrpc='2.0', id=2, method='tools/list'),
                    dict(jsonrpc='2.0', id=3, method='resources/read', params={'uri': mcp_server.URI})]
        result = subprocess.run([sys.executable, str(ROOT / 'integration/sidebar/mcp_server.py')],
                                input='\n'.join(json.dumps(m) for m in messages) + '\n',
                                text=True, encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        results = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in results], [1, 2, 3])
        self.assertIn('tools', results[1]['result'])
        self.assertTrue('data-embedded' in results[2]['result']['contents'][0]['text'])

    def test_build_and_registration_preserve_existing_settings_and_are_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '中文项目'
            home = Path(directory) / 'home'
            shutil.copytree(ROOT / 'integration/sidebar', root / 'integration/sidebar')
            package = build(root)
            data = json.loads((package / 'mcp.json').read_text(encoding='utf-8'))
            self.assertEqual(data['mcpServers']['skill_console']['command'], 'python')
            legacy = json.loads((package / '.mcp.json').read_text(encoding='utf-8'))
            self.assertEqual(legacy['mcpServers']['skill_console']['command'], sys.executable)
            self.assertEqual(data['mcpServers']['skill_console']['env']['SKILL_WORKSPACE_ROOT'], str(root.resolve()))
            config = home / '.codex/config.toml'
            config.parent.mkdir(parents=True)
            original = '# Keep this\nmodel = "example"\n[plugins.other]\nenabled = true\n'
            config.write_text(original)
            register(root, home)
            first = config.read_text(encoding='utf-8')
            register(root, home)
            self.assertEqual(config.read_text(encoding='utf-8'), first)
            self.assertTrue(first.startswith(original.rstrip()))
            state = tomllib.loads(first)
            self.assertEqual(state['marketplaces'][MARKET]['source'], root.as_posix())
            self.assertTrue(state['plugins'][f'{PLUGIN}@{MARKET}']['enabled'])
            self.assertEqual(config.with_name('config.toml.before-skill-workspace-sidebar.bak').read_text(), original)

    def test_registration_refuses_unowned_conflicting_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.codex/config.toml'
            config.parent.mkdir()
            text = f'[marketplaces.{MARKET}]\nsource = "other"\n'
            config.write_text(text)
            with self.assertRaises(ValueError):
                register(ROOT, home)
            self.assertEqual(config.read_text(), text)


if __name__ == '__main__':
    unittest.main()
