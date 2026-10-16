const assert=require('node:assert/strict');
const path=require('node:path');
const {reloadProject}=require('./ui-helpers.cjs');
module.exports=async(page,root)=>{
 const initial={schema_version:1,name:'循环编辑测试',elements:[],steps:[
  {id:'n',type:'variable.set',name:'次数',params:{output:'count',value_type:'number',value_number:3}},
  {id:'b',type:'variable.set',name:'布尔',params:{output:'enabled',value_type:'bool',value_boolean:true}},
  {id:'s',type:'variable.set',name:'文本',params:{output:'text',value_type:'string',value_text:'3'}}]};
 await page.locator('#file').setInputFiles({name:'loop.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(initial))});
 await page.waitForFunction(()=>flow.name==='循环编辑测试');
 await page.locator('.action[data-type="control.loop"]').click();
 const id=await page.evaluate(()=>flow.steps.at(-1).id);
 await page.getByLabel('次数来源').selectOption('reference');
 const options=await page.getByLabel('次数变量').locator('option').evaluateAll(items=>items.map(x=>x.value));
 assert.deepEqual(options,['','count']);
 await page.getByLabel('次数变量').selectOption('count');
 await page.locator(`.add-step[data-target="${id}:body_steps"]`).click();
 await page.locator('.action-choice[data-type="control.if"]').click();
 const condition=await page.evaluate(id=>findStep(id).body_steps[0].id,id);
 assert((await page.getByLabel('左侧变量').locator('option').allTextContents()).includes('loop_index · number'));
 await page.getByLabel('左侧变量').selectOption('loop_index');
 await page.locator(`.add-step[data-target="${condition}:then_steps"]`).click();
 await page.locator('.action-choice[data-type="control.continue"]').click();
 await page.locator(`.add-step[data-target="${id}:body_steps"]`).click();
 await page.locator('.action-choice[data-type="control.loop"]').click();
 const inner=await page.evaluate(id=>findStep(id).body_steps.at(-1).id,id);
 assert.equal(await page.getByLabel('循环序号变量名').inputValue(),'loop_index_2');
 await page.locator('.action[data-type="control.break"]').dragTo(page.locator(`.branch-box[data-target="${inner}:body_steps"] > .drop-slot`).last());
 assert.equal(await page.evaluate(id=>findStep(id).body_steps[0].type,inner),'control.break');
 await page.locator('.action[data-type="variable.set"]').click();
 await page.getByLabel('变量类型').selectOption('number');
 await page.getByLabel('值的来源').selectOption('reference');
 const available=await page.getByLabel('来源变量').locator('option').allTextContents();
 assert(!available.some(text=>text.includes('loop_index')));
 await page.getByRole('button',{name:'删除步骤',exact:true}).click();
 await page.locator(`.node[data-id="${id}"]`).click();
 await page.screenshot({path:path.join(root,'.tmp/loop-editor.png')});
 await page.waitForFunction(()=>document.querySelector('#saved').textContent==='已保存到本地');
 await reloadProject(page);await page.waitForFunction(()=>loaded&&flow.name==='循环编辑测试');
 assert.equal(await page.evaluate(id=>findStep(id).params.count_variable,id),'count');
 assert.equal(await page.evaluate(id=>findStep(id).body_steps[0].type,inner),'control.break');
 await page.locator(`.node[data-id="${id}"]`).click({button:'right'});
 await page.getByRole('menuitem',{name:'删除节点',exact:true}).click();
 assert.equal(await page.locator('.branch-box').count(),0);
 console.log('PASS: number-only loop count selector, loop index scope, nested loop editing/drag, save/reload and subtree deletion');
};
