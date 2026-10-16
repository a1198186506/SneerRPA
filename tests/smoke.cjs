// Real Neutralino + extension + worker + Windows UIA integration.
const {chromium} = require('@playwright/test');
const {spawn, execFile} = require('node:child_process');
const {promisify} = require('node:util');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const python = path.join(root,'.venv/Scripts/python.exe');
const exec = promisify(execFile);
const delay = ms => new Promise(resolve => setTimeout(resolve,ms));
const {menuAction,newProject,reloadProject}=require('./ui-helpers.cjs');
const savedPath = path.join(root,'projectdata/current-flow.json');

(async()=>{
  let original;
  try{original=await fs.readFile(savedPath);}catch(e){if(e.code!=='ENOENT')throw e;}
  await fs.rm(path.join(root,'.tmp/auth_info.json'),{force:true});
  const runtime=spawn(path.join(root,'bin/neutralino-win_x64.exe'),['--load-dir-res','--path='+root,'--mode=cloud','--port=0','--export-auth-info'],{cwd:root,windowsHide:true,env:{...process.env,SNEERRPA_PROJECTS_DIR:path.join(root,'.tmp','projects-smoke-'+Date.now())}});
  let browser, fixture;
  try{
    let auth;
    for(let i=0;i<100;i++){
      try{auth=JSON.parse(await fs.readFile(path.join(root,'.tmp/auth_info.json'),'utf8'));if(auth.nlPort)break;}catch{}
      await delay(100);
    }
    assert(auth?.nlPort,'Neutralino core did not start');
    browser=await chromium.launch({channel:'msedge',headless:true});
    const page=await browser.newPage({viewport:{width:1440,height:960}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:'+auth.nlPort);
    await page.waitForFunction(()=>document.querySelector('#engine').textContent.includes('在线'));
    await require('./project-smoke.cjs')(page,root);
    await menuAction(page,'sample');
    await page.waitForFunction(()=>document.querySelectorAll('.node').length===10);
    console.log('PASS: catalog, native extension connection, sample flow');
    await page.locator('#run').click();
    await page.waitForFunction(()=>['执行成功','执行失败','启动失败'].includes(document.querySelector('#runstatus').textContent),null,{timeout:35000});
    assert.equal(await page.locator('#runstatus').innerText(),'执行成功',await page.locator('#logs').innerText());
    assert((await page.locator('#logs').innerText()).includes('已确认：Hello SneerRPA · 你好 RPA + {test}'));
    await page.locator('#tab-variables').click();
    assert((await page.locator('#variables').innerText()).includes('result_text'));
    assert.equal(await page.locator('.node.completed').count(),10);
    console.log('PASS: all nine window actions, Unicode input, click, read, variables, close');
    await require('./loop-smoke.cjs')(page,root);
    // A live target for the picker, independent of the flow executor.
    const openFlow=await page.evaluate(()=>structuredClone(flow));
    openFlow.steps=openFlow.steps.filter(s=>s.type!=='window.close');
    await page.locator('#file').setInputFiles({name:'open.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(openFlow))});
    await page.waitForFunction(()=>document.querySelectorAll('.node').length===9);
    fixture=true;
    await page.locator('#run').click();
    await page.waitForFunction(()=>['执行成功','执行失败'].includes(document.querySelector('#runstatus').textContent),null,{timeout:25000});
    assert.equal(await page.locator('#runstatus').innerText(),'执行成功',await page.locator('#logs').innerText());
    await page.locator('#tab-elements').click();
    await page.locator('#pick').click();
    await delay(1300);
    await exec(python,[path.join(root,'tests/desktop_probe.py'),'point'],{cwd:root,windowsHide:true,timeout:15000});
    await page.locator('#element-dialog').waitFor({state:'visible',timeout:15000});
    await page.locator('#element-name').fill('捕获的输入框');
    const selector=JSON.parse(await page.locator('#element-selector').inputValue());
    assert(selector.path.length>0,'Picker must capture a control rather than the top-level window');
    assert(!JSON.stringify(selector).includes('handle'),'Persisted selector must not contain runtime handles');
    await page.locator('#test-element').click();
    await page.waitForFunction(()=>document.querySelector('#selector-result').textContent.length>0,null,{timeout:15000});
    assert((await page.locator('#selector-result').innerText()).includes('定位成功'),(await page.locator('#selector-result').innerText())+' '+JSON.stringify(selector));
    await page.locator('#commit-element').click();
    await page.locator('#element-dialog').waitFor({state:'hidden'});
    await page.waitForFunction(()=>document.querySelector('#element-count').textContent==='4');
    console.log('PASS: pointer tracking, F8 capture, property path selector and live re-location');
    await page.locator('#tab-images').click();
    await page.locator('#pick-image').click();await delay(1100);
    const cropProbe=await exec(python,[path.join(root,'tests/desktop_probe.py'),'image-region'],{cwd:root,windowsHide:true,timeout:15000});
    const crop=JSON.parse(cropProbe.stdout);
    await page.locator('#image-dialog').waitFor({state:'visible',timeout:15000});
    const asset=await page.evaluate(()=>structuredClone(flow.images[0]));
    assert.equal(asset.width,crop.width);assert.equal(asset.height,crop.height);
    assert.deepEqual(asset.capture_rect,crop);
    assert(asset.data_url.startsWith('data:image/png;base64,iVBORw0KGgo'));
    await page.waitForFunction(()=>document.querySelector('#image-preview').naturalWidth>0);
    await page.locator('#image-name').fill('确认按钮图片');await page.locator('#commit-image').click();
    await page.waitForFunction(()=>document.querySelectorAll('.image-asset').length===1);
    await page.locator('.image-asset button').filter({hasText:'预览'}).click();
    await page.screenshot({path:path.join(root,'.tmp/image-library.png'),fullPage:true});
    await page.locator('#recapture-image').click();await delay(1000);
    await exec(python,[path.join(root,'tests/desktop_probe.py'),'image-region','reverse'],{cwd:root,windowsHide:true,timeout:15000});
    await page.waitForFunction(()=>!toolBusy);
    assert.equal(await page.evaluate(()=>flow.images[0].id),asset.id);
    assert.equal(await page.evaluate(()=>flow.images[0].name),'确认按钮图片');
    const recaptured=await page.evaluate(()=>flow.images[0].data_url);
    await page.locator('#recapture-image').click();await delay(800);
    await exec(python,[path.join(root,'tests/desktop_probe.py'),'cancel-image'],{cwd:root,windowsHide:true,timeout:15000});
    await page.waitForFunction(()=>!toolBusy);
    assert.equal(await page.evaluate(()=>flow.images[0].data_url),recaptured);
    await page.locator('#close-image').click();
    console.log('PASS: screen image selection, PNG preview, rename, reverse recapture and Esc cancellation');
    const editingFlow=await page.evaluate(()=>structuredClone(flow));
    await require('./logic-smoke.cjs')(page,editingFlow,root);
    await page.locator('#tab-actions').click();
    await page.locator('.action[data-type="mouse.click"]').click();
    assert.equal(await page.getByLabel('点击目标').inputValue(),'element');
    await page.getByLabel('点击目标').selectOption('coordinates');
    await page.getByRole('button',{name:'实时捕获坐标…'}).click();await delay(900);
    const pointProbe=await exec(python,[path.join(root,'tests/desktop_probe.py'),'point'],{cwd:root,windowsHide:true,timeout:15000});
    const point=JSON.parse(pointProbe.stdout);
    await page.waitForFunction(()=>!toolBusy);
    assert.equal(Number(await page.getByLabel('屏幕 X 坐标').inputValue()),point.x);
    assert.equal(Number(await page.getByLabel('屏幕 Y 坐标').inputValue()),point.y);
    const coordinateStep=await page.evaluate(()=>structuredClone(flow.steps.at(-1)));
    await page.getByRole('button',{name:'实时捕获坐标…'}).click();await delay(500);
    await page.getByRole('button',{name:'取消坐标捕获',exact:true}).click();
    await page.waitForFunction(()=>!toolBusy);
    assert.equal(Number(await page.getByLabel('屏幕 X 坐标').inputValue()),point.x);
    console.log('PASS: real-time coordinate picker, F8 capture, cancellation preserves coordinates');
    await page.locator('.action[data-type="keyboard.input"]').click();
    assert.equal(await page.locator('#properties input,#properties select,#properties textarea').count(),1);
    const keyboardText='鼠标键盘 😀 中文 +^% {ENTER}';
    await page.getByLabel('要输入的文本').fill(keyboardText);await page.getByLabel('要输入的文本').blur();
    const keyboardStep=await page.evaluate(()=>structuredClone(flow.steps.at(-1)));
    const interactionFlow=structuredClone(editingFlow);
    const windowStep=structuredClone(editingFlow.steps.find(s=>s.type==='window.get'));windowStep.params.process_id='';
    interactionFlow.steps=[windowStep,
      {id:'clear-input',name:'清空输入框',type:'element.input',params:{element:'sample-input',window:'main_window',text:''}},
      coordinateStep,keyboardStep,
      {id:'mouse-confirm',name:'鼠标点击确认',type:'mouse.click',params:{target_mode:'element',element:'sample-confirm'}},
      {id:'read-keyboard',name:'读取键盘输入结果',type:'element.read',params:{element:'sample-result',window:'main_window',info:'value',output:'keyboard_result'}},
      {id:'log-keyboard',name:'输出键盘结果',type:'log',params:{message:'${keyboard_result}'}}];
    await page.locator('#file').setInputFiles({name:'mouse-keyboard.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(interactionFlow))});
    await page.waitForFunction(()=>document.querySelectorAll('.node').length===7);
    await page.locator('#run').click();
    await page.waitForFunction(()=>['执行成功','执行失败','启动失败'].includes(document.querySelector('#runstatus').textContent),null,{timeout:20000});
    assert.equal(await page.locator('#runstatus').innerText(),'执行成功',await page.locator('#logs').innerText());
    assert((await page.locator('#logs').innerText()).includes('已确认：'+keyboardText));
    await reloadProject(page);await page.waitForFunction(()=>document.querySelectorAll('.node').length===7);
    assert.equal(await page.evaluate(()=>flow.steps.find(s=>s.type==='mouse.click').params.x),point.x);
    assert.equal(await page.evaluate(()=>flow.steps.find(s=>s.type==='keyboard.input').params.text),keyboardText);
    await page.locator('#file').setInputFiles({name:'restore.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(editingFlow))});
    await page.waitForFunction(()=>document.querySelectorAll('.node').length===9);
    console.log('PASS: coordinate click -> literal keyboard input -> element mouse click; persistence');
    // Source switching controls both visible fields and the real execution target.
    await page.locator('.node[data-id="sample-window"]').click();
    assert.equal(await page.getByLabel('窗口获取方式').inputValue(),'criteria');
    await page.getByLabel('窗口获取方式').selectOption('variable');
    assert.equal(await page.getByLabel('窗口变量',{exact:true}).count(),1);
    assert.equal(await page.getByLabel('窗口标题',{exact:true}).count(),0);
    await page.getByLabel('窗口获取方式').selectOption('criteria');
    assert.equal(await page.getByLabel('窗口标题',{exact:true}).count(),1);
    await page.locator('#tab-actions').click();
    await page.locator('.action[data-type="window.close"]').click();
    assert.equal(await page.getByLabel('窗口获取方式').inputValue(),'element');
    for(const id of ['sample-window','sample-activate','sample-state',await page.evaluate(()=>flow.steps.at(-1).id)]){
      await page.locator(`.node[data-id="${id}"]`).click();
      await page.getByLabel('窗口获取方式').selectOption('element');
      await page.getByLabel('定位窗口的元素').selectOption('sample-confirm');
      assert((await page.locator('.target-preview').innerText()).includes('SneerRPA 节点测试台'));
      assert.equal(await page.getByLabel('窗口变量',{exact:true}).count(),0);
    }
    assert((await page.locator('.target-preview').innerText()).includes('将关闭整个窗口'));
    await page.locator('.action[data-type="element.read"]').click();
    assert.equal(await page.evaluate(()=>flow.steps.at(-1).params.window),'');
    assert.equal(await page.getByLabel('窗口变量（可选）').isVisible(),false);
    await page.locator('.advanced-settings > summary').click();
    assert.equal(await page.getByLabel('窗口变量（可选）').isVisible(),true);
    await page.getByRole('button',{name:'删除步骤',exact:true}).click();
    console.log('PASS: window source selection, owner preview, advanced control window override');
    // File selection keeps spaces/Unicode as a single program path.
    await page.locator('.node[data-id="sample-launch"]').click();
    const originalProgram=await page.getByLabel('程序或文件路径').inputValue();
    await page.evaluate(()=>{window.__oldOpenDialog=Neutralino.os.showOpenDialog;Neutralino.os.showOpenDialog=async()=>['F:/带 空格/demo.exe'];});
    await page.getByRole('button',{name:'浏览程序或文件…'}).click();
    await page.waitForFunction(()=>document.querySelector('#properties input')&&flow.steps[0].params.path==='F:/带 空格/demo.exe');
    await page.getByLabel('程序或文件路径').fill(originalProgram);await page.getByLabel('程序或文件路径').blur();
    await page.evaluate(()=>{Neutralino.os.showOpenDialog=window.__oldOpenDialog;delete window.__oldOpenDialog;});
    console.log('PASS: browse program/file path with spaces and Unicode');
    // Reuse the actual captured element in a new execution, not just a mock selector.
    const pickedFlow=await page.evaluate(()=>structuredClone(flow));
    const captured=pickedFlow.elements.find(e=>e.name==='捕获的输入框');
    pickedFlow.steps.find(s=>s.type==='element.input').params.element=captured.id;
    pickedFlow.steps.find(s=>s.type==='element.input').params.text='Captured selector + 中文 {ok}';
    await exec(python,[path.join(root,'tests/desktop_probe.py'),'close'],{cwd:root,windowsHide:true,timeout:10000});fixture=null;
    await page.locator('#file').setInputFiles({name:'picked.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(pickedFlow))});
    await page.waitForFunction(()=>document.querySelectorAll('.node').length===10);
    await page.locator('#run').click();
    await page.waitForFunction(()=>['执行成功','执行失败'].includes(document.querySelector('#runstatus').textContent),null,{timeout:20000});
    assert.equal(await page.locator('#runstatus').innerText(),'执行成功',await page.locator('#logs').innerText());
    assert((await page.locator('#logs').innerText()).includes('已确认：Captured selector + 中文 {ok}'));
    console.log('PASS: captured selector survives target application restart');
    const downloadPromise=page.waitForEvent('download');await menuAction(page,'save');
    const download=await downloadPromise, exportPath=path.join(root,'.tmp/exported-flow.json');await download.saveAs(exportPath);
    const exported=JSON.parse(await fs.readFile(exportPath,'utf8'));assert.equal(exported.elements.length,4);
    await reloadProject(page);
    await page.waitForFunction(()=>document.querySelectorAll('.node').length===10&&document.querySelector('#element-count').textContent==='5');
    assert.equal(await page.evaluate(()=>flow.images[0].data_url),recaptured);
    assert.equal(exported.images[0].name,'确认按钮图片');
    const largeProbe=await exec(python,['-c',"import sys,json,os;sys.path.insert(0,'extensions');from PIL import Image;from image_assets import encode_crop;print(json.dumps(encode_crop(Image.frombytes('RGB',(640,480),os.urandom(640*480*3)),(0,0,640,480))))"],{cwd:root,windowsHide:true,timeout:10000,maxBuffer:4*1024*1024});
    const largeAsset=JSON.parse(largeProbe.stdout);assert(largeAsset.data_url.length>1024*1024);
    const roundtrip=await page.evaluate(async image=>{
      const saved=structuredClone(flow),large=structuredClone(flow);large.images=[image];
      await request('save_flow',{flow:large});const loaded=await request('load_flow');await request('save_flow',{flow:saved});
      return loaded.flow.images[0].data_url;
    },largeAsset);
    assert.equal(roundtrip,largeAsset.data_url);
    console.log('PASS: image payload over 1 MB round-trips through native extension and local storage');
    console.log('PASS: export includes selectors; local project survives reload');
    // Exercise native filesystem IPC; mock only user file-path selection dialogs.
    const nativePath=path.join(root,'.tmp/native-flow.json');
    await page.evaluate(p=>{window.NL_MODE='window';Neutralino.os.showSaveDialog=async()=>p;Neutralino.os.showOpenDialog=async()=>[p];},nativePath);
    await menuAction(page,'save');
    for(let i=0;i<30;i++){try{await fs.access(nativePath);break;}catch{}await delay(100);}
    assert.equal(JSON.parse(await fs.readFile(nativePath,'utf8')).elements.length,4);
    await newProject(page);await menuAction(page,'open');
    await page.waitForFunction(()=>document.querySelectorAll('.node').length===10);
    await page.evaluate(()=>{window.NL_MODE='cloud';});
    console.log('PASS: desktop import/export via real native filesystem IPC');
    assert.equal(await page.evaluate(()=>flow.images[0].data_url),recaptured);
    await page.locator('#tab-elements').click();
    await page.locator('#tab-images').click();
    await page.locator('.image-asset button').filter({hasText:'删除'}).click();
    assert.equal(await page.evaluate(()=>flow.images.length),0);
    console.log('PASS: image bytes survive export/import/reload; image deletion');
    // Malformed/incomplete flow must fail before launching any program.
    const bad=structuredClone(pickedFlow);bad.steps.find(s=>s.type==='element.input').params.element='missing';
    const invalid=await page.evaluate(async f=>{try{await request('run_flow',{flow:f});return '';}catch(e){return e.message;}},bad);
    assert(invalid.includes('目标元素'));
    console.log('PASS: bad element references are rejected before execution');
    await newProject(page);
    await page.locator('#tab-actions').click();
    await page.locator('.action[data-type="wait"]').click();
    await page.getByLabel('等待时间（秒）').fill('30');await page.getByLabel('等待时间（秒）').blur();
    await page.locator('#run').click();
    await page.waitForFunction(()=>!document.querySelector('#stop').disabled);await page.locator('#stop').click();
    await page.waitForFunction(()=>document.querySelector('#runstatus').textContent==='已停止');
    await page.getByLabel('等待时间（秒）').fill('-1');await page.getByLabel('等待时间（秒）').blur();
    await page.locator('#run').click();await page.waitForFunction(()=>document.querySelector('#runstatus').textContent==='启动失败');
    console.log('PASS: cancel process; invalid numeric parameters rejected');
    await page.waitForFunction(()=>document.querySelector('#saved').textContent==='已保存到本地');
    await reloadProject(page);await page.waitForFunction(()=>document.querySelectorAll('.node').length===1);
    assert.equal(await page.getByLabel('等待时间（秒）').inputValue(),'-1');
    console.log('PASS: incomplete or invalid drafts survive reload without executing');
    // Picker cancellation must release the helper slot and keep the engine usable.
    await page.locator('#tab-elements').click();await page.locator('#tab-controls').click();await page.locator('#pick').click();await delay(700);
    await page.locator('#cancel-pick').click();await page.waitForFunction(()=>!document.querySelector('#pick').disabled);
    console.log('PASS: picker cancellation and helper cleanup');
    await menuAction(page,'sample');await page.locator('#tab-actions').click();await page.locator('#tab-logs').click();
    await page.screenshot({path:path.join(root,'.tmp/smoke.png'),fullPage:true});
    assert.deepEqual(errors,[]);console.log('PASS: no browser script errors');
  }finally{
    if(fixture)await exec(python,[path.join(root,'tests/desktop_probe.py'),'close'],{cwd:root,windowsHide:true,timeout:10000}).catch(()=>{});
    if(browser)await browser.close();
    runtime.kill();await delay(900);
    if(original){await fs.mkdir(path.dirname(savedPath),{recursive:true});await fs.writeFile(savedPath,original);}
    else await fs.rm(savedPath,{force:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
