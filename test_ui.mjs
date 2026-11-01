// Offscreen DOM + real local HTTP integration. Does not establish browser visual QA.
import {Window} from 'happy-dom';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
const root=path.dirname(fileURLToPath(import.meta.url));
const bundledPython=path.join(root,'..','.runtime','python','python.exe');
const python=process.env.PYTHON || (existsSync(bundledPython)?bundledPython:process.platform==='win32'?'python':'python3');
const proc=spawn(python,['-u','-c',"import tempfile; from pathlib import Path; from server import make_server; t=tempfile.TemporaryDirectory(); s=make_server(0,Path(t.name)/'ui.sqlite3'); print(s.server_port,flush=True); s.serve_forever()"],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
let stderr='';proc.stderr.on('data',b=>stderr+=b);
let window;
try{
 const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('server timeout '+stderr)),15000);proc.stdout.once('data',b=>{clearTimeout(timer);resolve(Number(b.toString().trim()));});proc.once('error',reject);proc.once('exit',code=>{clearTimeout(timer);reject(Error('server exited '+code+' '+stderr));});});
 const base=`http://127.0.0.1:${port}`;
 window=new Window({url:base,settings:{disableJavaScriptFileLoading:true,disableCSSFileLoading:true}});
 let drawingCalls=0;const contexts=new Map(),canvasLogs=new Map();
 window.HTMLCanvasElement.prototype.getContext=function(){const id=this.id;if(!contexts.has(id)){canvasLogs.set(id,{arcs:[],points:[]});contexts.set(id,new Proxy({}, {get(target,key){if(key in target)return target[key];return(...args)=>{if(['moveTo','lineTo','arc','clearRect'].includes(key)){assert.ok(args.every(v=>typeof v!=='number'||Number.isFinite(v)),`nonfinite drawing ${id} ${key}`);drawingCalls++;}if(key==='clearRect'){canvasLogs.get(id).arcs=[];canvasLogs.get(id).points=[];}if(key==='arc')canvasLogs.get(id).arcs.push(args);if(key==='moveTo'||key==='lineTo')canvasLogs.get(id).points.push(args);};},set(target,key,value){target[key]=value;return true;}}));}return contexts.get(id);};
 window.fetch=(url,options)=>fetch(new URL(url,base),options);
 window.structuredClone=structuredClone;
 // Happy DOM does not expose the browser's legacy Option constructor.
 window.Option=function(text,value){const o=window.document.createElement('option');o.textContent=text;o.value=value;return o;};
 Object.defineProperty(window,'crypto',{value:webcrypto});
 window.confirm=()=>true;
 window.document.write(await readFile(path.join(root,'static','index.html'),'utf8'));
 window.eval((await readFile(path.join(root,'static','app.js'),'utf8'))+'\n'+(await readFile(path.join(root,'static','editor.js'),'utf8'))+'\n'+(await readFile(path.join(root,'static','aero.js'),'utf8')));
 const $=id=>window.document.getElementById(id);
 async function waitFor(predicate,label){const start=Date.now();while(!predicate()){if(Date.now()-start>10000)throw Error(label+' / '+$('message').textContent);await new Promise(r=>setTimeout(r,25));}}
 async function click(id,predicate=()=>$('message').className!=='error'){$(id).click();await waitFor(()=>!$(id).disabled,'button '+id);assert.ok(predicate(),`${id}: ${$('message').textContent}`);}
 await waitFor(()=>$('status').textContent.includes('仮の入力例'),'bootstrap');
 assert.equal($('sections').rows.length,6);assert.equal($('row').options.length,4);assert.ok(drawingCalls>1000);
 await click('run');assert.equal($('summary').children.length,6);assert.equal($('results').rows.length,3);
 await click('save');assert.match($('status').textContent,/revision 1/);
 const bootstrap=await(await fetch(base+'/api/bootstrap')).json();assert.equal(bootstrap.saved.length,1);
 const id=bootstrap.saved[0].id;
 const name=$('name');name.value='UI変更テスト';name.dispatchEvent(new window.Event('input'));
 assert.equal($('summary').children.length,0);assert.match($('resultState').textContent,/更新必要/);
 await click('save');assert.match($('status').textContent,/revision 2/);
 $('saved').value=id;await click('load');assert.equal($('name').value,'UI変更テスト');
 await click('addSection');assert.equal($('sections').rows.length,7);await click('preview');
 $('addStage').click();assert.equal($('row').options.length,6);await click('run');assert.equal($('results').rows.length,4);
 $('removeStage').click();assert.equal($('row').options.length,4);
 const projectId=webcrypto.randomUUID(),componentId=webcrypto.randomUUID();
 const bundle={format:'gas-turbine-manager',bundle_version:1,revision:7,project:{id:projectId,name:'関連案件',components:[{id:componentId,name:'軸流タービン',kind:'turbine'}]}};
 const file={size:100,text:async()=>JSON.stringify(bundle)};
 Object.defineProperty($('managerFile'),'files',{value:[file],configurable:true});
 $('managerFile').dispatchEvent(new window.Event('change'));await waitFor(()=>$('component').options.length===2,'manager JSON');
 $('component').value=componentId;await click('link');assert.match($('linkInfo').textContent,/revision 7/);
 await click('save');const saved=await(await fetch(base+'/api/design?id='+id)).json();assert.equal(saved.design.link.project_id,projectId);assert.equal(saved.design.link.component_id,componentId);
 $('unlink').click();assert.match($('linkInfo').textContent,/単独案件/);
 // Distribution editing, mode conversion, drag, diagnostics and persistent history.
 await click('preview');await click('toDistribution');assert.match($('editMode').textContent,/角度・厚み分布/);
 assert.ok($('curvePoints').rows.length>10);assert.equal($('sectionMetrics').children.length,6);
 const angle=$('curvePoints').rows[4].cells[2].querySelector('input');angle.value=Number(angle.value)+1;angle.dispatchEvent(new window.Event('change'));assert.equal($('sectionMetrics').children.length,0);
 await click('evaluateSection');assert.match($('conversionInfo').textContent,/現在の最大差/);
 const curvatureX=canvasLogs.get('curvatureCanvas').points.map(p=>p[0]);assert.ok(Math.max(...curvatureX)-Math.min(...curvatureX)>900,'curvature graph must use full horizontal width');
 const angleCanvas=$('angleCanvas');angleCanvas.getBoundingClientRect=()=>({left:0,top:0,width:700,height:200});
 const anglePoint=canvasLogs.get('angleCanvas').arcs[7];
 const pointerEvent=(type,x,y)=>{const e=new window.Event(type);Object.assign(e,{clientX:x,clientY:y,pointerId:2});return e;};
 angleCanvas.dispatchEvent(pointerEvent('pointerdown',anglePoint[0],anglePoint[1]));angleCanvas.dispatchEvent(pointerEvent('pointermove',anglePoint[0],anglePoint[1]-3));angleCanvas.dispatchEvent(pointerEvent('pointerup',anglePoint[0],anglePoint[1]-3));await waitFor(()=>!$('preview').disabled,'angle drag evaluation');assert.equal($('message').className,'');
 $('curveKind').value='thicknesses';$('curveKind').dispatchEvent(new window.Event('change'));const oldCount=$('curvePoints').rows.length;$('addCurvePoint').click();assert.equal($('curvePoints').rows.length,oldCount+1);await click('evaluateSection');
 const thicknessInput=$('curvePoints').rows[4].cells[2].querySelector('input'),originalThickness=thicknessInput.value;thicknessInput.value='-2';thicknessInput.dispatchEvent(new window.Event('change'));assert.equal($('message').className,'error');assert.equal($('curvePoints').rows[4].cells[2].querySelector('input').value,originalThickness);await click('evaluateSection');
 $('controlCount').value='25';await click('toDirect');assert.match($('editMode').textContent,/両面直接/);assert.equal($('curvePoints').rows.length,26);assert.equal($('lockNose').checked,true);
 await click('save');let current=await(await fetch(base+'/api/design?id='+id)).json();let currentRow=current.design.stages[0].rows[1],section=currentRow.sections.find(s=>s.id===$('editSection').value);const beforeA=structuredClone(section.profile.side_a),beforeB=structuredClone(section.profile.side_b);assert.equal(section.profile_history.length,2);
 // Drag a rendered interior B-spline handle using its recorded Canvas position.
 const canvas=$('curveCanvas');canvas.getBoundingClientRect=()=>({left:0,top:0,width:700,height:420});
 const point=canvasLogs.get('curveCanvas').arcs[8];assert.ok(point);
 const event=(type,x,y)=>{const e=new window.Event(type);Object.assign(e,{clientX:x,clientY:y,pointerId:1});return e;};
 canvas.dispatchEvent(event('pointerdown',point[0],point[1]));canvas.dispatchEvent(event('pointermove',point[0],point[1]+8));canvas.dispatchEvent(event('pointerup',point[0],point[1]+8));await waitFor(()=>!$('preview').disabled,'drag evaluation');assert.equal($('sectionMetrics').children.length,6);
 await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();section=current.design.stages[0].rows[1].sections.find(s=>s.id===$('editSection').value);assert.notDeepEqual(section.profile.side_a,beforeA);assert.deepEqual(section.profile.side_b,beforeB);
 await click('undoCurve');await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();section=current.design.stages[0].rows[1].sections.find(s=>s.id===$('editSection').value);assert.deepEqual(section.profile.side_a,beforeA);
 await click('restoreProfile');assert.match($('editMode').textContent,/角度・厚み分布/);await click('restoreProfile');assert.match($('editMode').textContent,/基本/);
 $('saved').value=id;await click('load');assert.match($('editMode').textContent,/両面直接/);assert.ok($('gapResults').rows.length>=18);
 // Blade-row prediction uses explicit inputs and keeps the legacy design mode available.
 $('analysisMode').value='row_models';$('analysisMode').dispatchEvent(new window.Event('change'));
 assert.equal([...$('conditions').querySelectorAll('input')][7].disabled,true);
 await click('run',()=>$('message').className==='error');assert.match($('message').textContent,/inlet_metal_angle/);
 for(const option of [...$('row').options]){
  $('row').value=option.value;$('row').dispatchEvent(new window.Event('change'));await waitFor(()=>!$('preview').disabled,'row selection');
  await click('aeroFromShape');const ratio=$('aero_throat_ratio');ratio.value='.4';ratio.dispatchEvent(new window.Event('change'));
 }
 await click('run');assert.equal($('rowResults').rows.length,5);assert.match($('resultState').textContent,/適用条件外/);assert.match($('powerComparison').textContent,/目標/);
 await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();assert.equal(current.design.analysis.mode,'row_models');assert.equal(current.result.blade_rows.length,4);assert.ok(current.result.sources.loss.includes('doi.org'));
 $('aero_deviation_model').value='aungier';$('aero_deviation_model').dispatchEvent(new window.Event('change'));assert.equal($('rowResults').rows.length,0);await click('run');assert.equal($('rowResults').rows.length,5);
 $('aero_loss_model').value='specified_y';$('aero_loss_model').dispatchEvent(new window.Event('change'));const lossY=$('aero_specified_y');assert.equal(lossY.disabled,false);lossY.value='.1';lossY.dispatchEvent(new window.Event('change'));await click('run');assert.equal($('rowResults').rows.length,5);
 $('analysisMode').value='specified_efficiency';$('analysisMode').dispatchEvent(new window.Event('change'));assert.equal($('rowResults').rows.length,0);await click('run');assert.equal($('summary').children.length,6);
 const power=[...$('conditions').querySelectorAll('input')][4];power.value='1000000000';power.dispatchEvent(new window.Event('change'));await click('run',()=>$('message').className==='error');assert.match($('message').textContent,/過大/);assert.equal($('summary').children.length,0);
 console.log('PASS: existing 24 flows plus row-model selection/missing inputs, explicit geometry transfer, per-row prediction, model persistence, Aungier/Y changes, and return to legacy mode (30 scenarios).');
}finally{if(window)await window.happyDOM.abort();proc.kill();}
