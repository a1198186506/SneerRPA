// Regression: the shipped Windows example must launch its own bundled fixture.
const {spawn}=require('node:child_process');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),python=path.join(root,'.venv/Scripts/python.exe');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 const job=process.argv[2]?path.resolve(process.argv[2]):path.join(root,'.tmp','sample-exe-'+Date.now());
 if(!process.argv[2]){
 await fs.mkdir(job,{recursive:true});
 await fs.copyFile(path.join(root,'resources/sample-flow.json'),path.join(job,'workflow.json'));
 const build=spawn(python,[path.join(root,'extensions/exe_export.py'),job],{cwd:root,windowsHide:true});
 let buffer='',tail=[];
 build.stdout.on('data',chunk=>{buffer+=chunk.toString('utf8');const lines=buffer.split('\n');buffer=lines.pop();for(const line of lines){try{const item=JSON.parse(line);if(item.message)tail.push(item.message);tail=tail.slice(-20);}catch{}}});
 build.stderr.on('data',chunk=>tail.push(chunk.toString()));
 const code=await new Promise(resolve=>build.on('exit',resolve));assert.equal(code,0,tail.join('\n'));
 }
 const isolated=await fs.mkdtemp(path.join(os.tmpdir(),'SneerRPA-sample-'));
 const exe=path.join(isolated,'Windows 窗体示例.exe');await fs.copyFile(path.join(job,'dist/workflow.exe'),exe);
 const prepared=JSON.parse(await fs.readFile(path.join(job,'workflow.json'),'utf8'));
 assert(prepared.steps[0].params.args.at(-1).startsWith('sneerrpa-resource://'));
 assert.equal(await fs.access(path.join(isolated,'tools/test-window.ps1')).then(()=>true,()=>false),false);
 const events=path.join(isolated,'events.jsonl'),env={...process.env,PATH:'C:\\Windows\\System32;C:\\Windows;C:\\Windows\\System32\\WindowsPowerShell\\v1.0'};delete env.PYTHONHOME;delete env.PYTHONPATH;
 const running=spawn(exe,['--sneerrpa-worker','--events',events],{cwd:isolated,windowsHide:true,env});
 const exited=new Promise(resolve=>running.on('exit',resolve));
 let timer;const timeout=new Promise((resolve,reject)=>{timer=setTimeout(()=>{running.kill();reject(Error('Bundled sample timeout'));},45000);});
 let exit;try{exit=await Promise.race([exited,timeout]);}finally{clearTimeout(timer);}
 const output=(await fs.readFile(events,'utf8')).trim().split('\n').map(line=>JSON.parse(line));
 assert.equal(exit,0,JSON.stringify(output));
 assert(output.some(item=>item.name==='result_text'&&item.value==='已确认：Hello SneerRPA · 你好 RPA + {test}'),JSON.stringify(output));
 assert.equal(output.filter(item=>item.event==='node_finished').length,10);
 assert(output.some(item=>item.event==='run_finished'&&item.status==='completed'));
 console.log('PASS: actual bundled Windows example runs all 10 nodes from an unrelated folder without tools/ or Python on PATH');
 console.log('Verified EXE: '+exe);
})().catch(error=>{console.error(error);process.exitCode=1;});
