// Verify the real installed app with no development Python or Node on PATH.
const {chromium}=require('@playwright/test');
const {spawn}=require('node:child_process');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const {menuAction,createProject}=require('./ui-helpers.cjs');
const root=path.resolve(__dirname,'..');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const exit=child=>new Promise((resolve,reject)=>{child.on('error',reject);child.on('exit',resolve);});
(async()=>{
 const app=path.resolve(process.argv[2]);
 const dir=path.join(root,'.tmp','installer-verification-'+Date.now());await fs.mkdir(dir,{recursive:true});
 const data=path.join(dir,'user-data');
 const env={...process.env,PATH:'C:\\Windows\\System32;C:\\Windows;C:\\Windows\\System32\\WindowsPowerShell\\v1.0',SNEERRPA_DATA_DIR:data};
 for(const key of Object.keys(env))if(['pythonhome','pythonpath','psmodulepath','sneerrpa_projects_dir'].includes(key.toLowerCase()))delete env[key];
 await fs.rm(path.join(app,'.tmp/auth_info.json'),{force:true});
 const runtime=spawn(path.join(app,'SneerRPA.exe'),['--mode=cloud','--port=0','--export-auth-info'],{cwd:dir,windowsHide:true,env});
 let browser;
 try{
  let auth;for(let i=0;i<150;i++){try{auth=JSON.parse(await fs.readFile(path.join(app,'.tmp/auth_info.json'),'utf8'));if(auth.nlPort)break;}catch{}await delay(100);}
  assert(auth?.nlPort,'Installed Neutralino did not start from unrelated working directory');
  browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:960}});
  await page.goto('http://127.0.0.1:'+auth.nlPort);
  await page.waitForFunction(()=>ready&&loaded,null,{timeout:20000});
  await createProject(page,'安装版测试项目');await menuAction(page,'sample');
  await page.waitForFunction(()=>document.querySelectorAll('.node').length===10);
  await page.locator('#run').click();
  await page.waitForFunction(()=>['执行成功','执行失败','启动失败'].includes(document.querySelector('#runstatus').textContent),null,{timeout:40000});
  assert.equal(await page.locator('#runstatus').innerText(),'执行成功',await page.locator('#logs').innerText());
  assert((await page.locator('#logs').innerText()).includes('已确认：Hello SneerRPA · 你好 RPA + {test}'));
  console.log('PASS: installed editor, bundled extension and sample all 10 nodes, with system-only PATH');
  await delay(900);
  assert((await fs.readdir(path.join(data,'projects'))).some(n=>n.endsWith('.json')),'Projects must be saved outside installation directory');
  await menuAction(page,'export-exe');
  await page.locator('#export-exe-directory').fill(dir);
  await page.locator('#export-exe-filename').fill('安装版导出测试');
  await page.locator('#start-export-exe').click();
  await page.waitForFunction(()=>!exportBusy,null,{timeout:240000});
  const executable=path.join(dir,'安装版导出测试.exe');
  assert((await fs.stat(executable)).size>1000000,await page.locator('#export-exe-status').innerText());
  const events=path.join(dir,'events.jsonl');
  const worker=spawn(executable,['--sneerrpa-worker','--events',events],{cwd:dir,env,windowsHide:true});
  let timer;let code;
  try{code=await Promise.race([exit(worker),new Promise((_,reject)=>{timer=setTimeout(()=>{worker.kill();reject(Error('Exported workflow timeout'));},45000);})]);}finally{clearTimeout(timer);}
  const output=(await fs.readFile(events,'utf8')).trim().split('\n').map(s=>JSON.parse(s));
  assert.equal(code,0,JSON.stringify(output));
  assert.equal(output.filter(e=>e.event==='node_finished').length,10,JSON.stringify(output));
  console.log('PASS: installed Python exports a standalone EXE; exported sample executes all 10 nodes');
  await page.screenshot({path:path.join(dir,'installed-editor.png')});
  console.log('Verification directory: '+dir);
 }finally{if(browser)await browser.close();runtime.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
