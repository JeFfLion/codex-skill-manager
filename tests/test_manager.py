import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from manager import Manager, ManagerError
from server import create_server


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.project = self.root / '中文项目'
        self.project.mkdir()
        self.manager = Manager(self.root / 'data', self.home)
        self.manager.register(str(self.project))
        self.source = self.home / '.codex/skills/example'
        self.source.mkdir(parents=True)
        (self.source / 'SKILL.md').write_text('---\nname: example\ndescription: A test skill\n---\nDo something.\n', encoding='utf-8')
        (self.source / 'assets').mkdir()
        (self.source / 'assets/data.bin').write_bytes(bytes(range(256)))

    def tearDown(self):
        self.temporary.cleanup()

    def source_id(self):
        return next(s['id'] for s in self.manager.inventory()['skills'] if s['path'] == str(self.source))

    def perform(self, **request):
        plan = self.manager.plan(request)
        return self.manager.apply(plan['token'])

    def test_install_preserves_resources_and_global_source(self):
        self.perform(operation='install', skillId=self.source_id(), scope='project', project=str(self.project))
        target = self.project / '.agents/skills/example'
        self.assertEqual((target / 'assets/data.bin').read_bytes(), bytes(range(256)))
        self.assertTrue(self.source.exists())

    def test_migration_and_restore(self):
        self.perform(operation='migrate', skillId=self.source_id(), project=str(self.project))
        self.assertFalse(self.source.exists())
        self.assertTrue((self.project / '.agents/skills/example/SKILL.md').is_file())
        self.assertEqual(len(self.manager.state['backups']), 1)
        backup_id = self.manager.state['backups'][0]['id']
        reloaded = Manager(self.manager.data, self.home)
        plan = reloaded.plan({'operation': 'restore', 'backupId': backup_id})
        reloaded.apply(plan['token'])
        self.assertTrue(self.source.exists())
        self.assertEqual(reloaded.state['backups'], [])

    def test_existing_target_never_overwritten(self):
        request = dict(operation='install', skillId=self.source_id(), scope='project', project=str(self.project))
        self.perform(**request)
        target = self.project / '.agents/skills/example/precious.txt'
        target.write_text('keep')
        with self.assertRaises(ManagerError):
            self.manager.plan(request)
        self.assertEqual(target.read_text(), 'keep')

    def test_changed_source_rejects_apply(self):
        plan = self.manager.plan(dict(operation='disable', skillId=self.source_id()))
        (self.source / 'new.txt').write_text('changed')
        with self.assertRaises(ManagerError):
            self.manager.apply(plan['token'])
        self.assertTrue(self.source.exists())

    def test_target_appearing_after_preview_is_preserved(self):
        plan = self.manager.plan(dict(operation='install', skillId=self.source_id(), scope='user'))
        Path(plan['target']).mkdir(parents=True)
        with self.assertRaises(ManagerError):
            self.manager.apply(plan['token'])

    def test_disable_restore_conflict(self):
        self.perform(operation='disable', skillId=self.source_id())
        self.source.mkdir()
        with self.assertRaises(ManagerError):
            self.manager.plan(dict(operation='restore', backupId=self.manager.state['backups'][0]['id']))
        self.assertEqual(len(self.manager.state['backups']), 1)

    def test_copy_failure_cleans_target_and_keeps_source(self):
        plan = self.manager.plan(dict(operation='migrate', skillId=self.source_id(), project=str(self.project)))
        with patch('manager.shutil.copytree', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.manager.apply(plan['token'])
        self.assertTrue(self.source.exists())
        self.assertFalse(Path(plan['target']).exists())

    def test_metadata_save_failure_rolls_migration_back(self):
        plan = self.manager.plan(dict(operation='migrate', skillId=self.source_id(), project=str(self.project)))
        with patch.object(self.manager, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.manager.apply(plan['token'])
        self.assertTrue((self.source / 'SKILL.md').exists())
        self.assertFalse(Path(plan['target']).exists())
        self.assertEqual(self.manager.state['backups'], [])

    def test_builtins_and_plugins_are_not_scanned_or_operable(self):
        source = self.home / '.codex/skills/.system/builtin'
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text('Built in')
        plugin = self.home / '.codex/plugins/cache/vendor/skills/plugin'
        plugin.mkdir(parents=True)
        (plugin / 'SKILL.md').write_text('Plugin')
        import hashlib
        real_metadata = __import__('manager').metadata
        with patch('manager.metadata', wraps=real_metadata) as read_metadata:
            inventory = self.manager.inventory()
        self.assertEqual(len(inventory['skills']), 1)
        self.assertEqual(read_metadata.call_count, 1)
        for folder in (source, plugin):
            skill_id = hashlib.sha256(str(folder / 'SKILL.md').encode()).hexdigest()[:24]
            for operation in ('install', 'disable', 'migrate'):
                with self.assertRaises(ManagerError):
                    self.manager.plan(dict(operation=operation, skillId=skill_id, scope='user'))
            with self.assertRaises(ManagerError):
                self.manager.plan(dict(operation='import', path=str(folder)))
            with self.assertRaises(ManagerError):
                self.manager.register(str(folder))
            self.assertTrue((folder / 'SKILL.md').exists())

    def test_old_protected_backups_cannot_be_restored(self):
        protected_target = self.home / '.codex/skills/.system/builtin'
        self.manager.state['backups'].append(dict(id='legacy', original=str(protected_target)))
        self.assertEqual(self.manager.inventory()['backups'], [])
        with self.assertRaises(ManagerError):
            self.manager.plan(dict(operation='restore', backupId='legacy'))
        self.assertFalse(protected_target.exists())

    def test_protected_paths_with_parent_segments_and_case(self):
        from manager import protected
        for path in (self.home / '.codex/skills/example/../.system/builtin',
                     self.home / '.CODEX/PLUGINS/cache/custom',
                     self.project / '.agents/skills/.system/builtin'):
            self.assertTrue(protected(path))
            with self.assertRaises(ManagerError):
                self.manager.plan(dict(operation='import', path=str(path)))

    def test_apply_rechecks_protected_paths_before_file_access(self):
        import time
        protected_path = self.home / '.codex/skills/.system/builtin'
        for source, target in ((protected_path, self.root / 'destination'),
                               (self.source, protected_path)):
            self.manager.plans['old-token'] = dict(source=str(source), target=str(target),
                expires=time.time() + 300, operation='install', checksum='unused')
            with patch('manager.digest') as checksum:
                with self.assertRaises(ManagerError):
                    self.manager.apply('old-token')
                checksum.assert_not_called()
            self.assertFalse(protected_path.exists())

    def test_import_is_not_user_activation(self):
        self.perform(operation='import', path=str(self.source))
        self.assertTrue((self.manager.library / 'example/SKILL.md').exists())
        self.assertFalse((self.home / '.agents/skills/example').exists())

    def test_unregistered_project_rejected(self):
        with self.assertRaises(ManagerError):
            self.manager.plan(dict(operation='install', skillId=self.source_id(), scope='project', project=str(self.root)))

    def test_data_cannot_be_in_skill_discovery_roots(self):
        with self.assertRaises(ManagerError):
            Manager(self.home / '.agents/skills/my-library', self.home)
        model = Manager(self.project / '.agents/skills/my-library', self.home)
        with self.assertRaises(ManagerError):
            model.register(str(self.project))

    def test_empty_and_relative_paths_rejected(self):
        for path in ('', 'relative-folder'):
            with self.assertRaises(ManagerError):
                self.manager.register(path)
            with self.assertRaises(ManagerError):
                self.manager.plan(dict(operation='import', path=path))

    def test_symlink_is_rejected(self):
        link = self.source / 'linked'
        try:
            link.symlink_to(self.project, target_is_directory=True)
        except OSError:
            self.skipTest('Windows account cannot create symlinks')
        with self.assertRaises(ManagerError):
            self.manager.plan(dict(operation='disable', skillId=self.source_id()))

    def test_http_boundary_and_valid_write(self):
        server = create_server(0, self.manager)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(url + '/api/health') as response:
                self.assertEqual(json.load(response)['service'], 'codex-skill-workspace')
            with urlopen(url + '/api/state') as response:
                state = json.load(response)
            for headers in ({}, {'X-Manager-Token': state['token'], 'Origin': 'https://evil.example'}, {'Host': 'evil.example'}):
                request = Request(url + '/api/projects', data=b'{}', headers={'Content-Type': 'application/json', **headers})
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request)
                self.assertEqual(caught.exception.code, 403)
            request = Request(url + '/api/plan', data=json.dumps(dict(operation='disable', skillId=self.source_id())).encode(), headers={'Content-Type': 'application/json', 'X-Manager-Token': state['token']})
            with urlopen(request) as response:
                self.assertIn('token', json.load(response))
            with urlopen(url + '/') as response:
                self.assertIn(b'Skill Workspace', response.read())
                self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
