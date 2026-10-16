const {chromium}=require('@playwright/test');
const {spawn,execFile}=require('node:child_process');
const {promisify}=require('node:util');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const {menuAction}=require('./ui-helpers.cjs');
const exec=promisify(execFile),root=path.resolve(__dirname,'..'),python=path.join(root,'.venv/Scripts/python.exe');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 const dir=path.join(root,'.tmp','exe-test-'+Date.now());await fs.mkdir(dir,{recursive:true});
 let browser,runtime,fixture=false;
 try{
  const prepared=await exec(python,[path.join(root,'tests/exe_fixture.py')],{cwd:root,windowsHide:true,timeout:20000});fixture=true;
  const flow=JSON.parse(prepared.stdout);
  await fs.rm(path.join(root,'.tmp/auth_info.json'),{force:true});
  runtime=spawn(path.join(root,'bin/neutralino-win_x64.exe'),['--load-dir-res','--path='+root,'--mode=cloud','--port=0','--export-auth-info'],{cwd:root,windowsHide:true,env:{...process.env,SNEERRPA_PROJECTS_DIR:path.join(dir,'projects')}});
  let auth;for(let i=0;i<100;i++){try{auth=JSON.parse(await fs.readFile(path.join(root,'.tmp/auth_info.json'),'utf8'));if(auth.nlPort)break;}catch{}await delay(100);}
  browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+auth.nlPort);await page.waitForFunction(()=>ready&&loaded);
  await page.locator('#file').setInputFiles({name:'frozen.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(flow))});
  await page.waitForFunction(()=>view==='editor'&&!switching);
  await menuAction(page,'export-exe');
  await page.evaluate(directory=>{Neutralino.os.showFolderDialog=async()=>directory;},dir);
  await page.locator('#browse-export-directory').click();assert.equal(await page.locator('#export-exe-directory').inputValue(),dir);
  await page.locator('#export-exe-filename').fill('取消测试.exe');await page.locator('#start-export-exe').click();
  await page.waitForFunction(()=>exportId!==null);await page.locator('#cancel-export-exe').click();
  await page.waitForFunction(()=>!exportBusy,null,{timeout:15000});
  assert((await page.locator('#export-exe-status').innerText()).includes('取消'));
  await assert.rejects(fs.access(path.join(dir,'取消测试.exe')));
  console.log('PASS: folder selection, EXE filename form, export cancellation and child-process cleanup');
  await page.locator('#export-exe-filename').fill('独立 工作流.exe');await page.locator('#start-export-exe').click();
  await page.waitForFunction(()=>!exportBusy,null,{timeout:420000});
  const status=await page.locator('#export-exe-status').innerText();
  await page.screenshot({path:path.join(root,'.tmp/exe-export.png'),fullPage:true});
  assert(status.includes('导出完成'),status+'\n'+await page.locator('#export-exe-log').innerText());
  const executable=path.join(dir,'独立 工作流.exe');const stat=await fs.stat(executable);assert(stat.size>1024*1024);
  console.log('PASS: actual PyInstaller single-file export, '+Math.round(stat.size/1024/1024)+' MB');
  const env={...process.env,PATH:'C:\\Windows\\System32;C:\\Windows'};delete env.PYTHONPATH;delete env.PYTHONHOME;
  const events=path.join(dir,'frozen-events.jsonl'),start=path.join(dir,'start');
  const running=spawn(executable,['--sneerrpa-worker','--events',events,'--start',start],{cwd:dir,windowsHide:true,env});
  const exited=new Promise(resolve=>running.on('exit',code=>resolve(code)));
  let readyWorker=false;for(let i=0;i<250;i++){try{readyWorker=(await fs.readFile(events,'utf8')).includes('worker_ready');if(readyWorker)break;}catch{}if(running.exitCode!==null)break;await delay(100);}
  assert(readyWorker,'Frozen worker failed to start');await fs.writeFile(start,'');
  const code=await Promise.race([exited,delay(30000).then(()=>{running.kill();throw Error('Frozen worker timeout');})]);
  const output=(await fs.readFile(events,'utf8')).trim().split('\n').map(line=>JSON.parse(line));
  assert.equal(code,0,JSON.stringify(output));assert(output.some(e=>e.event==='run_finished'&&e.status==='completed'));
  assert(output.some(e=>e.name==='match'&&e.value.found===true),JSON.stringify(output));
  assert(output.some(e=>e.name==='typed_value'&&e.value==='Frozen RPA 中文'),JSON.stringify(output));
  assert(output.some(e=>e.message?.startsWith('FROZEN_DONE 已确认：')),JSON.stringify(output));
  assert.equal(output.filter(e=>e.event==='log'&&e.message.startsWith('FROZEN_LOOP_')).length,3);
  console.log('PASS: exported EXE without Python on PATH runs typed variables, loops, Windows UIA, OpenCV image match and center click');
  await exec(python,[path.join(root,'tests/exe_gui_probe.py'),executable],{cwd:dir,windowsHide:true,timeout:45000});
  console.log('PASS: exported GUI Run / Stop / rerun and independent startup');
  await page.locator('#start-export-exe').click();await page.waitForFunction(()=>!exportBusy);
  assert((await page.locator('#export-exe-status').innerText()).includes('已存在'));
  assert.equal((await fs.stat(executable)).size,stat.size);assert.deepEqual(errors,[]);
  console.log('PASS: existing EXE is preserved and no browser errors');
 }finally{
  if(fixture)await exec(python,[path.join(root,'tests/desktop_probe.py'),'close'],{cwd:root,windowsHide:true,timeout:10000}).catch(()=>{});
  if(browser)await browser.close();if(runtime)runtime.kill();
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
