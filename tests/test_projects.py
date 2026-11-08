import json
from pathlib import Path
import tempfile
import unittest

from manager import Manager, ManagerError


class SidebarProjectsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        (self.home / '.codex').mkdir(parents=True)
        self.first = self.root / 'folder-a'
        self.second = self.root / 'folder-b'
        self.first.mkdir()
        self.second.mkdir()
        self.file = self.home / '.codex/.codex-global-state.json'
        self.manager = Manager(self.root / 'data', self.home)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, projects, order=None):
        self.file.write_text(json.dumps({'local-projects': projects, 'project-order': order or []}, ensure_ascii=False), encoding='utf-8')

    def test_sidebar_names_order_multiroot_dedup_and_read_only(self):
        self.write({'a': {'name': '侧边栏名称', 'rootPaths': [str(self.first), str(self.second)]},
                    'b': {'name': '重复路径', 'rootPaths': [str(self.second)]}}, ['b', 'a'])
        self.manager.register(str(self.first))
        before = self.file.read_bytes()
        result = self.manager.inventory()
        self.assertEqual(result['projects'], [str(self.second), str(self.first)])
        self.assertEqual(result['projectDetails'][0]['name'], '重复路径')
        self.assertEqual(result['projectDetails'][1]['name'], '侧边栏名称 / folder-a')
        self.assertTrue(all(p['source'] == 'codex' for p in result['projectDetails']))
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(self.manager.state['projects'], [str(self.first)])

    def test_sync_reflects_added_renamed_and_removed_projects(self):
        self.write({'a': {'name': '原名', 'rootPaths': [str(self.first)]}})
        self.assertEqual(self.manager.inventory()['codexProjectCount'], 1)
        self.write({'b': {'name': '新名', 'rootPaths': [str(self.second)]}})
        result = self.manager.inventory()
        self.assertEqual(result['projects'], [str(self.second)])
        self.assertEqual(result['projectDetails'][0]['name'], '新名')

    def test_sidebar_project_can_receive_skill_without_registration(self):
        self.write({'a': {'name': '项目', 'rootPaths': [str(self.first)]}})
        source = self.root / 'new-skill'
        source.mkdir()
        (source / 'SKILL.md').write_text('---\nname: demo\ndescription: test\n---')
        plan = self.manager.plan(dict(operation='import', path=str(source)))
        self.manager.apply(plan['token'])
        skill = self.manager.inventory()['skills'][0]
        plan = self.manager.plan(dict(operation='install', skillId=skill['id'], scope='project', project=str(self.first)))
        self.manager.apply(plan['token'])
        self.assertTrue((self.first / '.agents/skills/new-skill/SKILL.md').exists())
        self.assertEqual(self.manager.state['projects'], [])

    def test_removed_project_rejected_at_apply(self):
        self.write({'a': {'name': '项目', 'rootPaths': [str(self.first)]}})
        source = self.home / '.agents/skills/demo'
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text('custom')
        item = self.manager.inventory()['skills'][0]
        plan = self.manager.plan(dict(operation='install', skillId=item['id'], scope='project', project=str(self.first)))
        self.write({})
        with self.assertRaises(ManagerError):
            self.manager.apply(plan['token'])
        self.assertFalse((self.first / '.agents').exists())

    def test_missing_project_marked_unavailable_and_not_writable(self):
        missing = self.root / 'missing'
        self.write({'a': {'name': '已移动', 'rootPaths': [str(missing)]}})
        result = self.manager.inventory()
        self.assertFalse(result['projectDetails'][0]['available'])
        with self.assertRaises(ManagerError):
            self.manager.destination('project', str(missing), 'skill')
        self.assertFalse(missing.exists())

    def test_invalid_state_keeps_manual_projects(self):
        self.manager.register(str(self.first))
        for content in ('{', '[]', '{"local-projects": []}'):
            self.file.write_text(content)
            result = self.manager.inventory()
            self.assertEqual(result['projects'], [str(self.first)])
            self.assertTrue(result['warnings'])

    def test_cloud_remote_and_official_paths_excluded(self):
        self.write({'system': {'rootPaths': [str(self.home / '.codex/plugins/cache')]},
                    'g-p-cloud': {'rootPaths': [str(self.first)]},
                    'remote': {'rootPaths': ['relative/path', '//server/share']}})
        self.assertEqual(self.manager.inventory()['projects'], [])


if __name__ == '__main__':
    unittest.main()
