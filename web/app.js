'use strict';
const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const labels = {all:'全部技能',library:'收藏库',user:'用户级',project:'项目级',backups:'停用与备份'};
let state = {skills:[],projects:[],backups:[]}, view = 'all', submitAction;
const dialog = $('#dialog');
async function api(path, body) {
  if (document.documentElement.hasAttribute('data-embedded')) {
    if (!window.skillWorkspaceRequest) throw new Error('尚未连接 Codex，请重新打开管理台。');
    return window.skillWorkspaceRequest(path, body);
  }
  const options = body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Manager-Token':state.token},body:JSON.stringify(body)};
  const response = await fetch('/api/' + path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败，请重试。');
  return result;
}
function notice(message, error=false) { const box=$('#status'); box.textContent=message; box.classList.toggle('error',error); box.hidden=false; }
async function refresh() {
  const button=$('#refresh'); button.disabled=true;
  try {
    const project=$('#project').value;
    state=await api('state');
    $('#project').innerHTML='<option value="">所有项目</option>'+projectOptions();
    if(state.projects.includes(project)) $('#project').value=project;
    for(const scope of ['user','project','library']) { const count=state.skills.filter(s=>s.scope===scope).length; $('#stat-'+scope).textContent=count; $('#count-'+scope).textContent=count; }
    $('#count-all').textContent=state.skills.length;
    $('#count-backups').textContent=state.backups.length;
    $('#project-status').textContent=state.codexProjectCount ? `已自动读取 Codex 侧边栏的 ${state.codexProjectCount} 个本地项目 · 刷新扫描可同步更新` : '未发现 Codex 侧边栏本地项目，可手动添加项目。';
    $('#data-path').textContent='数据位置：'+state.dataPath;
    if(state.warnings.length) notice('部分数据未能读取：\n'+state.warnings.join('\n'),true);
    render();
  } catch(error) {notice(error.message,true);$('#list').innerHTML='<div class="empty">扫描失败，请点击右上角重新扫描。</div>';}
  finally {button.disabled=false;}
}
function render() {
  const query=$('#search').value.toLowerCase(),project=$('#project').value;
  $('#breadcrumb').textContent=labels[view];
  $('#title').textContent=view==='all'?'技能工作台':labels[view];
  $('#subtitle').textContent=view==='backups'?'停用时保留完整文件，可恢复到原始位置。':'把合适的技能，放进合适的项目。';
  $('#list-title').textContent=view==='all'?'所有已发现技能':labels[view];
  $('#context-hint').textContent=project?'显示该项目根目录与用户级的后添加技能；官方内置技能和插件附带技能不纳入管理。':'仅管理后添加的独立技能；官方内置技能与插件附带技能不纳入管理。';
  let items;
  if(view==='backups') {
    items=state.backups.filter(b=>[b.name,b.original].join(' ').toLowerCase().includes(query));
    $('#list').innerHTML=items.map(b=>`<article class="skill-row"><div class="skill-icon" aria-hidden="true">↶</div><div><div class="skill-name"><strong>${escapeHTML(b.name)}</strong><span class="badge">可恢复</span></div><p class="description">${escapeHTML(b.created)} · ${b.operation==='migrate'?'迁移时备份':'已停用'}</p><div class="path">${escapeHTML(b.original)}</div></div><div class="row-actions"><button data-action="restore" data-id="${b.id}" class="install">恢复原位置</button></div></article>`).join('');
  } else {
    items=state.skills.filter(s=>(view==='all'||s.scope===view)&&(!project||s.scope!=='project'||s.project===project)&&[s.name,s.description,s.path].join(' ').toLowerCase().includes(query));
    const names = new Map();
    state.skills.filter(s=>s.scope!=='project'||!project||s.project===project).forEach(s=>names.set(s.name,(names.get(s.name)||0)+1));
    $('#list').innerHTML=items.map(s=>`<article class="skill-row"><div class="skill-icon" aria-hidden="true">${s.scope==='project'?'⌘':s.scope==='library'?'◇':'/>'}</div><div><div class="skill-name"><button class="name-button" data-action="detail" data-id="${s.id}">${escapeHTML(s.name)}</button><span class="badge ${s.scope}">${labels[s.scope]}</span>${names.get(s.name)>1?'<span class="badge duplicate">同名候选</span>':''}</div><p class="description">${escapeHTML(s.description||'未解析到描述，可点击名称查看完整 SKILL.md。')}</p><div class="path">${escapeHTML(s.path)}</div></div><div class="row-actions">${!s.readonly?`<button class="install" data-action="install" data-id="${s.id}">安装到…</button>`:'<span class="badge plugin">只读来源</span>'}${!s.readonly&&s.scope==='user'?`<button data-action="migrate" data-id="${s.id}">迁移到项目</button>`:''}${!s.readonly&&['user','project'].includes(s.scope)?`<button data-action="disable" data-id="${s.id}">停用</button>`:''}</div></article>`).join('');
  }
  $('#result-count').textContent=items.length+' 项';
  if(!items.length) $('#list').innerHTML=`<div class="empty"><strong>${query?'没有匹配的技能':view==='backups'?'尚无停用备份':view==='library'?'收藏你的第一项技能':view==='project'?'为项目准备专用技能':'这里还没有技能'}</strong><p>${query?'试试其他关键词，或调整项目筛选。':view==='library'?'导入本机的技能文件夹，再选择需要启用的作用域。':view==='project'?'从项目筛选中选择 Codex 项目，再按需安装技能。':'扫描结果会显示在这里。'}</p></div>`;
}
function openDialog(title, html, button, action) {
  $('#dialog-title').textContent=title; $('#dialog-body').innerHTML=html;
  $('#dialog-submit').textContent=button; $('#dialog-submit').hidden=!action; $('#dialog-error').hidden=true;
  submitAction=action;
  if(!dialog.open) dialog.showModal();
  queueMicrotask(()=>$('#dialog-body input, #dialog-body select')?.focus());
}
function projectOptions(){ return (state.projectDetails||state.projects.map(path=>({path,name:path,available:true,source:'manual'}))).map(p=>`<option value="${escapeHTML(p.path)}" title="${escapeHTML(p.path)}" ${p.available?'':'disabled'}>${escapeHTML(p.name)} · ${p.source==='codex'?'Codex':'手动'}${p.available?'':'（路径不可用）'}</option>`).join(''); }
async function preview(request) {
  const plan=await api('plan',request);
  openDialog('确认这次变更',`<p class="help">${escapeHTML(plan.effect)}</p><dl class="preview"><dt>源目录</dt><dd>${escapeHTML(plan.source)}</dd><dt>目标位置</dt><dd>${escapeHTML(plan.target)}</dd></dl><p class="help">预览有效期 5 分钟。已有会话的上下文不会随文件变更清除。</p>`,'执行变更',async()=>{
    const result=await api('apply',{token:plan.token});dialog.close();notice(result.message);await refresh();
  });
}
$('#dialog-submit').addEventListener('click',async()=>{
  const button=$('#dialog-submit'); if(!submitAction||button.disabled)return;
  button.disabled=true;$('#dialog-error').hidden=true;
  try {await submitAction();} catch(error){$('#dialog-error').textContent=error.message;$('#dialog-error').hidden=false;}
  finally {button.disabled=false;}
});
document.querySelectorAll('.close').forEach(button=>button.addEventListener('click',()=>dialog.close()));
$('#nav').addEventListener('click',event=>{const button=event.target.closest('[data-view]');if(!button)return;view=button.dataset.view;document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('selected',b===button);b.setAttribute('aria-current',b===button?'page':'false');});render();});
$('#search').addEventListener('input',render);$('#project').addEventListener('change',render);$('#refresh').addEventListener('click',refresh);
$('#add-project').addEventListener('click',()=>openDialog('手动添加项目','<label class="field">项目文件夹绝对路径<input id="project-path" placeholder="D:\\projects\\my-app" autocomplete="off"></label><p class="help">Codex 侧边栏项目已自动读取。此处可补充其他本机文件夹，不会修改项目文件。</p>','添加项目',async()=>{const path=$('#project-path').value.trim();if(!path)throw new Error('请输入项目路径。');await api('projects',{path});dialog.close();notice('项目已添加。');await refresh();}));
$('#import').addEventListener('click',()=>openDialog('导入技能到收藏库','<label class="field">技能文件夹绝对路径<input id="import-path" placeholder="D:\\skills\\my-skill" autocomplete="off"></label><p class="help">文件夹应包含 SKILL.md。脚本、引用和资源会一同复制，原文件保留。收藏库不参与 Codex 自动发现。</p>','预览导入',()=>{const path=$('#import-path').value.trim();if(!path)throw new Error('请输入技能文件夹路径。');return preview({operation:'import',path});}));
$('#list').addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  const {action,id}=button.dataset;
  try {
    if(action==='detail'){const item=state.skills.find(s=>s.id===id),result=await api('detail?id='+encodeURIComponent(id));openDialog(item.name,`<pre>${escapeHTML(result.content)}</pre>`,'',null);return;}
    if(action==='disable'||action==='restore'){await preview(action==='restore'?{operation:'restore',backupId:id}:{operation:'disable',skillId:id});return;}
    const migrate=action==='migrate';
    if(migrate&&!state.projects.length){notice('尚无可用项目，请刷新 Codex 项目列表或手动添加。',true);return;}
    openDialog(migrate?'迁移到指定项目':'选择启用位置',`${!migrate?'<label class="field">安装作用域<select id="install-scope"><option value="project">项目级 · 仅该项目</option><option value="user">用户级 · 所有项目</option><option value="library">收藏库 · 不自动启用</option></select></label>':''}<label class="field" id="target-project-field">目标项目<select id="target-project">${state.projects.length?projectOptions():'<option value="">请先添加项目</option>'}</select></label><p class="help">${migrate?'迁移会将用户级原目录移入备份区，只在所选项目保留启用副本。':'复制完整技能目录，不覆盖任何已有内容。复制到项目后，原用户级副本仍对所有项目可见。'}</p>`,'预览变更',()=>{const scope=migrate?'project':$('#install-scope').value,project=$('#target-project').value;if(scope==='project'&&!project)throw new Error('请选择路径可用的项目。');return preview({operation:action,skillId:id,scope,project});});
    if(!migrate)$('#install-scope').addEventListener('change',()=>{$('#target-project-field').hidden=$('#install-scope').value!=='project';});
  }catch(error){notice(error.message,true);}
});
refresh();
