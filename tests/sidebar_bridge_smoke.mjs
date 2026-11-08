// Run after npm run build:sidebar. Uses Edge plus the official MCP Apps host SDK.
// The fixture never launches a real control console or mutates any skills.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = join(root, '.local');
const pause = ms => new Promise(done => setTimeout(done, ms));
await mkdir(output, { recursive: true });
const html = await readFile(join(root, 'integration/sidebar/launcher.html'));
const hostBundle = await build({
  entryPoints: [join(root, 'tests/fixtures/sidebar_host.js')],
  bundle: true, format: 'esm', platform: 'browser', write: false,
});
const server = createServer((request, response) => {
  const path = new URL(request.url, 'http://localhost').pathname;
  const routes = {
    '/': ['text/html; charset=utf-8', '<!doctype html><html><head><meta charset="utf-8"><title>Sidebar bridge regression</title><style>body{margin:0}iframe{width:100vw;height:100vh;border:0}</style></head><body><iframe id="app" title="Skill 管理台测试"></iframe><script type="module" src="/host.js"></script></body></html>'],
    '/host.js': ['text/javascript; charset=utf-8', hostBundle.outputFiles[0].contents],
    '/launcher.html': ['text/html; charset=utf-8', html],
    // Negative control reproduces the prior window.openai-only boot strategy.
    '/legacy.html': ['text/html; charset=utf-8', '<!doctype html><html><meta charset="utf-8"><body><p id="status">正在连接本地启动器…</p><script>let attempts=0;const ready=setInterval(()=>{if(window.openai?.callTool){clearInterval(ready);window.openai.callTool("launch_skill_console",{});}else if(++attempts>=30){clearInterval(ready);}},100);</script></body></html>'],
  };
  const route = routes[path];
  response.writeHead(route ? 200 : 404, {
    'Content-Type': route?.[0] || 'text/plain', 'Cache-Control': 'no-store',
    // Prove that the UI bundle initializes without external scripts or API fetches.
    'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'none'; object-src 'none'",
  });
  response.end(route?.[1] || 'Not found');
});
await new Promise((done, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', done); });
const baseUrl = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp(join(output, 'sidebar-bridge-browser-'));
const executable = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
assert(existsSync(executable), 'Edge not found; set EDGE_PATH to the browser executable.');
const browser = spawn(executable, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
  '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank',
], { windowsHide: true, stdio: 'ignore' });
let socket;
const pending = new Map();
let sequence = 0;
const browserErrors = [];

try {
  let debugPort;
  for (let attempt = 0; attempt < 150; attempt++) {
    try { debugPort = Number((await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]); break; }
    catch { await pause(100); }
  }
  assert(debugPort, 'Edge did not expose its test debugging endpoint.');
  const pages = await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json();
  const page = pages.find(candidate => candidate.type === 'page');
  assert(page, 'No test browser page was created.');
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((done, reject) => { socket.addEventListener('open', done, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') browserErrors.push(message.params.exceptionDetails);
    const waiter = pending.get(message.id);
    if (!waiter) return;
    clearTimeout(waiter.timer); pending.delete(message.id);
    message.error ? waiter.reject(new Error(JSON.stringify(message.error))) : waiter.done(message.result);
  });
  const cdp = (method, params = {}) => new Promise((done, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 15000);
    pending.set(id, { done, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const until = async (expression, description) => {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) { if (await evaluate(expression)) return; await pause(50); }
    const diagnostic = await evaluate('JSON.stringify({fixture:window.fixture,childStatus:document.querySelector("#app")?.contentDocument?.querySelector("#status")?.textContent})');
    throw new Error(description + ': ' + diagnostic + '; browser errors: ' + JSON.stringify(browserErrors));
  };
  const child = 'document.querySelector("#app").contentDocument';
  await cdp('Runtime.enable');
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:baseUrl+'/?scenario=success'});
  await until(`${child}?.querySelectorAll('.skill-row').length===1`,'Embedded inventory missing');
  const fixture=await evaluate('window.fixture');
  assert(fixture.initializedMs<5000);
  assert(fixture.events.indexOf('ui/notifications/initialized')<fixture.events.indexOf('tools/call'));
  assert(fixture.calls.every(c=>c.name==='console_request'));
  await evaluate(`${child}.querySelector('.name-button').click()`);
  await until(`${child}.querySelector('pre')?.textContent.includes('SKILL.md')`,'Detail missing');
  await evaluate(`${child}.querySelector('dialog .close').click();${child}.querySelector('[data-action=install]').click();${child}.querySelector('#dialog-submit').click()`);
  await until(`${child}.querySelector('#dialog-title').textContent==='确认这次变更'`,'Preview missing');
  await evaluate(`${child}.querySelector('#dialog-submit').click()`);
  await until(`${child}.querySelector('#status').textContent==='内嵌操作完成'`,'Apply missing');
  assert((await evaluate('window.fixture.calls.map(c=>c.path)')).includes('apply'));
  const screenshot=await cdp('Page.captureScreenshot',{format:'png'});
  await writeFile(join(output,'embedded-console.png'),Buffer.from(screenshot.data,'base64'));
  await cdp('Page.navigate',{url:baseUrl+'/?scenario=tool-error'});
  await until(`${child}?.querySelector('#status')?.textContent==='模拟读取失败'`,'Visible error missing');
  await evaluate(`${child}.querySelector('#refresh').click()`);
  await until(`${child}.querySelectorAll('.skill-row').length===1`,'Error retry failed');
  assert.equal(browserErrors.length,0);
  console.log('Embedded console passed: standard handshake, inventory, details, preview/apply, error retry; all requests through MCP, no external browser or HTTP access.');
} finally {
  for (const waiter of pending.values()) clearTimeout(waiter.timer);
  socket?.close();
  browser.kill();
  server.closeAllConnections();
  await new Promise(done => server.close(done));
}
