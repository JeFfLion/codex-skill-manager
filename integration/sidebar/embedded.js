import { App } from '@modelcontextprotocol/ext-apps';
const app = new App({ name: 'Skill Workspace', version: '0.2.2' }, {}, { strict: true, autoResize: false });
app.ontoolinput = () => {};
app.ontoolresult = () => {};
window.skillWorkspaceRequest = async (path, body) => {
  const args = { path };
  if (body !== undefined) args.body = body;
  const result = await app.callServerTool({ name: 'console_request', arguments: args }, { timeout: 60000 });
  if (result.isError) throw new Error(result.content?.find(item => item.type === 'text')?.text || '操作失败');
  return result.structuredContent;
};
try {
  await app.connect(undefined, { timeout: 8000 });
  await import('../../web/app.js');
} catch (error) {
  const status = document.getElementById('status');
  status.hidden = false;
  status.classList.add('error');
  status.textContent = '连接失败：' + (error.message || error);
  document.getElementById('refresh').onclick = () => location.reload();
}
