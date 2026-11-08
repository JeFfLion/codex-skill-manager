"""Build and register our own local plugin without editing application resources."""
from pathlib import Path
import argparse
import json
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
MARKET = 'skill-workspace-local'
PLUGIN = 'skill-workspace-console'
BEGIN = '# BEGIN SKILL WORKSPACE SIDEBAR'
END = '# END SKILL WORKSPACE SIDEBAR'


def write_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build(root=ROOT, python=sys.executable):
    root = Path(root).resolve()
    package = root / '.local/sidebar-plugin'
    source = root / 'integration/sidebar'
    package.mkdir(parents=True, exist_ok=True)
    for name in ('mcp_server.py', 'launcher.html', 'plugin.json', 'icon.svg'):
        shutil.copy2(source / name, package / name)
    server = {'command': str(python), 'args': ['-u', '${PLUGIN_ROOT}/mcp_server.py'],
              'cwd': '${PLUGIN_ROOT}', 'env': {'SKILL_WORKSPACE_ROOT': str(root), 'PYTHONIOENCODING': 'utf-8'}}
    write_json(package / 'mcp.json', {
        '$schema': 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
        # Agent Plugins rejects absolute executable paths. The legacy format
        # below may still use the exact interpreter for older desktop builds.
        'mcpServers': {'skill_console': dict(server, command='python', type='stdio')}})
    # Compatibility files for existing Codex desktop builds.
    write_json(package / '.mcp.json', {'mcpServers': {'skill_console': server}})
    manifest = json.loads((package / 'plugin.json').read_text(encoding='utf-8'))
    overlay = dict(manifest['extensions']['com.openai'], name=PLUGIN, version=manifest['version'],
                   description=manifest['description'], author=manifest['author'], mcpServers='./.mcp.json')
    write_json(package / '.codex-plugin/plugin.json', overlay)
    market_file = root / '.agents/plugins/marketplace.json'
    market = {'name': MARKET, 'interface': {'displayName': 'Skill Workspace 本地插件'}, 'plugins': []}
    if market_file.exists():
        market = json.loads(market_file.read_text(encoding='utf-8'))
        if market.get('name') != MARKET:
            raise ValueError('项目已有其他插件市场，未覆盖。请将本插件添加到现有市场。')
    entry = {'name': PLUGIN, 'source': {'source': 'local', 'path': './.local/sidebar-plugin'},
             'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}, 'category': 'Productivity'}
    market['plugins'] = [p for p in market['plugins'] if p.get('name') != PLUGIN] + [entry]
    write_json(market_file, market)
    return package


def register(root=ROOT, home=None):
    root = Path(root).resolve()
    config = (Path(home) if home else Path.home()) / '.codex/config.toml'
    text = config.read_text(encoding='utf-8-sig') if config.exists() else ''
    state = tomllib.loads(text)
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            raise ValueError('注册标记异常，未修改配置。')
        start, end = text.index(BEGIN), text.index(END) + len(END)
        if start >= end:
            raise ValueError('注册标记顺序异常，未修改配置。')
        text = text[:start] + text[end:]
        state = tomllib.loads(text)
    if MARKET in state.get('marketplaces', {}) or f'{PLUGIN}@{MARKET}' in state.get('plugins', {}):
        raise ValueError('存在同名插件配置，未覆盖。请检查 Codex 配置。')
    block = (f'\n{BEGIN}\n[marketplaces."{MARKET}"]\nsource_type = "local"\n'
             f'source = {json.dumps(root.as_posix(), ensure_ascii=False)}\n\n'
             f'[plugins."{PLUGIN}@{MARKET}"]\nenabled = true\n{END}\n')
    updated = text.rstrip() + '\n' + block
    tomllib.loads(updated)
    config.parent.mkdir(parents=True, exist_ok=True)
    backup = config.with_name('config.toml.before-skill-workspace-sidebar.bak')
    if config.exists() and not backup.exists():
        shutil.copy2(config, backup)
    temporary = config.with_name('config.toml.skill-workspace-tmp')
    temporary.write_text(updated, encoding='utf-8')
    temporary.replace(config)
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成本地侧边栏插件；--register 同时注册到当前用户的 Codex。')
    parser.add_argument('--register', action='store_true')
    args = parser.parse_args()
    print(f'Plugin: {build()}')
    if args.register:
        print(f'Config: {register()}')
    print('请在 Codex 插件详情页安装/启用 Skill 管理台。')
    print('命令行安装或升级后，请在客户端详情页关闭再重新启用一次，以触发全局侧栏目录刷新。')
    print('installed/enabled 状态不等于侧栏入口已刷新；实际显示需在客户端确认。')
