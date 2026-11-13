from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import os
import secrets
import socket
from urllib.parse import urlparse, parse_qs

from manager import Manager, ManagerError
from plugin_manager import plugin_inventory, set_plugin_state

ROOT = Path(__file__).resolve().parent


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_server(port=8765, manager=None):
    model = manager or Manager(Path(os.environ.get('SKILL_MANAGER_HOME', ROOT / '.local')))
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, value, content_type='application/json; charset=utf-8'):
            data = json.dumps(value, ensure_ascii=False).encode() if content_type.startswith('application/json') else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def trusted(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            return self.headers.get('Host') == expected and self.headers.get('Origin', f'http://{expected}') == f'http://{expected}'

        def do_GET(self):
            if not self.trusted():
                return self.respond(403, {'error': '只允许本机同源访问。'})
            parsed = urlparse(self.path)
            try:
                if parsed.path == '/api/health':
                    return self.respond(200, {'service': 'codex-skill-workspace', 'version': '0.1.0'})
                if parsed.path == '/api/plugins':
                    return self.respond(200, dict(plugin_inventory(), token=token))
                with model.lock:
                    if parsed.path == '/api/state':
                        return self.respond(200, dict(model.inventory(), token=token))
                    if parsed.path == '/api/detail':
                        item = model.skill(parse_qs(parsed.query).get('id', [''])[0])
                        text = (Path(item['path']) / 'SKILL.md').read_text(encoding='utf-8-sig')
                        return self.respond(200, {'content': text})
                files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
                if parsed.path not in files:
                    return self.respond(404, {'error': '页面不存在。'})
                file, mime = files[parsed.path]
                self.respond(200, (ROOT / 'web' / file).read_bytes(), mime + '; charset=utf-8')
            except (OSError, ValueError) as exc:
                self.respond(400, {'error': str(exc)})

        def do_POST(self):
            if not self.trusted() or not secrets.compare_digest(self.headers.get('X-Manager-Token', ''), token):
                return self.respond(403, {'error': '请求令牌无效，请刷新页面。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 65536 or not self.headers.get('Content-Type', '').startswith('application/json'):
                    raise ManagerError('请求格式不正确。')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ManagerError('请求必须是 JSON 对象。')
                with model.lock:
                    if self.path == '/api/projects':
                        model.register(str(body.get('path', '')))
                        result = {'message': '项目已登记。'}
                    elif self.path == '/api/plan':
                        result = model.plan(body)
                    elif self.path == '/api/apply':
                        result = model.apply(body.get('token', ''))
                    elif self.path == '/api/plugin-state':
                        result = set_plugin_state(body)
                    else:
                        return self.respond(404, {'error': '接口不存在。'})
                self.respond(200, result)
            except (OSError, ValueError, TypeError) as exc:
                self.respond(400, {'error': str(exc)})

    return LocalServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Codex Skill Workspace 本地管理台')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = create_server(args.port)
    print(f'Skill Workspace: http://127.0.0.1:{server.server_port}', flush=True)
    print('按 Ctrl+C 停止。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
