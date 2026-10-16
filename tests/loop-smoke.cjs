const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
module.exports=async(page,root)=>{
 const original=await page.evaluate(()=>structuredClone(flow));
 const sample=JSON.parse(await fs.readFile(path.join(root,'resources/loop-flow.json'),'utf8'));
 const upload=async f=>{
  await page.locator('#file').setInputFiles({name:'loop.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(f))});
  await page.waitForFunction(name=>flow.name===name,f.name);
 };
 const run=async()=>{
  await page.locator('#clear').click();await page.locator('#run').click();
  await page.waitForFunction(()=>['执行成功','执行失败','启动失败'].includes(document.querySelector('#runstatus').textContent),null,{timeout:15000});
  assert.equal(await page.locator('#runstatus').innerText(),'执行成功',await page.locator('#logs').innerText());
 };
 sample.steps[1].body_steps.unshift({id:'change-count',name:'修改来源不会改变本次次数',type:'variable.set',params:{output:'repeat_count',value_type:'number',value_number:0}});
 await upload(sample);await run();
 let logs=await page.locator('#logs').innerText();
 assert(logs.includes('第 4 次循环'));assert(!logs.includes('第 5 次循环'));
 assert.equal(logs.split('本轮处理完成').length-1,2);
 assert(logs.includes('循环已结束'));
 assert.equal(await page.evaluate(()=>variables.repeat_count),0);
 assert.equal(await page.evaluate(()=>loopProgress.repeat),'4/5');
 assert.equal(await page.locator('.node[data-id="repeat"]').getAttribute('class').then(s=>s.includes('completed')),true);
 console.log('PASS: live Neutralino loop events, count snapshot, IF/Continue/Break, iteration progress and following steps');
 const zero=structuredClone(sample);zero.name='零次循环';zero.steps[0].params.value_number=0;
 await upload(zero);await run();
 assert.equal(await page.locator('.node.skipped').count(),7);
 assert.equal(await page.evaluate(()=>Object.hasOwn(variables,'loop_index')),false);
 // Runtime values must be validated even when statically typed number.
 for(const value of [-1,1.5,1001]){
  const bad=structuredClone(sample);bad.name='无效次数 '+value;bad.steps[0].params.value_number=value;
  await upload(bad);await page.locator('#clear').click();await page.locator('#run').click();
  await page.waitForFunction(()=>document.querySelector('#runstatus').textContent==='执行失败');
  assert(!(await page.locator('#logs').innerText()).includes('第 1 次循环'));
 }
 const stopping=structuredClone(sample);stopping.name='停止循环';stopping.steps[1].body_steps=[{id:'loop-wait',name:'循环内等待',type:'wait',params:{seconds:20}}];
 await upload(stopping);await page.locator('#run').click();
 await page.waitForFunction(()=>document.querySelector('.node[data-id="loop-wait"]').classList.contains('running'));
 await page.locator('#stop').click();await page.waitForFunction(()=>document.querySelector('#runstatus').textContent==='已停止');
 console.log('PASS: zero iterations, invalid number values before body execution and stop within loop');
 await upload(original);
};
