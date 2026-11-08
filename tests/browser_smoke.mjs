// Optional local Edge smoke test. No packages, no skill mutations.
import {spawn} from 'node:child_process';
import {mkdir, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
const pause=ms=>new Promise(done=>setTimeout(done,ms));
await mkdir('.local',{recursive:true});
const browser=spawn('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',[
  '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--remote-debugging-port=9388','--remote-allow-origins=http://localhost:9388',
  '--user-data-dir='+resolve('.local/browser-test'),'about:blank'
],{windowsHide:true,stdio:'ignore'});
let socket;
try {
  let pages;
  for(let i=0;i<100;i++) {try {pages=await (await fetch('http://127.0.0.1:9388/json')).json();break;}catch{await pause(100);}}
  assert(pages,'Edge debugging endpoint unavailable');
  const page=pages.find(p=>p.type==='page');
  socket=new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((done,reject)=>{socket.addEventListener('open',done,{once:true});socket.addEventListener('error',reject,{once:true});});
  const pending=new Map();let seq=0;
  socket.addEventListener('message',event=>{const msg=JSON.parse(event.data);if(pending.has(msg.id)){const {done,reject,timer}=pending.get(msg.id);clearTimeout(timer);pending.delete(msg.id);msg.error?reject(new Error(JSON.stringify(msg.error))):done(msg.result);}});
  const cdp=(method,params={})=>new Promise((done,reject)=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout: '+method));},15000);pending.set(id,{done,reject,timer});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
  const until=async expression=>{for(let i=0;i<150;i++){if(await evaluate(expression))return;await pause(100);}throw new Error('UI timeout: '+expression);};
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:'http://127.0.0.1:8765'});
  await until("document.querySelectorAll('.skill-row').length > 0");
  const count=await evaluate("document.querySelectorAll('.skill-row').length");
  const state=await (await fetch('http://127.0.0.1:8765/api/state')).json();
  assert.equal(await evaluate("document.querySelectorAll('#project option').length"),state.projects.length+1);
  if(state.codexProjectCount) {
    assert((await evaluate("document.querySelector('#project-status').textContent")).includes(String(state.codexProjectCount)));
    const project=state.projectDetails.find(p=>p.source==='codex'&&p.available);
    if(project) {
      assert((await evaluate("Array.from(document.querySelectorAll('#project option')).map(o=>o.textContent).join('\\n')")).includes(project.name));
      await evaluate("document.querySelector('[data-action=install]').click()");
      assert.equal(await evaluate("document.querySelectorAll('#target-project option').length"),state.projects.length);
      await evaluate("document.querySelector('dialog .close').click()");
    }
  }
  await evaluate("document.querySelector('.name-button').click()");
  await until("document.querySelector('dialog').open && !!document.querySelector('pre')");
  await evaluate("document.querySelector('dialog .close').click(); document.querySelector('#search').value='zzzz_no_such_skill_999'; document.querySelector('#search').dispatchEvent(new Event('input'))");
  assert.equal(await evaluate("document.querySelectorAll('.skill-row').length"),0);
  await evaluate("document.querySelector('#search').value=''; document.querySelector('#search').dispatchEvent(new Event('input')); document.querySelector('#import').click()");
  assert.equal(await evaluate("document.activeElement.id"),'import-path');
  await evaluate("document.querySelector('dialog .close').click()");
  let shot=await cdp('Page.captureScreenshot',{format:'png'});
  await writeFile('.local/desktop.png',Buffer.from(shot.data,'base64'));
  for(const [width,height] of [[375,812],[812,375]]) {
    await cdp('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
    await cdp('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
    await pause(100);
    assert(await evaluate('document.documentElement.scrollWidth <= innerWidth'),'Horizontal overflow at '+width);
  }
  await cdp('Emulation.setDeviceMetricsOverride',{width:375,height:812,deviceScaleFactor:1,mobile:false});
  shot=await cdp('Page.captureScreenshot',{format:'png'});
  await writeFile('.local/mobile.png',Buffer.from(shot.data,'base64'));
  console.log(`Browser checks passed: ${count} skill rows; search, detail, modal focus, 375px and landscape overflow, reduced motion.`);
} finally {
  socket?.close();
  browser.kill();
}
