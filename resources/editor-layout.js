'use strict';
const EditorLayout={
  init(){
    const main=document.querySelector('main'),workspace=document.querySelector('.workspace');
    const storageKey='sneerrpa.layout.v1';
    let sizes={left:245,right:310,console:225};
    try{const saved=JSON.parse(localStorage.getItem(storageKey));for(const key of Object.keys(sizes))if(Number.isFinite(saved?.[key]))sizes[key]=saved[key];}catch{}
    const clamp=(value,min,max)=>Math.max(min,Math.min(value,max));
    const limits=()=>({left:[200,Math.min(420,main.clientWidth-sizes.right-372)],right:[260,Math.min(520,main.clientWidth-sizes.left-372)],console:[120,Math.min(560,workspace.clientHeight-215)]});
    const apply=()=>{
      if(main.hidden)return;
      // Reserve a usable canvas when the host window gets smaller.
      sizes.left=clamp(sizes.left,200,420);sizes.right=clamp(sizes.right,260,520);
      let excess=sizes.left+sizes.right+372-main.clientWidth;
      if(excess>0){const reduce=Math.min(excess,sizes.right-260);sizes.right-=reduce;excess-=reduce;sizes.left=Math.max(200,sizes.left-excess);}
      const bounds=limits();sizes.console=clamp(sizes.console,...bounds.console);
      main.style.setProperty('--left-size',sizes.left+'px');main.style.setProperty('--right-size',sizes.right+'px');
      workspace.style.setProperty('--console-size',sizes.console+'px');
      for(const [key,id]of [['left','palette-resizer'],['right','properties-resizer'],['console','console-resizer']]){
        const bar=document.getElementById(id);bar.setAttribute('aria-valuemin',bounds[key][0]);bar.setAttribute('aria-valuemax',Math.max(bounds[key][0],bounds[key][1]));bar.setAttribute('aria-valuenow',sizes[key]);
      }
    };
    const save=()=>{try{localStorage.setItem(storageKey,JSON.stringify(sizes));}catch{}};
    for(const [key,id,sign]of [['left','palette-resizer',1],['right','properties-resizer',-1],['console','console-resizer',-1]]){
      const bar=document.getElementById(id),position=e=>key==='console'?e.clientY:e.clientX;
      let drag=null;
      bar.onpointerdown=e=>{
        if(e.button!==0)return;e.preventDefault();bar.setPointerCapture(e.pointerId);
        drag={start:position(e),value:sizes[key]};document.body.classList.add('resizing',key==='console'?'resizing-row':'resizing-column');bar.classList.add('active');
      };
      bar.onpointermove=e=>{if(!drag)return;sizes[key]=clamp(drag.value+sign*(position(e)-drag.start),...limits()[key]);apply();};
      const end=()=>{if(!drag)return;drag=null;bar.classList.remove('active');document.body.classList.remove('resizing','resizing-row','resizing-column');save();};
      bar.onpointerup=end;bar.onpointercancel=end;bar.onlostpointercapture=end;
      bar.onkeydown=e=>{
        const direction=key==='console'?{ArrowUp:1,ArrowDown:-1}:{ArrowLeft:-sign,ArrowRight:sign};
        if(!direction[e.key])return;e.preventDefault();sizes[key]=clamp(sizes[key]+direction[e.key]*16,...limits()[key]);apply();save();
      };
      bar.ondblclick=()=>{sizes[key]={left:245,right:310,console:225}[key];apply();save();};
    }
    const button=document.getElementById('expand-workspace');
    const expand=value=>{document.body.classList.toggle('workspace-expanded',value);button.setAttribute('aria-pressed',value);button.textContent=value?'⤡ 还原布局':'⤢ 放大编排区';button.title=value?'还原布局（Esc）':'放大编排区';if(!value)apply();};
    button.onclick=()=>expand(!document.body.classList.contains('workspace-expanded'));
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]'))expand(false);});
    window.addEventListener('resize',()=>{if(!document.body.classList.contains('workspace-expanded'))apply();});
    apply();
  }
};
