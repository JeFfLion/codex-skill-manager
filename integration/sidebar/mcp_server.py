"""Small stdio MCP launcher. Discovery never starts a service or opens a browser."""
from pathlib import Path
import json
import os
import sys
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

URI = 'ui://skill-workspace/console-v5.html'
LEGACY_URIS = {'ui://skill-workspace/launcher-v1.html', 'ui://skill-workspace/launcher-v2.html',
               'ui://skill-workspace/console-v3.html', 'ui://skill-workspace/console-v4.html'}
TOOL = 'show_skill_console'
LAUNCH = 'launch_skill_console'
EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}


def tools():
    return [
        {'name': TOOL, 'title': 'Skill 管理台', 'description': '打开 Skill 管理台侧边栏入口。',
         'inputSchema': EMPTY,
         'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False},
         '_meta': {'ui': {'resourceUri': URI}, 'openai/outputTemplate': URI,
                   'openai/ui': {'entrypoints': [{'type': 'global'}]}}},
        {'name': LAUNCH, 'title': '打开本地技能管理控制台',
         'description': '仅从管理台入口调用；启动本机管理服务并在默认浏览器打开。',
         'inputSchema': EMPTY,
         'outputSchema': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url'], 'additionalProperties': False},
         'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False},
         '_meta': {'ui': {'visibility': ['app']}, 'openai/visibility': 'private', 'openai/widgetAccessible': True}},
        {'name': 'console_request', 'title': '管理台操作', 'description': '仅供内嵌管理界面使用。',
         'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'body': {'type': 'object'}}, 'required': ['path'], 'additionalProperties': False},
         'outputSchema': {'type': 'object', 'additionalProperties': True},
         'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False},
         '_meta': {'ui': {'visibility': ['app']}, 'openai/visibility': 'private', 'openai/widgetAccessible': True}},
    ]


def launch():
    root = Path(os.environ.get('SKILL_WORKSPACE_ROOT', Path(__file__).resolve().parents[2]))
    if not (root / 'launcher.py').is_file():
        raise ValueError('管理系统项目路径已移动，请重新运行 setup_sidebar.py。')
    sys.path.insert(0, str(root))
    from launcher import open_console
    return open_console()


def console_request(arguments):
    from urllib.parse import urlsplit, parse_qs
    path = arguments.get('path', '')
    parsed = urlsplit(path)
    body = arguments.get('body')
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError('不支持的管理台请求。')
    if body is None:
        valid = path in ('state', 'plugins') or (parsed.path == 'detail' and set(parse_qs(parsed.query)) == {'id'})
    else:
        valid = path in ('projects', 'plan', 'apply', 'plugin-state') and isinstance(body, dict)
    if not valid:
        raise ValueError('不支持的管理台请求。')
    root = Path(os.environ.get('SKILL_WORKSPACE_ROOT', Path(__file__).resolve().parents[2]))
    sys.path.insert(0, str(root))
    from launcher import ensure_console
    base = ensure_console()
    client = build_opener(ProxyHandler({}))
    headers = {'Content-Type': 'application/json'}
    if body is not None:
        with client.open(base + 'api/state', timeout=30) as response:
            headers['X-Manager-Token'] = json.load(response)['token']
    request = Request(base + 'api/' + path, data=None if body is None else json.dumps(body).encode('utf-8'), headers=headers)
    try:
        with client.open(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        raise ValueError(json.loads(error.read()).get('error', '管理操作失败。')) from error
    if path in ('state', 'plugins'):
        result.pop('token', None)
    return result


def dispatch(method, params):
    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25') else '2025-06-18'
        return {'protocolVersion': version, 'capabilities': {'tools': {}, 'resources': {}},
                'serverInfo': {'name': 'skill-workspace-console', 'title': 'Skill 管理台', 'version': '0.2.2'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': tools()}
    if method == 'resources/list':
        return {'resources': [{'uri': URI, 'name': 'skill-console', 'title': 'Skill 管理台', 'mimeType': 'text/html;profile=mcp-app'}]}
    if method == 'resources/templates/list':
        return {'resourceTemplates': []}
    if method == 'resources/read':
        requested_uri = params.get('uri')
        if requested_uri not in {URI, *LEGACY_URIS}:
            raise ValueError('未知的界面资源。')
        # Existing open tabs can retain the previous URI while MCP reloads.
        # Always serve the fixed SDK UI rather than making those tabs fail.
        return {'contents': [{'uri': requested_uri, 'mimeType': 'text/html;profile=mcp-app',
            'text': Path(__file__).with_name('launcher.html').read_text(encoding='utf-8'),
            '_meta': {'ui': {'csp': {'connectDomains': [], 'resourceDomains': []}},
                      'openai/ui': {'availableDisplayModes': ['fullscreen', 'inline']}}}]}
    if method == 'tools/call':
        if params.get('name') == 'console_request':
            try:
                data = console_request(params.get('arguments', {}))
                return {'structuredContent': data, 'content': [{'type': 'text', 'text': '管理操作完成。'}]}
            except (OSError, ValueError, RuntimeError) as exc:
                return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
        if params.get('arguments', {}) != {}:
            raise ValueError('此入口不接受路径、命令或其他参数。')
        name = params.get('name')
        if name == TOOL:
            return {'content': [{'type': 'text', 'text': 'Skill 管理台入口已打开。'}]}
        if name == LAUNCH:
            try:
                url = launch()
                return {'structuredContent': {'url': url}, 'content': [{'type': 'text', 'text': f'管理控制台已打开：{url}'}]}
            except (OSError, ValueError, RuntimeError) as exc:
                return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
        raise ValueError('未知工具。')
    raise LookupError('不支持的方法。')


def main():
    for line in sys.stdin.buffer:
        message = None
        try:
            if len(line) > 1024 * 1024:
                raise ValueError('请求过大。')
            message = json.loads(line)
            if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                raise ValueError('请求必须为 JSON-RPC 2.0 对象。')
            if 'id' not in message:
                continue
            params = message.get('params', {})
            if not isinstance(params, dict):
                raise ValueError('参数必须为对象。')
            response = {'jsonrpc': '2.0', 'id': message['id'], 'result': dispatch(message.get('method'), params)}
        except (ValueError, LookupError) as exc:
            code = -32700 if isinstance(exc, json.JSONDecodeError) else -32601 if isinstance(exc, LookupError) else -32602
            response = {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                        'error': {'code': code, 'message': str(exc)}}
        except Exception:
            response = {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                        'error': {'code': -32603, 'message': '本地管理台入口发生错误，请检查项目文件。'}}
        sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + '\n').encode('utf-8'))
        sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
