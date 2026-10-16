'use strict';
const $ = selector => document.querySelector(selector);
const clone = value => structuredClone(value);
let definitions = {}, flow, selected, ready = false, busy = false, toolBusy = false;
let runId = null, editingElement = null, revision = 0, saveTimer, loaded = false;
let editingImage = null;
let actionInsert=null;
let activeProject=null,view='home',switching=false;
let saveChain=Promise.resolve();
let exportBusy=false,exportId=null;
const advancedOpen = new Set();
const states = {}, variables = {}, pending = new Map();
const variableTypes={};
const loopProgress={};
function allEntries(){return FlowModel.walk(flow.steps);}
function allSteps(){return allEntries().map(entry=>entry.step);}
function findStep(id){return allSteps().find(step=>step.id===id);}
function destination(target='root'){
  if(target==='root')return {list:flow.steps,parentId:null};
  const [id,branch]=target.split(':');const parent=findStep(id);
  if(!parent||!FlowModel.branches(parent).includes(branch))return {list:flow.steps,parentId:null};
  return {list:parent[branch],parentId:id};
}
function moveNode(id,target,index){
  const entry=allEntries().find(item=>item.step.id===id),to=destination(target);
  if(!entry)return;
  const descendants=FlowModel.walk([entry.step]).map(item=>item.step.id);
  if(to.parentId&&descendants.includes(to.parentId))return toast('不能把容器移动到自己的内部');
  entry.list.splice(entry.index,1);
  if(entry.list===to.list&&entry.index<index)index--;
  to.list.splice(index,0,entry.step);dirty();
}
function clearDropHints(){
  document.querySelectorAll('.drop-before,.drop-after,.drop-active').forEach(node=>node.classList.remove('drop-before','drop-after','drop-active'));
}
function closeNodeMenu(){document.querySelector('#node-menu')?.remove();}
function deleteStep(id){
  if(busy||toolBusy||switching)return;
  const entry=allEntries().find(item=>item.step.id===id);
  if(!entry)return;
  const removed=FlowModel.walk([entry.step]).map(item=>item.step.id);
  entry.list.splice(entry.index,1);
  for(const key of removed)delete states[key];
  if(removed.includes(selected))selected=entry.list[entry.index]?.id||entry.list[entry.index-1]?.id||entry.parentId||flow.steps[0]?.id;
  dirty();
}
function openNodeMenu(event,step){
  event.preventDefault();event.stopPropagation();closeNodeMenu();
  if(busy||toolBusy)return;
  const rect=event.currentTarget.getBoundingClientRect();
  selected=step.id;render();
  const menu=el('div','node-menu');menu.id='node-menu';menu.setAttribute('role','menu');menu.setAttribute('aria-label','节点操作');
  const button=el('button','delete-node','删除节点');button.setAttribute('role','menuitem');
  button.onclick=()=>deleteStep(step.id);menu.append(button);
  if(FlowModel.branches(step).length)menu.append(el('p','hint','同时删除此容器内的所有步骤'));
  document.body.append(menu);
  const x=event.clientX||rect.left+20,y=event.clientY||rect.top+20;
  menu.style.left=Math.max(8,Math.min(x,window.innerWidth-menu.offsetWidth-8))+'px';
  menu.style.top=Math.max(8,Math.min(y,window.innerHeight-menu.offsetHeight-8))+'px';
  button.focus({preventScroll:true});
}
function insertDrop(event,target,index){
  event.preventDefault();event.stopPropagation();clearDropHints();
  if(busy||toolBusy)return;
  const id=event.dataTransfer.getData('step');
  if(id)moveNode(id,target,index);
  else{const type=event.dataTransfer.getData('action');if(definitions[type])add(type,target,index);}
}
function bindInsertion(element,target,index,split=false){
  const after=event=>split&&event.clientY>=element.getBoundingClientRect().top+element.getBoundingClientRect().height/2;
  element.ondragover=event=>{
    if(busy||toolBusy||!['action','step'].some(type=>Array.from(event.dataTransfer.types).includes(type)))return;
    event.preventDefault();event.stopPropagation();clearDropHints();
    element.classList.add(split?(after(event)?'drop-after':'drop-before'):'drop-active');
  };
  element.ondragleave=event=>{if(!element.contains(event.relatedTarget))element.classList.remove('drop-before','drop-after','drop-active');};
  element.ondrop=event=>insertDrop(event,target,index+(after(event)?1:0));
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').style.display = 'block';
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $('#toast').style.display = 'none', 4000);
}
function log(message, kind = 'info') {
  const row = el('div', 'log ' + kind);
  row.append(el('time', '', new Date().toLocaleTimeString('zh-CN', {hour12:false})), el('span', '', message));
  $('#logs').append(row);
  while ($('#logs').children.length > 1000) $('#logs').firstChild.remove();
  $('#logs').scrollTop = $('#logs').scrollHeight;
}
function report(error) { const message = error.message || String(error); log(message, 'error'); toast(message); }
function request(command, data = {}) {
  const request_id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(request_id); reject(Error('请求超时：' + command)); }, 85000);
    pending.set(request_id, {resolve, reject, timer, command});
    Neutralino.extensions.dispatch('com.sneer.python', 'command', {command, request_id, ...data})
      .catch(error => { clearTimeout(timer); pending.delete(request_id); reject(Error(error.message || error.code || String(error))); });
  });
}
function defaults(type) { return Object.fromEntries(definitions[type].fields.map(f => [f.key, clone(f.default)])); }
function normalize(data) {
  if (data?.schema_version !== 1 || !Array.isArray(data.steps) || !Array.isArray(data.elements || []) || !Array.isArray(data.images || [])) throw Error('流程格式不受支持');
  const elements = data.elements || [];
  const images = data.images || [];
  if(images.some(image=>!image||typeof image.id!=='string'||!image.id||typeof image.name!=='string'||image.format!=='png'||!/^data:image\/png;base64,[A-Za-z0-9+/]+=*$/.test(image.data_url||'')||!Number.isInteger(image.width)||!Number.isInteger(image.height))||new Set([...elements,...images].map(e=>e.id)).size!==elements.length+images.length)throw Error('图片素材格式无效或 ID 重复');
  if (elements.some(e => !e || typeof e.id !== 'string' || typeof e.name !== 'string' || !e.selector) || new Set(elements.map(e => e.id)).size !== elements.length) throw Error('元素库格式无效');
  const ids = new Set();
  function normalizeSteps(steps,depth=0){
  if(depth>16||!Array.isArray(steps))throw Error('容器格式无效或嵌套过深');
  for (const step of steps) {
    if (!step || !definitions[step.type] || typeof step.name !== 'string' || typeof step.id !== 'string' || !step.id || ids.has(step.id) || !step.params || Array.isArray(step.params)) throw Error('步骤格式无效或 ID 重复');
    ids.add(step.id);
    if(step.type.startsWith('window.')&&!('target_mode' in step.params))step.params.target_mode=step.type==='window.get'?'criteria':'variable';
    if(step.type.startsWith('element.')&&!('window' in step.params))step.params.window='main_window';
    step.params = {...defaults(step.type), ...step.params};
    for(const key of ['then_steps','else_steps','body_steps']){
      if(FlowModel.branches(step).includes(key)){step[key]??=[];normalizeSteps(step[key],depth+1);}
      else if(key in step)throw Error('IF 或循环的子步骤字段无效');
    }
  }
  }
  normalizeSteps(data.steps);if(ids.size>1000)throw Error('流程不能超过 1000 个步骤');
  return {...data, name:data.name || '未命名流程', elements, images};
}
function installFlow(data) {
  flow = normalize(clone(data));
  selected = flow.steps[0]?.id;
  actionInsert=null;
  Object.keys(states).forEach(k => delete states[k]);
  Object.keys(variables).forEach(k => delete variables[k]);
  Object.keys(variableTypes).forEach(k => delete variableTypes[k]);
  Object.keys(loopProgress).forEach(k => delete loopProgress[k]);
  $('#runstatus').textContent = '等待运行';
  render();
}
function dirty() {
  revision++;
  $('#saved').textContent = '待保存';
  render();
  clearTimeout(saveTimer);
  if (ready && loaded && view==='editor') saveTimer = setTimeout(()=>saveCurrent().catch(()=>{}), 650);
}
async function saveCurrent() {
  if(!activeProject||view!=='editor')return;
  const current = revision,projectId=activeProject.id,snapshot=clone(flow);
  try {
    saveChain=saveChain.catch(()=>{}).then(()=>request('save_project',{project_id:projectId,flow:snapshot}));
    await saveChain;
    if (activeProject?.id===projectId&&revision === current) $('#saved').textContent = '已保存到本地';
  } catch (error) {
    if (activeProject?.id===projectId&&revision === current) $('#saved').textContent = '保存失败';
    throw error;
    // Incomplete steps are allowed while editing; validation blocks execution.
  }
}
function closeProjectMenu(){$('#project-menu').hidden=true;$('#project-menu-toggle').setAttribute('aria-expanded','false');}
async function refreshProjects(){
  $('#project-list-message').textContent='正在加载项目…';
  try{
    const response=await request('list_projects');$('#project-list').replaceChildren();
    for(const project of response.projects){
      const card=el('button','project-card');card.dataset.projectId=project.id;
      const icon=el('span','project-card-icon','▤'),text=el('span','project-card-text');
      text.append(el('strong','',project.name),el('small','',`${project.step_count} 个步骤 · 最近保存 ${new Date(project.updated_at).toLocaleString('zh-CN',{hour12:false})}`));
      card.append(icon,text,el('span','project-card-open','打开 →'));card.onclick=()=>openProject(project.id);$('#project-list').append(card);
    }
    $('#project-list-message').textContent=response.warnings?.join(' ')||(response.projects.length?'':'还没有项目，点击“新建项目”开始。');
  }catch(error){$('#project-list-message').textContent='项目加载失败：'+error.message;}
}
function setView(next){
  view=next;$('#project-home').hidden=next!=='home';$('#editor').hidden=next!=='editor';
  document.body.classList.remove('workspace-expanded');$('#expand-workspace').setAttribute('aria-pressed','false');$('#expand-workspace').textContent='⤢ 放大编排区';$('#expand-workspace').title='放大编排区';
  if(next==='editor')window.dispatchEvent(new Event('resize'));
  render();
}
function enterProject(project){
  clearTimeout(saveTimer);revision++;activeProject={id:project.id,name:project.name};
  installFlow(project.flow);setView('editor');$('#saved').textContent='已保存到本地';
}
async function openProject(id){
  if(switching||busy||toolBusy||!ready)return;
  switching=true;render();
  try{await saveChain.catch(()=>{});const response=await request('load_project',{project_id:id});enterProject(response.project);}
  catch(error){report(error);}finally{switching=false;render();}
}
async function returnHome(){
  if(switching||busy||toolBusy)return;
  switching=true;clearTimeout(saveTimer);closeProjectMenu();render();
  try{await saveChain.catch(()=>{});activeProject=null;revision++;setView('home');$('#saved').textContent='';$('#leave-project-dialog').close();await refreshProjects();}
  finally{switching=false;render();}
}
function askNewProject(){
  closeProjectMenu();if(busy||toolBusy||switching)return;
  if(view==='home')return showProjectName();
  $('#leave-project-dialog').showModal();
}
function showProjectName(){
  if(!ready||switching)return;
  $('#project-name-input').value='';$('#project-name-error').textContent='';$('#project-name-dialog').showModal();$('#project-name-input').focus();
}
async function createProject(name,data){
  if(switching)throw Error('正在切换项目，请稍候');
  switching=true;clearTimeout(saveTimer);render();
  try{
    if(activeProject&&view==='editor')await saveCurrent();
    const response=await request('create_project',{name,...(data?{flow:data}:{})});enterProject(response.project);
  }finally{switching=false;render();}
}
function add(type,target='root',index=null) {
  if (busy || toolBusy || switching || definitions[type]?.hidden) return;
  const step = {id:crypto.randomUUID(), type, name:definitions[type].name, params:defaults(type)};
  if(type==='control.if'){step.then_steps=[];step.else_steps=[];}
  if(type==='control.loop'){
    step.body_steps=[];
    const names=new Set(allSteps().flatMap(s=>[s.params.output,s.params.index_variable]));
    let index=1;while(names.has(step.params.index_variable))step.params.index_variable='loop_index_'+(++index);
  }
  const list=destination(target).list;list.splice(index===null?list.length:index,0,step); selected = step.id; dirty();
}
function summary(step) {
  const p = step.params;
  if(step.type==='variable.set')return `${p.output} · ${p.value_type}`;
  if(step.type==='control.loop')return `${p.count_source==='reference'?'变量 '+(p.count_variable||'未选择'):p.count+' 次'} · 序号 ${p.index_variable}`+(loopProgress[step.id]?' · '+loopProgress[step.id]:'');
  if(step.type==='control.if')return `${p.left||'请选择变量'} ${p.operator} ${p.right_source==='reference'?p.right_reference:p['right_'+({bool:'boolean',string:'text',number:'number'}[p.right_type])]}`;
  if(step.type==='image.find')return flow.images.find(image=>image.id===p.image)?.name||'请选择目标图片';
  if(step.type==='mouse.click'&&p.target_mode==='position')return '位置变量 · '+p.position;
  if(step.type==='mouse.click'&&p.target_mode==='coordinates')return `屏幕坐标 · (${p.x}, ${p.y})`;
  if (step.type.startsWith('window.')) {
    if(p.target_mode==='element')return '所属窗口 · '+(flow.elements.find(e=>e.id===p.element)?.selector.window.title||'请选择元素');
    if(p.target_mode==='variable')return '窗口变量 · '+p.window;
    return p.title||p.process_name||p.class_name||p.process_id||'请填写窗口条件';
  }
  if (p.element) return flow.elements.find(e => e.id === p.element)?.name || '目标元素已缺失';
  if (p.path) return p.path;
  if (p.title) return p.title;
  if (p.window) return p.window + (p.state ? ' · ' + p.state : '');
  return String(p.message ?? p.seconds ?? p.text ?? definitions[step.type].description);
}
function renderActions() {
  $('#actions').replaceChildren();
  const search = $('#search').value.trim().toLowerCase();
  let group;
  for (const d of Object.values(definitions)) {
    if(d.hidden)continue;
    if (search && !`${d.name} ${d.description} ${d.type}`.toLowerCase().includes(search)) continue;
    if (d.group !== group) { group = d.group; $('#actions').append(el('h4', 'group-title', group)); }
    const card = el('div', 'action'); card.draggable = !busy && !toolBusy;
    card.dataset.type = d.type; card.tabIndex = 0;
    card.append(el('div', 'icon', d.icon));
    const text = el('div'); text.append(el('strong', '', d.name), el('small', '', d.description)); card.append(text);
    card.onclick = () => add(d.type);
    card.onkeydown = e => { if(e.key === 'Enter') add(d.type); };
    card.ondragstart = e => e.dataTransfer.setData('action', d.type);
    $('#actions').append(card);
  }
}
function renderActionPicker(){
  const list=$('#action-dialog-list'),query=$('#action-dialog-search').value.trim().toLowerCase();list.replaceChildren();
  let group;
  for(const d of Object.values(definitions)){
    if(d.hidden)continue;
    if(query&&!`${d.name} ${d.description} ${d.type}`.toLowerCase().includes(query))continue;
    if(group!==d.group){group=d.group;list.append(el('h4','group-title',group));}
    const button=el('button','action-choice');button.dataset.type=d.type;
    button.append(el('span','icon',d.icon));const text=el('span');text.append(el('strong','',d.name),el('small','',d.description));button.append(text);
    button.onclick=()=>{const insert=actionInsert;$('#action-dialog').close();if(insert)add(d.type,insert.target,insert.index);};list.append(button);
  }
  if(!list.children.length)list.append(el('p','hint','没有匹配的动作'));
}
function openActionPicker(target,index){
  if(busy||toolBusy)return;
  actionInsert={target,index};
  const parent=target==='root'?null:findStep(target.split(':')[0]);
  $('#action-dialog-title').textContent=parent?'添加步骤 · '+parent.name:'添加步骤 · 主流程';
  $('#action-dialog-search').value='';renderActionPicker();$('#action-dialog').showModal();$('#action-dialog-search').focus();
}
function render() {
  if (!flow) return;
  closeNodeMenu();
  $('#flowname').textContent = view==='home'?'项目首页':flow.name;
  $('#count').textContent = allSteps().length + ' 个步骤';
  $('#element-count').textContent = flow.elements.length+flow.images.length;
  $('#flow').replaceChildren(el('div', 'endpoint', '● 开始'));
  function renderList(steps,container,target){
  steps.forEach((step, index) => {
    const d = definitions[step.type];
    const slot=el('div','connector drop-slot','↓');bindInsertion(slot,target,index);container.append(slot);
    const node = el('div', `node ${selected === step.id ? 'selected' : ''} ${states[step.id] || ''}`);
    node.dataset.id = step.id; node.draggable = !busy && !toolBusy;
    node.ondragstart = event => event.dataTransfer.setData('step', step.id);
    bindInsertion(node,target,index,true);
    const content = el('div', 'content'); content.append(el('strong', '', step.name), el('p', '', summary(step)));
    node.append(el('div', 'icon', d.icon), content, el('span', 'number', states[step.id] === 'completed' ? '✓' : String(index+1).padStart(2,'0')));
    node.onclick = () => { selected = step.id; render(); };
    node.oncontextmenu=event=>openNodeMenu(event,step);
    container.append(node);
    if(FlowModel.branches(step).length){
      const branches=step.type==='control.loop'?[['body_steps','循环体 · 重复执行']]:[['then_steps','如果 · 条件为真'],['else_steps','否则 · 条件为假']];
      for(const [branch,title]of branches){
        const box=el('div','branch-box'+(step.type==='control.loop'?' loop-body':''));box.dataset.target=step.id+':'+branch;
        box.append(el('div','branch-heading',title));
        bindInsertion(box,box.dataset.target,step[branch].length);
        renderList(step[branch],box,box.dataset.target);
        container.append(box);
      }
    }
  });
  const tail=el('div','connector drop-slot','↓');bindInsertion(tail,target,steps.length);container.append(tail);
  const addButton=el('button','add-step','＋ 添加步骤');addButton.dataset.target=target;addButton.disabled=busy||toolBusy;
  addButton.onclick=()=>openActionPicker(target,steps.length);container.append(addButton);
  }
  renderList(flow.steps,$('#flow'),'root');
  $('#flow').append(el('div', 'endpoint', '◎ 结束'));
  renderProperties(); renderElements(); renderVariables();
  $('#run').disabled = view!=='editor'||exportBusy||switching||!ready || busy || toolBusy || !flow.steps.length;
  $('#run').hidden=view!=='editor';$('#stop').hidden=view!=='editor';
  $('#stop').disabled = !busy || !runId;
  for (const id of ['new','sample','open','manual','pick','pick-image','pick-backend','recapture-image']) $('#' + id).disabled = exportBusy||switching||busy || toolBusy || !ready;
  $('#export-exe').disabled=view!=='editor'||!flow.steps.length||exportBusy||switching||busy||toolBusy||!ready;
  $('#save').disabled=view!=='editor'||switching||busy||toolBusy||!ready;
  $('#create-project').disabled=!ready||switching;
  $('#refresh-projects').disabled=!ready||switching;
  $('#confirm-leave-project').disabled=switching;
  $('#cancel-pick').hidden = !toolBusy;
}
function renderProperties() {
  const panel = $('#properties'); panel.replaceChildren();
  const step = findStep(selected);
  if (!step) { panel.append(el('p','hint','选择一个步骤查看和编辑参数')); return; }
  const d = definitions[step.type]; panel.append(el('span','badge',step.type), el('p','hint',d.description));
  const fields = step.type==='keyboard.input'?d.fields:[{key:'__name',label:'步骤名称'}, ...d.fields];
  const advanced=el('details','advanced-settings');
  advanced.open=advancedOpen.has(step.id);advanced.append(el('summary','','高级设置'));
  advanced.ontoggle=()=>{if(advanced.open)advancedOpen.add(step.id);else advancedOpen.delete(step.id);};
  for (const field of fields) {
    if(!Object.entries(field.show_if||{}).every(([key,values])=>values.includes(step.params[key])))continue;
    const container=field.advanced?advanced:panel;
    const label = el('label','field',field.label);
    let input;
    if (['select','element','reference','image'].includes(field.kind)) {
      input = el('select');
      let options = field.kind === 'element' ? [['','请选择元素'], ...flow.elements.map(e => [e.id,e.name])]:field.kind==='image'?[['','请选择图片'],...flow.images.map(image=>[image.id,image.name])]:field.options;
      if(field.kind==='reference'){
        let types=field.types;
        if(step.type==='variable.set'&&field.key==='source_variable')types=[step.params.value_type];
        const available=FlowModel.before(flow.steps,step.id).types;
        options=[['','请选择前面步骤的变量'],...Object.entries(available).filter(([name,type])=>!types||types.includes(type)).map(([name,type])=>[name,`${name} · ${type}`])];
        if(step.params[field.key]&&!options.some(([key])=>key===step.params[field.key]))options.push([step.params[field.key],step.params[field.key]+'（未定义或类型不适用）']);
      }
      if(step.type==='variable.set'&&field.key==='source')options=options.filter(([key])=>step.params.value_type==='window'?key!=='literal':key!=='window');
      if(step.type==='control.if'&&field.key==='operator'&&FlowModel.before(flow.steps,step.id).types[step.params.left]!=='number')options=options.filter(([key])=>['==','!='].includes(key));
      for (const [value, text] of options) {const option = el('option','',text); option.value=value; input.append(option);}
    } else input = el(field.kind === 'multiline' || field.kind === 'json' ? 'textarea' : 'input');
    const value = field.key === '__name' ? step.name : step.params[field.key];
    if (field.kind === 'boolean') { input.type='checkbox'; input.checked=value; }
    else input.value = field.kind === 'json' ? JSON.stringify(value) : value ?? '';
    if (field.kind === 'number') { input.type='number'; input.min=field.min; input.max=field.max; input.step=field.integer?'1':'any'; }
    input.disabled = busy || toolBusy || switching;
    input.onchange = () => {
      try {
        if (field.key === '__name') step.name = input.value || d.name;
        else step.params[field.key] = field.kind === 'boolean' ? input.checked : field.kind === 'number' ? Number(input.value) : field.kind === 'json' ? JSON.parse(input.value) : input.value;
        if(step.type==='variable.set'&&field.key==='value_type'&&step.params.source!=='reference')step.params.source=input.value==='window'?'window':'literal';
        if(step.type==='control.if'&&field.key==='left'){
          const type=FlowModel.before(flow.steps,step.id).types[input.value];
          if(['bool','string','number'].includes(type)){step.params.right_type=type;if(type!=='number')step.params.operator='==';}
        }
        dirty();
      } catch {input.setCustomValidity('请输入有效的 JSON 数组'); input.reportValidity(); input.setCustomValidity('');}
    };
    label.append(input); container.append(label);
    if(field.help)container.append(el('p','hint',field.help));
    if(field.kind==='image'){
      const image=flow.images.find(image=>image.id===step.params[field.key]);
      if(image){const thumb=el('img','image-thumbnail');thumb.src=image.data_url;thumb.alt=image.name;container.append(thumb);}
    }
    if(step.type==='image.find'&&field.key==='region_height'){
      const button=el('button','wide','框选搜索区域…');button.disabled=busy||toolBusy;button.onclick=()=>pickSearchRegion(step);container.append(button);
    }
    if(step.type==='mouse.click'&&field.key==='y'){
      const capture=el('button','wide','实时捕获坐标…');capture.disabled=busy||toolBusy;
      capture.onclick=()=>pickCoordinates(step);container.append(capture);
      if(toolBusy){const cancel=el('button','wide','取消坐标捕获');cancel.onclick=()=>$('#cancel-pick').click();container.append(cancel);}
    }
    if(field.kind==='file'){
      const browse=el('button','wide','浏览程序或文件…');browse.disabled=busy||toolBusy;
      browse.onclick=async()=>{
        browse.disabled=true;
        try{const paths=await Neutralino.os.showOpenDialog('选择程序或文件',{multiSelections:false,filters:[{name:'程序',extensions:['exe','com']},{name:'所有文件',extensions:['*']}]});
          if(paths.length){step.params[field.key]=paths[0];dirty();}
        }catch(error){report(error);}finally{browse.disabled=busy||toolBusy;}
      };
      container.append(browse);
    }
    if (field.kind === 'element') {
      const buttons = el('div','inline-tools');
      for (const [text, action] of [['拾取新元素',pickElement], ['编辑 / 测试',()=>{const e=flow.elements.find(e=>e.id===step.params[field.key]); if(e) editElement(e); else toast('请先选择或拾取元素');}]]) {
        const button=el('button','',text); button.disabled=busy||toolBusy; button.onclick=action; buttons.append(button);
      }
      container.append(buttons);
      if(step.type.startsWith('window.')){
        const entry=flow.elements.find(e=>e.id===step.params[field.key]);
        const target=entry?.selector.window;
        container.append(el('p','target-preview',target
          ? (step.type==='window.close'?'将关闭整个窗口：':'操作所选元素所属的窗口：')+(target.title||target.process_name||target.class_name)
          : '选择任意已捕获的控件，用它所属的窗口作为操作目标。'));
      }else if(!step.params.window)container.append(el('p','hint','使用该元素自身保存的窗口信息，无需先获取窗口变量。'));
    }
  }
  if ((step.type.startsWith('window.')||step.type==='variable.set'&&step.params.source==='window')&&step.params.target_mode==='criteria') { const button=el('button','wide','从当前窗口列表选择'); button.disabled=busy||toolBusy; button.onclick=chooseWindow; panel.append(button); }
  if(step.type==='image.find'){
    const test=el('button','wide','测试找图');test.disabled=busy||toolBusy;test.onclick=()=>testImage(step);panel.append(test);
  }
  if(advanced.children.length>1)panel.append(advanced);
  const actions=el('div','edit-actions');
  for (const [text,action] of [['上移',()=>move(-1)],['下移',()=>move(1)],['删除步骤',()=>deleteStep(step.id)]]) {
    const button=el('button','',text); button.disabled=busy||toolBusy; button.onclick=action; actions.append(button);
  }
  panel.append(actions);
  if(step.type==='control.loop')panel.append(el('p','hint','次数在进入循环时读取一次，必须为非负整数。0 次跳过循环体；超过上限报错。循环体内可使用序号、跳出循环和继续循环。'));
  else if(['control.break','control.continue'].includes(step.type))panel.append(el('p','hint','仅影响当前所在的最内层循环；必须放在循环体或其内部的 IF 分支中。'));
  else if(step.type==='variable.set')panel.append(el('p','hint','自定义文本按原样保存；复制已有值请选“已有变量”。同名变量保持相同类型。'));
  else if(step.type==='control.if')panel.append(el('p','hint','两侧类型必须一致。大小比较支持数字；文本与布尔值支持相等、不等。'));
  else if(step.type==='image.find')panel.append(el('p','hint','请先激活目标窗口，保持目标可见。未找到时 found 为 false，center 为空；建议先用 IF 判断 found，再点击中心位置。'));
  else if(step.type!=='keyboard.input')panel.append(el('p','hint','文本支持 ${变量名}，例如 ${result_text}。窗口变量直接填写变量名。'));
}
function move(delta) {
  const entry=allEntries().find(item=>item.step.id===selected),to=entry.index+delta;
  if(to<0||to>=entry.list.length)return;
  [entry.list[entry.index],entry.list[to]]=[entry.list[to],entry.list[entry.index]]; dirty();
}
function renderElements() {
  $('#elements').replaceChildren();
  $('#control-count').textContent=flow.elements.length;
  $('#image-count').textContent=flow.images.length;
  for (const entry of flow.elements) {
    const row=el('div','library-item');
    row.append(el('strong','',entry.name),el('p','hint',entry.selector.backend+' · '+entry.selector.window.title));
    const actions=el('div','inline-tools');
    for(const [text,action] of [['编辑',()=>editElement(entry)],['删除',()=>{
      if(allSteps().some(s=>s.params.element===entry.id&&(!s.type.startsWith('window.')&&s.type!=='mouse.click'&&s.type!=='variable.set'||s.params.target_mode==='element')))return toast('有步骤正在引用此元素，请先更换目标元素');
      for(const step of allSteps())if(step.params.element===entry.id)step.params.element='';
      flow.elements=flow.elements.filter(e=>e.id!==entry.id);dirty();
    }]]){const b=el('button','',text);b.disabled=busy||toolBusy;b.onclick=action;actions.append(b);}
    row.append(actions);$('#elements').append(row);
  }
  if(!flow.elements.length)$('#elements').append(el('p','hint','元素库为空。拾取软件控件，或手动添加选择器。'));
  $('#images').replaceChildren();
  for(const image of flow.images){
    const card=el('div','library-item image-asset');card.dataset.id=image.id;
    const thumb=el('img','image-thumbnail');thumb.src=image.data_url;thumb.alt=image.name;thumb.onclick=()=>editImage(image);
    card.append(thumb,el('strong','',image.name),el('p','hint',`${image.width} × ${image.height} px · PNG`));
    const actions=el('div','inline-tools');
    for(const [text,action] of [['预览 / 编辑',()=>editImage(image)],['删除',()=>{
      if(allSteps().some(step=>step.params.image===image.id))return toast('有步骤正在引用此图片，请先更换目标图片');
      flow.images=flow.images.filter(item=>item.id!==image.id);dirty();
    }]]){const button=el('button','',text);button.disabled=busy||toolBusy;button.onclick=action;actions.append(button);}
    card.append(actions);$('#images').append(card);
  }
  if(!flow.images.length)$('#images').append(el('p','hint','点击“拾取图片”框选目标，保存为后续找图使用的图片素材。'));
}
function renderVariables() {
  $('#variables').replaceChildren();
  for(const [name,value] of Object.entries(variables)){const row=el('div','variable');row.append(el('code','',name+' · '+(variableTypes[name]||'')),el('pre','',typeof value==='string'?value:JSON.stringify(value,null,2)));$('#variables').append(row);}
  if(!Object.keys(variables).length)$('#variables').append(el('p','hint','运行后，这里展示窗口、进程及读取结果变量。'));
}
function switchLibrary(elements) {
  $('#action-panel').hidden=elements;$('#element-panel').hidden=!elements;
  $('#tab-actions').classList.toggle('active',!elements);$('#tab-elements').classList.toggle('active',elements);
}
function switchAssetTab(images){
  $('#control-assets').hidden=images;$('#image-assets').hidden=!images;
  for(const [id,active]of [['tab-controls',!images],['tab-images',images]]){
    const button=$('#'+id);button.classList.toggle('active',active);button.setAttribute('aria-selected',active);button.tabIndex=active?0:-1;
  }
}
function setExportUI(){
  for(const id of ['export-exe-directory','export-exe-filename','browse-export-directory','start-export-exe','close-export-exe'])$('#'+id).disabled=exportBusy;
  $('#cancel-export-exe').hidden=!exportBusy;$('#export-exe-progress').hidden=!exportBusy;
  render();
}
function showExeExport(){
  closeProjectMenu();if(view!=='editor'||busy||toolBusy||exportBusy)return;
  let name=flow.name.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/[. ]+$/,'').slice(0,80)||'工作流';
  if(/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name))name='工作流';
  $('#export-exe-filename').value=name+'.exe';$('#export-exe-status').textContent='完成后将显示保存位置。同名文件不会被覆盖。';
  $('#export-exe-log').textContent='';$('#export-exe-log').hidden=true;$('#export-exe-details').hidden=true;$('#export-exe-details').open=false;exportId=null;setExportUI();$('#export-exe-dialog').showModal();
}
function editElement(entry) {
  editingElement=clone(entry);$('#element-name').value=entry.name;
  $('#element-selector').value=JSON.stringify(entry.selector,null,2);$('#selector-result').textContent='';
  $('#element-dialog').showModal();
}
async function pickElement() {
  if(busy||toolBusy)return;
  toolBusy=true;switchLibrary(true);switchAssetTab(false);render();$('#pick-hint').textContent='拾取中：指向控件后按 F8，Esc 取消（60 秒）。';
  try {
    const response=await request('pick_element',{backend:$('#pick-backend').value});
    const entry=response.result;
    flow.elements.push(entry);
    const step=findStep(selected);
    if(step&&definitions[step.type].fields.some(f=>f.kind==='element')){
      step.params.element=entry.id;
      if(step.type.startsWith('window.')||step.type==='mouse.click')step.params.target_mode='element';
    }
    dirty();log('已捕获元素：'+entry.name,'success');editElement(entry);
  } catch(error){if(!/取消/.test(error.message))report(error);}
  finally{toolBusy=false;$('#pick-hint').textContent='鼠标移到控件后按 F8 捕获，Esc 取消。';render();}
}
function editImage(image){
  editingImage=image.id;$('#image-name').value=image.name;$('#image-preview').src=image.data_url;
  const rect=image.capture_rect;
  $('#image-info').textContent=`${image.width} × ${image.height} px · PNG`+(rect?` · 捕获位置 (${rect.x}, ${rect.y})`:'');
  if(!$('#image-dialog').open)$('#image-dialog').showModal();
}
async function pickImage(replaceId=null){
  if(busy||toolBusy)return;
  let result, hidden=false;
  toolBusy=true;switchLibrary(true);switchAssetTab(true);render();
  try{
    if(window.NL_MODE==='window'){await Neutralino.window.hide();hidden=true;await new Promise(resolve=>setTimeout(resolve,250));}
    const response=await request('pick_image');
    const existing=flow.images.find(image=>image.id===replaceId);
    result={...response.result,name:existing?.name||`图片 ${flow.images.length+1}`};
    if(existing){result.id=existing.id;flow.images.splice(flow.images.indexOf(existing),1,result);}
    else flow.images.push(result);
    dirty();log(`已捕获图片：${result.width} × ${result.height} px`,'success');
  }catch(error){if(!/取消/.test(error.message))report(error);}
  finally{
    if(hidden)try{await Neutralino.window.show();}catch(error){report(error);}
    toolBusy=false;render();
  }
  if(result)editImage(result);
}
async function chooseWindow() {
  toolBusy=true;render();
  try {
    const step=findStep(selected);
    const response=await request('list_windows',{backend:step?.params.backend||'uia'});
    $('#window-list').replaceChildren();
    for(const item of response.result){const button=el('button','window-choice');button.append(el('strong','',item.title),el('small','',item.process_name+' · '+item.class_name));button.onclick=()=>{Object.assign(step.params,item,{match:'exact',process_id:'',target_mode:'criteria'});$('#window-dialog').close();dirty();};$('#window-list').append(button);}
    $('#window-dialog').showModal();
  }catch(error){report(error);}finally{toolBusy=false;render();}
}
async function pickCoordinates(step) {
  if(busy||toolBusy)return;
  toolBusy=true;render();toast('移动鼠标到目标位置，F8 捕获，Esc 取消');
  try{
    const response=await request('pick_coordinates');
    Object.assign(step.params,response.result,{target_mode:'coordinates'});
    dirty();log(`已捕获屏幕坐标：(${response.result.x}, ${response.result.y})`,'success');
  }catch(error){if(!/取消/.test(error.message))report(error);}
  finally{toolBusy=false;render();}
}
async function pickSearchRegion(step){
  if(busy||toolBusy)return;toolBusy=true;render();let hidden=false;
  try{
    if(window.NL_MODE==='window'){await Neutralino.window.hide();hidden=true;await new Promise(resolve=>setTimeout(resolve,250));}
    const response=await request('pick_image'),rect=response.result.capture_rect;
    Object.assign(step.params,{region_x:rect.x,region_y:rect.y,region_width:rect.width,region_height:rect.height});dirty();
  }catch(error){if(!/取消/.test(error.message))report(error);}
  finally{try{if(hidden)await Neutralino.window.show();}catch(error){report(error);}toolBusy=false;render();}
}
async function testImage(step){
  if(busy||toolBusy)return;toolBusy=true;render();let hidden=false;
  try{
    if(window.NL_MODE==='window'){await Neutralino.window.hide();hidden=true;await new Promise(resolve=>setTimeout(resolve,250));}
    const response=await request('test_image',{flow:clone(flow),params:clone(step.params)});
    const result=response.result;log(result.found?`找图成功：(${result.center.x}, ${result.center.y})，分数 ${result.score.toFixed(3)}`:`未找到目标图片，最佳分数 ${result.score.toFixed(3)}`,result.found?'success':'info');
    toast(result.found?'找图成功，已在目标位置高亮':'未找到目标图片');
  }catch(error){report(error);}
  finally{try{if(hidden)await Neutralino.window.show();}catch(error){report(error);}toolBusy=false;render();}
}
function wireUI() {
  EditorLayout.init();
  $('#export-exe').onclick=showExeExport;
  $('#close-export-exe').onclick=()=>{if(!exportBusy)$('#export-exe-dialog').close();};
  $('#export-exe-dialog').addEventListener('cancel',event=>{if(exportBusy)event.preventDefault();});
  $('#browse-export-directory').onclick=async()=>{
    try{const directory=await Neutralino.os.showFolderDialog('选择 EXE 保存文件夹');if(directory)$('#export-exe-directory').value=directory;}
    catch(error){$('#export-exe-status').textContent=error.message||String(error);}
  };
  $('#export-exe-form').onsubmit=async event=>{
    event.preventDefault();if(exportBusy)return;
    exportBusy=true;exportId=null;$('#export-exe-log').textContent='';$('#export-exe-log').hidden=false;$('#export-exe-details').hidden=false;$('#export-exe-details').open=false;
    $('#export-exe-status').textContent='正在准备导出，首次打包可能需要几分钟…';setExportUI();
    try{const response=await request('export_exe',{flow:clone(flow),directory:$('#export-exe-directory').value,filename:$('#export-exe-filename').value});exportId=response.export_id;}
    catch(error){exportBusy=false;$('#export-exe-status').textContent='导出失败：'+error.message;setExportUI();}
  };
  $('#cancel-export-exe').onclick=async()=>{
    $('#cancel-export-exe').disabled=true;
    try{await request('cancel_export');if(exportBusy)$('#export-exe-status').textContent='正在取消导出…';}
    catch(error){report(error);}finally{$('#cancel-export-exe').disabled=false;}
  };
  $('#project-menu-toggle').onclick=()=>{const open=$('#project-menu').hidden;$('#project-menu').hidden=!open;$('#project-menu-toggle').setAttribute('aria-expanded',open);if(open)$('#project-menu button:not(:disabled)')?.focus();};
  document.addEventListener('pointerdown',event=>{if(!event.target.closest('.project-dropdown'))closeProjectMenu();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeProjectMenu();});
  $('#create-project').onclick=showProjectName;
  $('#refresh-projects').onclick=refreshProjects;
  $('#cancel-leave-project').onclick=()=>$('#leave-project-dialog').close();
  $('#confirm-leave-project').onclick=()=>returnHome().catch(report);
  $('#cancel-project-name').onclick=()=>$('#project-name-dialog').close();
  $('#project-name-form').onsubmit=async event=>{
    event.preventDefault();const name=$('#project-name-input').value.trim();
    if(!name){$('#project-name-error').textContent='请输入项目名称';return;}
    $('#submit-project-name').disabled=true;
    try{await createProject(name);$('#project-name-dialog').close();}catch(error){$('#project-name-error').textContent=error.message;}
    finally{$('#submit-project-name').disabled=false;}
  };
  $('#action-dialog-search').oninput=renderActionPicker;
  $('#close-action-dialog').onclick=()=>$('#action-dialog').close();
  $('#action-dialog').addEventListener('close',()=>{actionInsert=null;});
  document.addEventListener('pointerdown',event=>{if(!event.target.closest('#node-menu'))closeNodeMenu();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeNodeMenu();});
  document.addEventListener('scroll',closeNodeMenu,true);
  window.addEventListener('resize',closeNodeMenu);
  document.addEventListener('dragend',clearDropHints,true);
  $('#search').oninput=renderActions;
  $('#tab-actions').onclick=()=>switchLibrary(false);$('#tab-elements').onclick=()=>switchLibrary(true);
  $('#tab-controls').onclick=()=>switchAssetTab(false);$('#tab-images').onclick=()=>switchAssetTab(true);
  for(const id of ['tab-controls','tab-images'])$('#'+id).onkeydown=event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const images=event.key==='End'||event.key!=='Home'&&id==='tab-controls';switchAssetTab(images);$(images?'#tab-images':'#tab-controls').focus();
  };
  $('#tab-logs').onclick=()=>{$('#logs').hidden=false;$('#variables').hidden=true;$('#tab-logs').classList.add('active');$('#tab-variables').classList.remove('active');};
  $('#tab-variables').onclick=()=>{$('#logs').hidden=true;$('#variables').hidden=false;$('#tab-logs').classList.remove('active');$('#tab-variables').classList.add('active');};
  $('#pick').onclick=pickElement;
  $('#pick-image').onclick=()=>pickImage();
  $('#close-image').onclick=()=>$('#image-dialog').close();
  $('#recapture-image').onclick=()=>pickImage(editingImage);
  $('#commit-image').onclick=()=>{
    const name=$('#image-name').value.trim();if(!name)return toast('请输入图片名称');
    const image=flow.images.find(item=>item.id===editingImage);if(!image)return;
    image.name=name;$('#image-dialog').close();dirty();toast('图片素材已保存');
  };
  $('#cancel-pick').onclick=async()=>{try{await request('cancel_tool');for(const [id,p] of pending){if(['pick_element','pick_coordinates','pick_image','test_element','test_image','list_windows'].includes(p.command)){clearTimeout(p.timer);pending.delete(id);p.reject(Error('已取消定位工具'));}}toolBusy=false;render();}catch(e){report(e);}};
  $('#manual').onclick=()=>editElement({id:crypto.randomUUID(),name:'新元素',selector:{backend:'uia',window:{title:'',match:'exact',backend:'uia'},criteria:{control_type:'Button',name:'确认'}}});
  $('#commit-element').onclick=async()=>{
    try {
      const entry={...editingElement,name:$('#element-name').value.trim(),selector:JSON.parse($('#element-selector').value)};
      if(!entry.name)throw Error('请输入元素名称');
      const proposed=clone(flow), index=proposed.elements.findIndex(e=>e.id===entry.id);
      if(index>=0)proposed.elements[index]=entry;else proposed.elements.push(entry);
      // Validate the selector independently: incomplete steps can still be edited.
      if(!entry.selector.window||!['uia','win32'].includes(entry.selector.backend)||!['title','class_name','process_name'].some(k=>entry.selector.window[k])||!('path' in entry.selector||'criteria' in entry.selector))throw Error('选择器需要 backend、window 和 path / criteria');
      await request('validate_selector',{selector:entry.selector});
      flow=proposed;$('#element-dialog').close();dirty();toast('元素已保存');
    }catch(error){report(error);}
  };
  $('#test-element').onclick=async()=>{
    if(toolBusy||busy)return;
    toolBusy=true;$('#test-element').disabled=true;render();
    try{const response=await request('test_element',{selector:JSON.parse($('#element-selector').value)});$('#selector-result').textContent='定位成功：'+JSON.stringify(response.result);log('元素定位测试成功','success');}
    catch(error){$('#selector-result').textContent='定位失败：'+error.message;}
    finally{toolBusy=false;$('#test-element').disabled=false;render();}
  };
  $('#close-windows').onclick=()=>$('#window-dialog').close();
  $('#canvas').ondragover=e=>e.preventDefault();
  $('#canvas').ondrop=e=>insertDrop(e,'root',flow.steps.length);
  $('#run').onclick=async()=>{
    busy=true;runId=null;Object.keys(states).forEach(k=>delete states[k]);Object.keys(variables).forEach(k=>delete variables[k]);Object.keys(variableTypes).forEach(k=>delete variableTypes[k]);Object.keys(loopProgress).forEach(k=>delete loopProgress[k]);render();$('#runstatus').textContent='启动中';
    try{await request('run_flow',{flow:clone(flow)});}catch(error){busy=false;$('#runstatus').textContent='启动失败';render();report(error);}
  };
  $('#stop').onclick=()=>request('stop_run').catch(report);
  $('#clear').onclick=()=>$('#logs').replaceChildren();
  $('#new').onclick=askNewProject;
  $('#sample').onclick=async()=>{closeProjectMenu();try{const sample=await (await fetch('sample-flow.json')).json();await createProject(sample.name,sample);toast('已载入窗体自动化示例');}catch(e){report(e);}};
  $('#save').onclick=async()=>{
    closeProjectMenu();
    try {
      const contents=JSON.stringify(flow,null,2);
      if(window.NL_MODE==='window'){
        let target=await Neutralino.os.showSaveDialog('导出流程与元素库',{defaultPath:'sneerrpa-flow.json',filters:[{name:'SneerRPA 流程',extensions:['json']}]});
        if(!target)return;
        if(!target.toLowerCase().endsWith('.json'))target+='.json';
        await Neutralino.filesystem.writeFile(target,contents);
      }else{
        const url=URL.createObjectURL(new Blob([contents],{type:'application/json'}));
        const a=el('a');a.href=url;a.download='sneerrpa-flow.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }
      toast('流程与元素库已导出');
    }catch(error){report(error);}
  };
  const importContents=async contents=>{
    const data=normalize(JSON.parse(contents));await createProject(data.name,data);toast('流程与元素库已导入');
  };
  $('#open').onclick=async()=>{
    closeProjectMenu();
    if(window.NL_MODE!=='window')return $('#file').click();
    try{const paths=await Neutralino.os.showOpenDialog('导入流程',{multiSelections:false,filters:[{name:'SneerRPA 流程',extensions:['json']}]});
      if(paths.length)await importContents(await Neutralino.filesystem.readFile(paths[0]));
    }catch(error){report(error);}
  };
  $('#file').onchange=async e=>{
    try{const file=e.target.files[0];if(!file)return;await importContents(await file.text());}
    catch(error){report(error);}finally{e.target.value='';}
  };
}
function onEvent(event) {
  const d=event.detail;
  if(d.request_id&&pending.has(d.request_id)){
    const p=pending.get(d.request_id);clearTimeout(p.timer);pending.delete(d.request_id);
    if(d.event==='error')p.reject(Error(d.message));else p.resolve(d);
  }
  if(d.event==='export_started')exportId=d.export_id;
  if(d.event==='export_progress'&&(!exportId||d.export_id===exportId)){
    const panel=$('#export-exe-log'),lines=(panel.textContent+'\n'+d.message).trim().split('\n');panel.textContent=lines.slice(-300).join('\n');panel.scrollTop=panel.scrollHeight;return;
  }
  if(d.event==='export_finished'&&(!exportId||d.export_id===exportId)){
    exportBusy=false;
    $('#export-exe-status').textContent=d.status==='completed'?`导出完成：${d.path}（${(d.size/1024/1024).toFixed(1)} MB）`:d.message;
    if(d.status==='failed')$('#export-exe-details').open=true;
    log($('#export-exe-status').textContent,d.status==='completed'?'success':d.status==='failed'?'error':'info');setExportUI();return;
  }
  if(d.event==='run_started'){runId=d.run_id;busy=true;$('#runstatus').textContent='运行中';}
  if(d.run_id&&d.run_id!==runId)return;
  if(d.event==='variable'){variables[d.name]=d.value;variableTypes[d.name]=d.value_type;renderVariables();return;}
  if(d.event==='node_started')states[d.node_id]='running';
  if(d.event==='node_finished')states[d.node_id]='completed';
  if(d.event==='node_failed')states[d.node_id]='failed';
  if(d.event==='node_skipped')states[d.node_id]='skipped';
  if(d.event==='loop_iteration'){
    loopProgress[d.node_id]=d.iteration+'/'+d.total;
    const loop=findStep(d.node_id);
    if(loop)for(const {step} of FlowModel.walk(loop.body_steps||[])){delete states[step.id];delete loopProgress[step.id];}
  }
  if(d.run_id&&d.message)log(d.message,d.event==='node_failed'||d.status==='failed'?'error':d.event==='node_finished'||d.status==='completed'?'success':'info');
  if(d.event==='run_finished'){
    busy=false;runId=null;$('#runstatus').textContent=({completed:'执行成功',stopped:'已停止',failed:'执行失败'})[d.status]||d.status;
    for(const id in states)if(states[id]==='running')states[id]='stopped';
  }
  if(d.event.startsWith('node_')||d.event.startsWith('run_')||d.event==='loop_iteration')render();
}
async function boot() {
  const catalog=await (await fetch('actions.json')).json();
  definitions=Object.fromEntries(catalog.map(d=>[d.type,d]));
  installFlow({schema_version:1,name:'Windows 窗体自动化',steps:[],elements:[]});
  wireUI();renderActions();log('工作区就绪，正在连接 Python 引擎…');
  if(typeof Neutralino==='undefined')throw Error('请使用 npm start 启动桌面程序');
  Neutralino.events.on('rpa',onEvent);
  Neutralino.events.on('ready',async()=>{
    try{
      await request('ping');ready=true;$('#engine').textContent='● Python 引擎在线';$('#engine').classList.add('online');
      loaded=true;setView('home');$('#saved').textContent='';await refreshProjects();render();
    }catch(error){report(error);$('#saved').textContent='加载失败，可载入示例';loaded=true;render();}
  });
  Neutralino.events.on('serverOffline',()=>{ready=false;busy=false;toolBusy=false;if(exportBusy){exportBusy=false;$('#export-exe-status').textContent='引擎连接已断开，导出已中止';setExportUI();}$('#engine').textContent='● 引擎连接已断开';$('#engine').classList.remove('online');for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('引擎连接已断开'));}pending.clear();render();});
  Neutralino.init();
}
boot().catch(report);
