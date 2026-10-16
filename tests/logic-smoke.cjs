const assert=require('node:assert/strict');
const path=require('node:path');
const {reloadProject}=require('./ui-helpers.cjs');

module.exports=async function(page,editingFlow,root){
  const node=(id,type,params)=>({id,type,name:id,params});
  const main=structuredClone(editingFlow.steps.find(s=>s.type==='window.get'));
  main.params.process_id='';
  const condition=node('found-if','control.if',{left:'image_match.found',operator:'==',right_type:'bool',right_boolean:true});
  const nested=node('number-if','control.if',{left:'count',operator:'>=',right_source:'reference',right_reference:'minimum'});
  nested.then_steps=[node('numeric-log','log',{message:'NUMBER_BRANCH_OK'})];
  nested.else_steps=[node('wrong-number','log',{message:'NUMBER_BRANCH_WRONG'})];
  condition.then_steps=[node('image-click','mouse.click',{target_mode:'position',position:'image_match.center'}),nested];
  condition.else_steps=[node('wrong-image','log',{message:'IMAGE_BRANCH_WRONG'})];
  const logic=structuredClone(editingFlow);
  logic.steps=[main,
    node('window-alias','variable.set',{output:'target_window',value_type:'window',source:'reference',source_variable:'main_window'}),
    node('activate','window.activate',{target_mode:'variable',window:'target_window'}),
    node('exists','window.exists',{target_mode:'variable',window:'target_window',output:'window_present'}),
    node('count','variable.set',{output:'count',value_type:'number',value_number:5}),
    node('minimum','variable.set',{output:'minimum',value_type:'number',value_number:3}),
    node('find-image','image.find',{image:logic.images[0].id,scope:'window',search_window:'main_window',threshold:.8,timeout:1,ambiguity:'best',output:'image_match'}),
    condition,
    node('absent','window.exists',{target_mode:'criteria',title:'SneerRPA definitely absent 492720',timeout:0,output:'absent_window'}),
    node('logic-log','log',{message:'LOGIC_OK present=${window_present} absent=${absent_window} found=${image_match.found}'})];
  const upload=async f=>{
    await page.locator('#file').setInputFiles({name:'logic.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(f))});
    await page.waitForFunction(()=>flow.steps.some(s=>s.id==='found-if'));
  };
  await upload(logic);
  await page.locator('.node[data-id="find-image"]').click();
  assert.equal(await page.getByLabel('目标图片').inputValue(),logic.images[0].id);
  await page.getByRole('button',{name:'测试找图',exact:true}).click();
  await page.waitForFunction(()=>!toolBusy);
  assert((await page.locator('#logs').innerText()).includes('找图成功'),await page.locator('#logs').innerText());
  await page.locator('#run').click();
  await page.waitForFunction(()=>['执行成功','执行失败','启动失败'].includes(document.querySelector('#runstatus').textContent),null,{timeout:25000});
  assert.equal(await page.locator('#runstatus').innerText(),'执行成功',await page.locator('#logs').innerText());
  const logs=await page.locator('#logs').innerText();
  assert(logs.includes('NUMBER_BRANCH_OK'));assert(logs.includes('LOGIC_OK present=true absent=false found=true'));
  assert(!logs.includes('BRANCH_WRONG'));
  assert.equal(await page.locator('.node.skipped').count(),2);
  assert.equal(await page.evaluate(()=>variableTypes.target_window),'window');
  const point=await page.evaluate(()=>variables.image_match.center);
  assert(Number.isInteger(point.x)&&Number.isInteger(point.y));
  console.log('PASS: OpenCV live window matching, test/highlight, typed window alias, window exists, nested IF and center click');

  // Edit a real nested branch through the palette, then move it using drag/drop.
  await page.locator('.add-step[data-target="found-if:else_steps"]').click();
  await page.locator('.action-choice[data-type="variable.set"]').click();
  await page.getByLabel('变量类型').selectOption('string');
  await page.getByLabel('变量名称',{exact:true}).fill('branch_text');await page.getByLabel('变量名称',{exact:true}).blur();
  const added=await page.evaluate(()=>findStep('found-if').else_steps.at(-1).id);
  assert.equal(await page.evaluate(id=>FlowModel.before(flow.steps,id).types.count,added),'number');
  const transfer=await page.evaluateHandle(()=>new DataTransfer());
  await transfer.evaluate((dt,id)=>dt.setData('step',id),added);
  await page.locator('.branch-box[data-target="found-if:then_steps"]').dispatchEvent('drop',{dataTransfer:transfer});
  assert.equal(await page.evaluate(()=>findStep('found-if').then_steps.at(-1).params.output),'branch_text');
  await transfer.evaluate(dt=>dt.setData('step','found-if'));
  await page.locator('.branch-box[data-target="found-if:then_steps"]').dispatchEvent('drop',{dataTransfer:transfer});
  assert.equal(await page.evaluate(()=>flow.steps.filter(s=>s.id==='found-if').length),1);
  await page.locator('.node[data-id="number-if"]').click();
  assert.equal(await page.getByLabel('左侧变量').inputValue(),'count');
  assert.equal(await page.getByLabel('比较运算符').inputValue(),'>=');
  await page.screenshot({path:path.join(root,'.tmp/logic-editor.png'),fullPage:true});
  await page.waitForFunction(()=>document.querySelector('#saved').textContent==='已保存到本地');
  await reloadProject(page);
  await page.waitForFunction(()=>typeof flow!=='undefined'&&flow.steps.some(s=>s.id==='found-if'));
  assert.equal(await page.evaluate(()=>findStep('found-if').then_steps.at(-1).params.output),'branch_text');
  assert.equal(await page.evaluate(()=>findStep('number-if').else_steps[0].id),'wrong-number');
  console.log('PASS: branch insertion, typed property editors, cross-branch drag/drop, cycle prevention and nested persistence');
  await page.locator('#file').setInputFiles({name:'restore.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(editingFlow))});
  await page.waitForFunction(()=>document.querySelectorAll('.node').length===9);
};
