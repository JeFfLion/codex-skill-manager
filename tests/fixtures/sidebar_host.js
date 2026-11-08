// A real MCP Apps parent host. All tools are mocked: no console or browser opens.
import { AppBridge, PostMessageTransport, SUPPORTED_PROTOCOL_VERSIONS } from '@modelcontextprotocol/ext-apps/app-bridge';

const frame = document.getElementById('app');
const scenario = new URL(location.href).searchParams.get('scenario') || 'success';
const fixture = window.fixture = {
  scenario, events: [], calls: [], initialized: false, initializedMs: null,
  requestedProtocol: null, negotiatedProtocol: null, errors: [],
  supportedProtocols: SUPPORTED_PROTOCOL_VERSIONS, receivedMessages: [], hostTimedOut: false,
};
const started = performance.now();

window.addEventListener('error', event => fixture.errors.push(event.message));
window.addEventListener('unhandledrejection', event => fixture.errors.push(String(event.reason)));
window.addEventListener('message', event => {
  fixture.receivedMessages.push({ fromApp: event.source === frame.contentWindow, keys: Object.keys(event.data || {}) });
  if (event.source !== frame.contentWindow || !event.data || typeof event.data !== 'object') return;
  const message = event.data;
  if (message.method) fixture.events.push(message.method);
  if (message.method === 'ui/initialize') fixture.requestedProtocol = message.params?.protocolVersion;
});

const bridge = new AppBridge(
  null,
  { name: 'Sidebar regression host', version: '1.0.0' },
  { serverTools: {}, logging: {} },
  { hostContext: { theme: 'light', displayMode: 'fullscreen', availableDisplayModes: ['fullscreen', 'inline'] } },
);
const transport = new PostMessageTransport(frame.contentWindow, frame.contentWindow);
const send = transport.send.bind(transport);
transport.send = async (message, options) => {
  if (message.result?.protocolVersion) fixture.negotiatedProtocol = message.result.protocolVersion;
  return send(message, options);
};
bridge.onerror = error => fixture.errors.push(String(error));
bridge.oninitialized = () => {
  fixture.initialized = true;
  fixture.initializedMs = performance.now() - started;
  // Exercise the notifications Codex sends immediately after handshake.
  void bridge.sendToolInput({ arguments: {} }).catch(error => fixture.errors.push(String(error)));
  void bridge.sendToolResult({ content: [{ type: 'text', text: 'Skill 管理台入口已打开。' }] })
    .catch(error => fixture.errors.push(String(error)));
};
bridge.oncalltool = async params => {
  if (!fixture.initialized) throw new Error('Tool invoked before UI initialized notification');
  if (params.name !== 'console_request') throw new Error('Unexpected tool: '+params.name);
  fixture.calls.push({name:params.name, path:params.arguments.path, afterInitialized:fixture.initialized});
  const path=params.arguments.path;
  if(scenario==='tool-error' && fixture.calls.length===1) return {isError:true,content:[{type:'text',text:'模拟读取失败'}]};
  let data={};
  if(path==='state') data={skills:[{id:'demo',name:'示例技能',description:'用于内嵌回归',path:'C:/skills/demo',scope:'user',readonly:false}],projects:['C:/project'],projectDetails:[{path:'C:/project',name:'示例项目',source:'codex',available:true}],codexProjectCount:1,backups:[],warnings:[],dataPath:'C:/data'};
  else if(path.startsWith('detail?')) data={content:'示例完整 SKILL.md'};
  else if(path==='plan') data={token:'preview',source:'C:/skills/demo',target:'C:/project/.agents/skills/demo',effect:'仅项目可见'};
  else if(path==='apply') data={message:'内嵌操作完成'};
  else throw new Error('Unknown path');
  return {structuredContent:data,content:[{type:'text',text:'OK'}]};
};

await bridge.connect(transport);
// No window.openai compatibility global is provided in either frame.
frame.src = scenario === 'legacy-no-handshake' ? '/legacy.html' : '/launcher.html';
setTimeout(() => { fixture.hostTimedOut = !fixture.initialized; }, 5000);
