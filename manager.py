"""Filesystem model. No skill content is ever executed."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time


class ManagerError(ValueError):
    pass


def protected(path: Path) -> bool:
    """Exclude runtime-owned locations, including aliases and '..' paths."""
    for candidate in (Path(os.path.abspath(path)), path.resolve()):
        parts = [part.casefold() for part in candidate.parts]
        for index, part in enumerate(parts):
            tail = parts[index + 1:]
            if part == '.codex' and tail[:1] == ['plugins']:
                return True
            if part in ('.codex', '.agents') and tail[:2] == ['skills', '.system']:
                return True
    return False


def require_custom(path: Path) -> None:
    if protected(path):
        raise ManagerError('官方内置技能和插件目录不属于本系统的管理范围。')


def linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def safe_tree(path: Path) -> None:
    for parent in (path, *path.parents):
        if linked(parent):
            raise ManagerError('路径包含符号链接或 junction，第一版仅支持普通目录。')
    if not path.is_dir():
        raise ManagerError('技能目录不存在。')
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            require_custom(Path(root) / name)
            if linked(Path(root) / name):
                raise ManagerError('技能内包含符号链接或 junction，无法安全复制或移动。')


def digest(path: Path) -> str:
    safe_tree(path)
    result = hashlib.sha256()
    for item in sorted(path.rglob('*')):
        result.update(item.relative_to(path).as_posix().encode())
        if item.is_file():
            with item.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    result.update(chunk)
    return result.hexdigest()


def metadata(file: Path) -> tuple[str, str]:
    content = file.read_text(encoding='utf-8-sig')
    name, description = file.parent.name, ''
    # Read the common frontmatter subset; preserve original files byte-for-byte.
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.S)
    if match:
        fields = match.group(1)
        found = re.search(r'^name:\s*(.+)$', fields, re.M)
        if found:
            name = found.group(1).strip().strip('\"\'')
        found = re.search(r'^description:\s*(.*(?:\n[ \t]+[^\n]+)*)', fields, re.M)
        if found:
            description = ' '.join(found.group(1).strip().strip('\"\'').split())
            description = re.sub(r'^[>|][-+]?\s*', '', description)
    return name, description


class Manager:
    def __init__(self, data: Path, home: Path | None = None):
        self.data = data.absolute()
        self.home = (home or Path.home()).absolute()
        require_custom(self.data)
        safe_tree_parents(self.data)
        for scanned in (self.home / '.agents/skills', self.home / '.codex/skills', self.home / '.codex/plugins'):
            if self.data == scanned or scanned in self.data.parents:
                raise ManagerError('管理器数据目录必须位于 Codex 的技能和插件扫描目录之外。')
        self.library = self.data / 'library'
        self.backups = self.data / 'backups'
        self.state_file = self.data / 'state.json'
        self.lock = threading.RLock()
        self.plans = {}
        self.state = {'projects': [], 'backups': []}
        if self.state_file.exists():
            self.state = json.loads(self.state_file.read_text(encoding='utf-8'))

    def save(self):
        self.data.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.state_file)

    def register(self, value):
        path = Path(value).expanduser()
        if not value or not path.is_absolute():
            raise ManagerError('请输入项目文件夹的绝对路径。')
        require_custom(path)
        if not path.is_dir():
            raise ManagerError('项目路径不存在或不是文件夹。')
        safe_tree_parents(path)
        for relative in ('.agents/skills', '.codex/skills'):
            scanned = path / relative
            if self.data == scanned or scanned in self.data.parents:
                raise ManagerError('收藏库与备份不能位于项目技能扫描目录中。')
        if not any(Path(p) == path for p in self.state['projects']):
            self.state['projects'].append(str(path))
            self.save()

    def project_catalog(self):
        """Read sidebar metadata only; never write Codex state."""
        details, warnings, seen = [], [], set()

        def add(value, name, source, project_id):
            if not isinstance(value, str) or not value:
                return
            path = Path(value).expanduser()
            if not path.is_absolute() or value.startswith(('\\\\', '//')) or protected(path):
                return
            if '.chatgpt-projects' in path.parts:
                return
            key = os.path.normcase(os.path.abspath(path))
            if key in seen:
                return
            seen.add(key)
            try:
                safe_tree_parents(path)
                available = path.is_dir()
            except (OSError, ManagerError):
                available = False
            details.append(dict(path=str(path), name=name or path.name, source=source,
                                id=project_id, available=available))

        state_file = self.home / '.codex/.codex-global-state.json'
        if state_file.is_file():
            try:
                state = json.loads(state_file.read_text(encoding='utf-8-sig'))
                if not isinstance(state, dict):
                    raise ValueError('项目状态不是 JSON 对象')
                projects = state.get('local-projects', {})
                order = state.get('project-order', [])
                if not isinstance(projects, dict) or not isinstance(order, list):
                    raise ValueError('项目状态结构不兼容')
                ordered_ids = [key for key in order if isinstance(key, str)]
                ordered_ids += [key for key in projects if key not in ordered_ids]
                for project_id in ordered_ids:
                    item = projects.get(project_id)
                    if not isinstance(item, dict) or project_id.startswith('g-p-'):
                        continue
                    roots = item.get('rootPaths', [])
                    if not isinstance(roots, list):
                        continue
                    name = item.get('name', '')
                    if not isinstance(name, str):
                        name = ''
                    for value in roots:
                        label = name
                        if len(roots) > 1 and isinstance(value, str):
                            label = f'{name} / {Path(value).name}'
                        add(value, label, 'codex', project_id)
            except (OSError, ValueError) as exc:
                warnings.append(f'读取 Codex 侧边栏项目失败：{exc}。仍可使用手动添加的项目。')
        for value in self.state['projects']:
            add(value, '', 'manual', value)
        return details, warnings

    def roots(self, projects=None):
        yield self.library, 'library', '', False
        yield self.home / '.agents/skills', 'user', '', False
        yield self.home / '.codex/skills', 'user', '', False
        if projects is None:
            projects, _ = self.project_catalog()
        for item in projects:
            if not item['available']:
                continue
            project = item['path']
            for relative in ('.agents/skills', '.codex/skills'):
                yield Path(project) / relative, 'project', project, False

    def inventory(self):
        projects, warnings = self.project_catalog()
        skills, seen = [], set()

        def add(file, scope, project='', readonly=False):
            if protected(file):
                return
            key = str(file.absolute())
            if key in seen:
                return
            seen.add(key)
            try:
                name, description = metadata(file)
                skills.append(dict(id=hashlib.sha256(key.encode()).hexdigest()[:24], name=name,
                    description=description, path=str(file.parent.absolute()), scope=scope,
                    project=project, readonly=readonly or linked(file.parent)))
            except (OSError, UnicodeError) as exc:
                warnings.append(f'{file}: {exc}')

        for root, scope, project, readonly in self.roots(projects):
            if protected(root) or not root.is_dir():
                continue
            try:
                for directory in root.iterdir():
                    if directory.name.startswith('.'):
                        continue
                    if (directory / 'SKILL.md').is_file():
                        add(directory / 'SKILL.md', scope, project, readonly)
            except OSError as exc:
                warnings.append(str(exc))
        backups = [b for b in self.state['backups'] if not protected(Path(b['original']))]
        return dict(skills=skills, projects=[p['path'] for p in projects], projectDetails=projects,
                    codexProjectCount=len({p['id'] for p in projects if p['source'] == 'codex'}), backups=backups,
                    warnings=warnings, dataPath=str(self.data))

    def skill(self, skill_id):
        for item in self.inventory()['skills']:
            if item['id'] == skill_id:
                return item
        raise ManagerError('技能不存在，请刷新列表。')

    def destination(self, scope, project, folder):
        if scope == 'library':
            return self.library / folder
        if scope == 'user':
            return self.home / '.agents/skills' / folder
        if scope == 'project':
            projects, _ = self.project_catalog()
            if any(p['path'] == project and p['available'] for p in projects):
                return Path(project) / '.agents/skills' / folder
            raise ManagerError('项目已移除或路径不可用，请刷新项目列表。')
        raise ManagerError('请选择已登记的项目或有效作用域。')

    def plan(self, request):
        operation = request.get('operation')
        source_item = None
        if operation == 'import':
            value = request.get('path', '')
            source = Path(value).expanduser()
            if not value or not source.is_absolute():
                raise ManagerError('请输入技能文件夹的绝对路径。')
            if not (source / 'SKILL.md').is_file():
                raise ManagerError('请选择包含 SKILL.md 的完整技能文件夹。')
            target = self.destination('library', '', source.name)
        elif operation == 'restore':
            backup = next((b for b in self.state['backups'] if b['id'] == request.get('backupId')), None)
            if not backup:
                raise ManagerError('备份不存在。')
            source = self.backups / backup['id'] / 'skill'
            target = Path(backup['original'])
        elif operation in ('install', 'disable', 'migrate'):
            source_item = self.skill(request.get('skillId'))
            source = Path(source_item['path'])
            if operation in ('disable', 'migrate') and (source_item['readonly'] or source_item['scope'] not in ('user', 'project')):
                raise ManagerError('仅支持停用或迁移独立的用户级、项目级技能。')
            if operation == 'migrate' and source_item['scope'] != 'user':
                raise ManagerError('迁移操作仅用于用户级技能。')
            if operation == 'disable':
                target = None
            else:
                target = self.destination('project' if operation == 'migrate' else request.get('scope'),
                                          request.get('project'), source.name)
        else:
            raise ManagerError('不支持的操作。')
        require_custom(source)
        if target:
            require_custom(target)
        checksum = digest(source)
        if target:
            safe_tree_parents(target)
            if target.exists():
                raise ManagerError('目标目录已存在，拒绝覆盖。请先检查同名技能。')
            if source == target or source in target.parents or target in source.parents:
                raise ManagerError('源与目标目录不能相互包含。')
        token = secrets.token_urlsafe(24)
        self.plans = {k: v for k, v in self.plans.items() if v['expires'] > time.time()}
        self.plans[token] = dict(operation=operation, source=str(source), target=str(target) if target else None,
                                 checksum=checksum, expires=time.time() + 300, backupId=request.get('backupId'),
                                 project=request.get('project') if operation == 'migrate' or (operation == 'install' and request.get('scope') == 'project') else None)
        effects = {
            'import': '仅收藏，不会让 Codex 自动加载。',
            'install': '复制整个技能目录；用户级安装对所有项目可见，项目级安装仅供该项目发现。',
            'disable': '将原目录移入备份区，减少该作用域的可见候选；可在备份页面恢复。',
            'migrate': '先安装到所选项目，再将用户级原目录移入备份区。其他项目将失去此用户级副本。',
            'restore': '恢复到原始路径；若原路径已存在则拒绝覆盖。',
        }
        return dict(token=token, operation=operation, source=str(source), target=str(target) if target else '本地备份区', effect=effects[operation])

    def apply(self, token):
        plan = self.plans.pop(token, None)
        if not plan or plan['expires'] < time.time():
            raise ManagerError('预览已失效，请重新预览。')
        source = Path(plan['source'])
        target = Path(plan['target']) if plan['target'] else None
        require_custom(source)
        if target:
            require_custom(target)
        if plan.get('project'):
            self.destination('project', plan['project'], source.name)
        if digest(source) != plan['checksum']:
            raise ManagerError('预览后源文件发生变化，请重新预览。')
        if target:
            safe_tree_parents(target)
            if target.exists():
                raise ManagerError('目标目录已存在，拒绝覆盖。')
        operation = plan['operation']
        if operation in ('import', 'install', 'migrate'):
            target.parent.mkdir(parents=True, exist_ok=True)
            # Reserve target with mkdir; never merge or overwrite an existing folder.
            target.mkdir()
            try:
                shutil.copytree(source, target, dirs_exist_ok=True)
                if digest(target) != plan['checksum'] or digest(source) != plan['checksum']:
                    raise ManagerError('复制过程中内容发生变化，已取消操作。')
            except Exception:
                shutil.rmtree(target)
                raise
        if operation in ('disable', 'migrate'):
            backup_id = secrets.token_hex(12)
            storage = self.backups / backup_id / 'skill'
            storage.parent.mkdir(parents=True)
            entry = dict(id=backup_id, original=str(source), name=source.name,
                         created=time.strftime('%Y-%m-%d %H:%M:%S'), operation=operation)
            try:
                shutil.move(str(source), str(storage))
                self.state['backups'].append(entry)
                self.save()
            except Exception:
                if storage.exists() and not source.exists():
                    shutil.move(str(storage), str(source))
                if entry in self.state['backups']:
                    self.state['backups'].remove(entry)
                if operation == 'migrate' and target.exists():
                    shutil.rmtree(target)
                raise
        if operation == 'restore':
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            old = list(self.state['backups'])
            self.state['backups'] = [b for b in old if b['id'] != plan['backupId']]
            try:
                self.save()
            except Exception:
                self.state['backups'] = old
                shutil.move(str(target), str(source))
                raise
        return {'message': '操作完成。建议在 Codex 中开启新会话验证技能可见性。'}


def safe_tree_parents(path: Path):
    for parent in (path, *path.parents):
        if linked(parent):
            raise ManagerError('目标或项目路径包含符号链接或 junction。')
