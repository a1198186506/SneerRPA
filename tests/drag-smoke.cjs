// Exercise actual HTML drag events in the editor, with persistence kept in memory.
const {chromium}=require('@playwright/test');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const {createProject}=require('./ui-helpers.cjs');
const bridge=`const handlers={};let saved=JSON.parse(localStorage.getItem('test-flow')||'null')||{schema_version:1,name:'拖拽测试',steps:[],elements:[]};
let projects=JSON.parse(localStorage.getItem('test-projects')||'{}');
window.Neutralino={events:{on:(name,fn)=>handlers[name]=fn},init:()=>queueMicrotask(()=>handlers.ready()),extensions:{dispatch:async(id,event,data)=>{
 let response={};
 if(data.command==='list_projects')response.projects=Object.values(projects).map(p=>({...p,step_count:0}));
 if(data.command==='create_project'){const id=crypto.randomUUID(),name=data.name;projects[id]={id,name,updated_at:new Date().toISOString(),flow:data.flow||{schema_version:1,name,steps:[],elements:[]}};response.project=projects[id];}
 if(data.command==='load_project')response.project=projects[data.project_id];
 if(data.command==='save_project'){projects[data.project_id].flow=structuredClone(data.flow);response.project_id=data.project_id;}
 localStorage.setItem('test-projects',JSON.stringify(projects));
 if(data.command==='save_flow'){saved=structuredClone(data.flow);localStorage.setItem('test-flow',JSON.stringify(saved));}
 queueMicrotask(()=>handlers.rpa({detail:{event:'response',request_id:data.request_id,flow:structuredClone(saved),...structuredClone(response)}}));
}}};`;
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://localhost:47839/**',async route=>{
   const pathname=new URL(route.request().url()).pathname;
   if(pathname==='/js/neutralino.js')return route.fulfill({contentType:'application/javascript',body:bridge});
   const files={'/':'index.html','/style.css':'style.css','/app.js':'app.js','/flow-model.js':'flow-model.js','/editor-layout.js':'editor-layout.js','/actions.json':'actions.json'};
   if(!files[pathname])return route.fulfill({status:404});
   const body=await fs.readFile(path.join(root,'resources',files[pathname]));
   await route.fulfill({body,contentType:pathname.endsWith('.js')?'application/javascript':pathname.endsWith('.json')?'application/json':pathname.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('http://localhost:47839/');await page.waitForFunction(()=>ready&&loaded);
  await createProject(page,'拖拽测试');
  await page.locator('.action[data-type="log"]').click();
  const first=await page.evaluate(()=>flow.steps[0].id);
  const card=page.locator('.action[data-type="wait"]');
  await card.dragTo(page.locator(`.node[data-id="${first}"]`),{targetPosition:{x:100,y:8}});
  assert.deepEqual(await page.evaluate(()=>flow.steps.map(s=>s.type)),['wait','log']);
  const bounds=await page.locator(`.node[data-id="${first}"]`).boundingBox();
  await card.dragTo(page.locator(`.node[data-id="${first}"]`),{targetPosition:{x:100,y:bounds.height-8}});
  assert.deepEqual(await page.evaluate(()=>flow.steps.map(s=>s.type)),['wait','log','wait']);
  console.log('PASS: palette drag onto upper/lower half inserts before/after');
  const last=await page.evaluate(()=>flow.steps.at(-1).id);
  await page.locator(`.node[data-id="${last}"]`).dragTo(page.locator(`.node[data-id="${first}"]`),{targetPosition:{x:100,y:8}});
  assert.equal(await page.evaluate(()=>flow.steps[1].id),last);
  const head=await page.evaluate(()=>flow.steps[0].id);
  await page.locator(`.node[data-id="${head}"]`).dragTo(page.locator(`.node[data-id="${first}"]`),{targetPosition:{x:100,y:bounds.height-8}});
  assert.deepEqual(await page.evaluate(()=>flow.steps.map(s=>s.id)),[last,first,head]);
  await card.dragTo(page.locator('#flow > .drop-slot').first());
  assert.equal(await page.evaluate(()=>flow.steps[0].type),'wait');
  await card.dragTo(page.locator('#flow > .drop-slot').last());
  assert.equal(await page.evaluate(()=>flow.steps.at(-1).type),'wait');
  console.log('PASS: existing-node reordering and gap insertion at beginning/end');
  await page.locator('.action[data-type="control.if"]').click();
  const ifId=await page.evaluate(()=>flow.steps.at(-1).id);
  const branch=`.branch-box[data-target="${ifId}:then_steps"]`;
  await card.dragTo(page.locator(branch+' > .drop-slot').last());
  const child=await page.evaluate(id=>findStep(id).then_steps[0].id,ifId);
  await page.locator('.action[data-type="log"]').dragTo(page.locator(`.node[data-id="${child}"]`),{targetPosition:{x:80,y:8}});
  const childBox=await page.locator(`.node[data-id="${child}"]`).boundingBox();
  await page.locator('.action[data-type="log"]').dragTo(page.locator(`.node[data-id="${child}"]`),{targetPosition:{x:80,y:childBox.height-8}});
  assert.deepEqual(await page.evaluate(id=>findStep(id).then_steps.map(s=>s.type),ifId),['log','wait','log']);
  // Dragover feedback must agree with drop placement, then clear on cancel.
  const transfer=await page.evaluateHandle(()=>{const d=new DataTransfer();d.setData('action','wait');return d;});
  const target=page.locator(`.node[data-id="${child}"]`),rect=await target.boundingBox();
  await target.dispatchEvent('dragover',{dataTransfer:transfer,clientY:rect.y+2});
  assert((await target.getAttribute('class')).includes('drop-before'));
  await target.dispatchEvent('dragover',{dataTransfer:transfer,clientY:rect.y+rect.height-2});
  assert((await target.getAttribute('class')).includes('drop-after'));
  await page.screenshot({path:path.join(root,'.tmp/drag-insertion.png')});
  await target.dispatchEvent('dragend',{dataTransfer:transfer});
  assert.equal(await page.locator('.drop-before,.drop-after,.drop-active').count(),0);
  await target.click({button:'right'});
  assert.equal(await page.locator('#node-menu').count(),1);
  assert.equal(await page.evaluate(()=>selected),child);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#node-menu').count(),0);
  await target.click({button:'right'});
  await page.getByRole('menuitem',{name:'删除节点',exact:true}).click();
  assert.equal(await page.evaluate(id=>!!findStep(id),child),false);
  assert.deepEqual(await page.evaluate(id=>findStep(id).then_steps.map(s=>s.type),ifId),['log','log']);
  // Right click must act on its own node, even when another is selected.
  await page.locator(`.node[data-id="${ifId}"]`).click({button:'right'});
  await page.screenshot({path:path.join(root,'.tmp/node-menu.png')});
  await page.getByRole('menuitem',{name:'删除节点',exact:true}).click();
  assert.equal(await page.evaluate(id=>!!findStep(id),ifId),false);
  assert.equal(await page.locator('.branch-box').count(),0);
  const remaining=page.locator('.node').first();
  await remaining.click({button:'right'});await page.locator('header').click();
  assert.equal(await page.locator('#node-menu').count(),0);
  await page.evaluate(()=>{busy=true;});
  await remaining.click({button:'right'});
  assert.equal(await page.locator('#node-menu').count(),0);
  await page.evaluate(()=>{busy=false;});
  await require('./loop-editor.cjs')(page,root);
  await require('./layout-smoke.cjs')(page,root);
  assert.deepEqual(errors,[]);
  console.log('PASS: nested branch placement, insertion hints and drag cancellation cleanup');
  console.log('PASS: node context menu, branch deletion, IF subtree deletion, Escape/outside dismissal and run protection');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
