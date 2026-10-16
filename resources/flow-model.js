'use strict';
const FlowModel={
  branches(step){return step.type==='control.if'?['then_steps','else_steps']:step.type==='control.loop'?['body_steps']:[];},
  walk(steps,parentId=null,branch=null){
    return steps.flatMap((step,index)=>[{step,list:steps,index,parentId,branch},...this.branches(step).flatMap(key=>this.walk(step[key]||[],step.id,key))]);
  },
  outputs(step){
    const p=step.params,name=p.output;if(!name)return {};
    const types={'variable.set':p.value_type,'window.get':'window','window.exists':'bool','app.launch':'number','element.wait':'bool','image.find':'match'};
    const output={[name]:types[step.type]||(step.type==='element.read'&&['text','value'].includes(p.info)?'string':'object')};
    if(step.type==='image.find')for(const [field,type]of Object.entries({found:'bool',score:'number',x:'number',y:'number',width:'number',height:'number',center:'point','center.x':'number','center.y':'number'}))output[name+'.'+field]=type;
    return output;
  },
  before(steps,id,known={}){
    known={...known};
    for(const step of steps){
      if(step.id===id)return {found:true,types:known};
      if(step.type==='control.loop'){
        const body=this.before(step.body_steps||[],id,{...known,[step.params.index_variable]:'number'});
        if(body.found)return body;
      }else if(step.type==='control.if'){
        const yes=this.before(step.then_steps||[],id,known),no=this.before(step.else_steps||[],id,known);
        if(yes.found)return yes;if(no.found)return no;
        known=Object.fromEntries(Object.entries(yes.types).filter(([key,value])=>no.types[key]===value));
      }else Object.assign(known,this.outputs(step));
    }
    return {found:false,types:known};
  }
};
