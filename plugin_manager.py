"""Manage installed plugins through the local Codex app server."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
from threading import Thread
from time import monotonic

from manager import ManagerError, safe_tree_parents


PLUGIN_ID = re.compile(r'[a-zA-Z0-9_-]+@[a-zA-Z0-9_-]+')
PROTECTED_MARKETS = {'openai-bundled', 'openai-primary-runtime'}
CONSOLE_PLUGIN = 'skill-workspace-console@skill-workspace-local'


@contextmanager
def codex_client():
    command = shutil.which('codex')
    if not command:
        raise ManagerError('未找到 Codex CLI。请将 Codex 加入 PATH 后重试。')
    # Prefer the executable over Windows package-manager shims when available.
    if os.name == 'nt':
        command = shutil.which('codex.exe') or command
    messages = Queue()
    deadline = monotonic() + 18
    next_id = 0
    with subprocess.Popen(
        [command, 'app-server', '--stdio'], cwd=Path.home(),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    ) as process:
        def read_messages():
            try:
                for line in process.stdout:
                    messages.put(line)
            finally:
                messages.put(None)

        def send(message):
            process.stdin.write(json.dumps(message) + '\n')
            process.stdin.flush()

        def call(method, params):
            nonlocal next_id
            next_id += 1
            send({'id': next_id, 'method': method, 'params': params})
            while monotonic() < deadline:
                line = messages.get(timeout=max(0, deadline - monotonic()))
                if line is None:
                    break
                message = json.loads(line)
                if message.get('id') != next_id or 'method' in message:
                    continue
                if 'error' in message:
                    details = message['error'].get('data')
                    if isinstance(details, dict) and details.get('config_write_error_code') == 'configVersionConflict':
                        raise ManagerError('Codex 配置已更改，请刷新插件列表后重试。')
                    raise ManagerError('Codex 未能完成插件操作。请检查 Codex 版本和用户配置。')
                if isinstance(message.get('result'), dict):
                    return message['result']
                break
            raise ManagerError('Codex 插件接口未返回有效响应。')

        reader = Thread(target=read_messages, daemon=True)
        reader.start()
        try:
            info = call('initialize', {'clientInfo': {'name': 'skill-workspace', 'version': '0.2.0'}})
            send({'method': 'initialized'})
            yield call, info
        except Empty as exc:
            raise ManagerError('读取 Codex 插件状态超时，请重试。') from exc
        except (BrokenPipeError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ManagerError('Codex 插件接口不可用，请检查 Codex CLI 版本和配置。') from exc
        finally:
            process.kill()
            reader.join()


def installed_plugins(call):
    result = call('plugin/installed', {})
    items = {}
    for marketplace in result['marketplaces']:
        market = marketplace['name']
        if market.casefold() in PROTECTED_MARKETS:
            continue
        for plugin in marketplace['plugins']:
            plugin_id = plugin['id']
            if (
                not plugin['installed'] or not PLUGIN_ID.fullmatch(plugin_id)
                or plugin_id.casefold() == CONSOLE_PLUGIN
                or plugin_id.split('@')[1] != market
                or plugin.get('installPolicySource') == 'IMPLICIT_CANONICAL_APP'
            ):
                continue
            interface = plugin.get('interface') or {}
            remote = plugin['source']['type'] == 'remote'
            items[plugin_id] = {
                'id': plugin_id, 'name': interface.get('displayName') or plugin['name'],
                'description': interface.get('shortDescription') or '',
                'marketplace': market, 'version': plugin.get('localVersion') or plugin.get('version') or '',
                'enabled': plugin['enabled'],
                'remote': remote,
                'editable': not remote and plugin.get('installPolicy') == 'AVAILABLE' and not plugin.get('installPolicySource'),
            }
    return sorted(items.values(), key=lambda plugin: (plugin['name'].casefold(), plugin['id']))


def plugin_inventory():
    with codex_client() as (call, _):
        return {'plugins': installed_plugins(call)}


def set_plugin_state(request):
    plugin_id, enabled, expected = (request.get(key) for key in ('id', 'enabled', 'expected'))
    if not isinstance(plugin_id, str) or type(enabled) is not bool or type(expected) is not bool:
        raise ManagerError('插件状态请求无效。')
    with codex_client() as (call, info):
        config = call('config/read', {'includeLayers': True})
        plugin = next((item for item in installed_plugins(call) if item['id'] == plugin_id), None)
        if not plugin or not plugin['editable']:
            raise ManagerError('这个插件的状态由 Codex 管理，或插件已不在本地目录中。')
        if plugin['enabled'] != expected:
            raise ManagerError('插件状态已更改，请刷新插件列表后重试。')
        if enabled == expected:
            return {'message': '插件已处于所选状态。'}

        config_path = Path(info['codexHome']) / 'config.toml'
        layer = next((
            layer for layer in (config.get('layers') or [])
            if layer['name']['type'] == 'user' and not layer['name'].get('profile')
            and Path(layer['name']['file']) == config_path and not layer.get('disabledReason')
        ), None)
        if not layer or not layer.get('version'):
            raise ManagerError('无法识别可写的 Codex 用户配置。')
        safe_tree_parents(config_path)
        result = call('config/value/write', {
            'filePath': str(config_path), 'keyPath': f'plugins."{plugin_id}".enabled',
            'value': enabled, 'mergeStrategy': 'replace', 'expectedVersion': layer['version'],
        })
        if result.get('overriddenMetadata'):
            return {'message': '用户级设置已保存，当前插件状态受优先级更高的配置控制。'}
        return {'message': '插件设置已保存。请在 Codex 中开启新会话验证。'}
