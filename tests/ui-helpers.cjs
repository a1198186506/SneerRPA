const menuAction=async(page,id)=>{
 if(!await page.locator('#'+id).isVisible())await page.locator('#project-menu-toggle').click();
 await page.locator('#'+id).click();
};
const createProject=async(page,name='测试项目')=>{
 await page.locator('#create-project').click();await page.getByLabel('项目名称',{exact:true}).fill(name);
 await page.locator('#submit-project-name').click();await page.waitForFunction(()=>view==='editor'&&!switching);
};
const newProject=async(page,name='测试项目')=>{
 await menuAction(page,'new');await page.locator('#confirm-leave-project').click();await page.waitForFunction(()=>view==='home'&&!switching);
 await createProject(page,name);
};
const reloadProject=async(page)=>{
 const id=await page.evaluate(()=>activeProject?.id);await page.reload();await page.waitForFunction(()=>ready&&loaded);
 if(id){await page.locator(`.project-card[data-project-id="${id}"]`).click();await page.waitForFunction(()=>view==='editor'&&!switching);}
};
module.exports={menuAction,createProject,newProject,reloadProject};
