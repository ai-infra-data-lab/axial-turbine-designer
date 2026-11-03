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
 window.eval((await readFile(path.join(root,'static','app.js'),'utf8'))+'\n'+(await readFile(path.join(root,'static','editor.js'),'utf8'))+'\n'+(await readFile(path.join(root,'static','aero.js'),'utf8'))+'\n'+(await readFile(path.join(root,'static','radial.js'),'utf8'))+'\n'+(await readFile(path.join(root,'static','edges.js'),'utf8'))+'\n'+(await readFile(path.join(root,'static','meridional.js'),'utf8')));
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
 // Radial equilibrium: solve, plot, candidates, persistence, grid change and failure retention.
 await click('runRadial');assert.match($('radialState').textContent,/計算完了/);assert.equal($('radialStation').options.length,5);assert.equal($('radialResults').rows.length,34);assert.equal($('radialSummary').children.length,6);
 $('radialStation').value=$('radialStation').options[1].value;$('radialStation').dispatchEvent(new window.Event('change'));$('radialMetric').value='pressure';$('radialMetric').dispatchEvent(new window.Event('change'));assert.ok(canvasLogs.get('radialPlot').points.length>20);
 await click('radialCandidates');assert.ok($('radialCandidateResults').rows.length>=3);assert.match($('message').textContent,/専用ボタン/);
 const downloads=[];window.URL.createObjectURL=blob=>{downloads.push(blob);return'blob:test';};window.URL.revokeObjectURL=()=>{};window.HTMLAnchorElement.prototype.click=function(){};
 await click('exportRadial');const csv=await downloads[0].text();assert.match(csv,/radial_pressure_residual/);assert.equal(csv.trim().split(/\r?\n/).length,167);
 await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();assert.equal(current.design.radial.enabled,true);assert.equal(current.result.radial.status,'computed');
 $('saved').value=id;await click('load');assert.equal($('radialEnabled').checked,true);assert.equal($('radialStation').options.length,5);
 $('radialPoints').value='65';$('radialPoints').dispatchEvent(new window.Event('change'));assert.equal($('radialResults').rows.length,0);await click('runRadial');assert.equal($('radialResults').rows.length,66);
 $('radialLaw').value='1';$('radialLaw').dispatchEvent(new window.Event('change'));await click('runRadial',()=>$('message').className==='error');assert.match($('radialState').textContent,/不成立/);assert.equal($('summary').children.length,6);assert.match($('radialError').textContent,/亜音速解/);
 $('radialEnabled').checked=false;$('radialEnabled').dispatchEvent(new window.Event('change'));await click('run');assert.equal($('radialResults').rows.length,0);
 // Explicit radial-to-basic geometry transfer, stale selection protection and persisted restoration.
 $('radialLaw').value='-1';$('radialLaw').dispatchEvent(new window.Event('change'));$('radialFlow').value='meanline_anchor';$('radialFlow').dispatchEvent(new window.Event('change'));await click('runRadial');
 $('row').value='1:1';$('row').dispatchEvent(new window.Event('change'));await waitFor(()=>!$('preview').disabled,'basic row');
 await click('radialCandidates');assert.match($('radialCandidateResults').textContent,/入口角変更/);
 $('row').value='0:0';$('row').dispatchEvent(new window.Event('change'));await waitFor(()=>!$('preview').disabled,'switch row');
 await click('applyRadialAngles',()=>$('message').className==='error');assert.match($('message').textContent,/再表示/);
 $('row').value='1:1';$('row').dispatchEvent(new window.Event('change'));await waitFor(()=>!$('preview').disabled,'return row');
 await click('save');await click('radialCandidates');current=await(await fetch(base+'/api/design?id='+id)).json();const beforeTransfer=structuredClone(current.design.stages[1].rows[1].sections);
 await click('applyRadialAngles');assert.match($('message').textContent,/5断面/);assert.equal($('radialResults').rows.length,0);assert.equal($('summary').children.length,0);
 await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();assert.equal(current.result,null);assert.notEqual(current.design.stages[1].rows[1].sections[0].outlet_angle,beforeTransfer[0].outlet_angle);assert.ok(current.design.stages[1].rows[1].sections[0].profile_history.at(-1).analysis_source.input_hash);
 $('saved').value=id;await click('load');$('editSection').value=beforeTransfer[0].id;$('editSection').dispatchEvent(new window.Event('change'));await waitFor(()=>!$('preview').disabled,'selected section');await click('restoreProfile');await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();const restored=current.design.stages[1].rows[1].sections[0];delete restored.profile_history;assert.deepEqual(restored,beforeTransfer[0]);
 await click('runRadial');await click('radialCandidates');$('radialIncidence').value='1';$('radialIncidence').dispatchEvent(new window.Event('change'));await click('applyRadialAngles',()=>$('message').className==='error');assert.match($('message').textContent,/再表示/);
 // Dedicated LE/TE geometry: exact arcs, joins, history, conversion and persistence.
 await click('evaluateSection');$('edgeEnabled').checked=true;await click('applyEdges');assert.equal($('edgeConnections').rows.length,9);assert.match($('edgeSummary').textContent,/TE接続部厚み/);assert.ok(canvasLogs.get('leadingEdgePlot').points.length>10);assert.ok(canvasLogs.get('trailingEdgePlot').points.length>10);
 await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();assert.equal(current.design.schema_version,6);assert.equal(current.design.stages[1].rows[1].sections[0].edges.enabled,true);assert.equal(current.result,null);
 $('edge_le_type').value='ellipse';$('edge_le_ratio').value='1.7';$('edge_le_orientation').value='8';$('edge_te_type').value='ellipse';$('edge_te_ratio').value='1.8';$('edge_continuity').value='G1';await click('applyEdges');assert.equal($('edgeConnections').rows.length,9);assert.match($('edgeSummary').textContent,/G1/);
 $('edge_te_type').value='flat';$('edge_continuity').value='G2';await click('applyEdges');assert.equal($('edgeConnections').rows.length,7);await click('toDistribution');await click('evaluateSection');assert.equal($('edgeConnections').rows.length,7);
 await click('toDirect');assert.equal($('edgeEnabled').disabled,true);await click('evaluateSection');assert.equal($('edgeConnections').rows.length,0);await click('save');$('saved').value=id;await click('load');await click('restoreProfile');await click('evaluateSection');assert.equal($('edgeEnabled').disabled,false);assert.equal($('edgeConnections').rows.length,7);
 $('edge_le_radius').value='1000000';await click('applyEdges',()=>$('message').className==='error');assert.match($('message').textContent,/le_radius/);await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();assert.ok(current.design.stages[1].rows[1].sections[0].edges.le_radius<.01);
 $('saved').value=id;await click('load');$('edgeEnabled').checked=false;await click('applyEdges');assert.equal($('edgeConnections').rows.length,0);await click('restoreProfile');await click('evaluateSection');assert.equal($('edgeConnections').rows.length,7);
 // Meridional wall editing, placement, mapping and explicitly bounded analysis.
 await click('resetMeridional');assert.equal($('meridionalPlacements').rows.length,5);assert.ok($('meridionalStations').rows.length>100);
 $('meridionalEnabled').checked=true;$('meridionalEnabled').dispatchEvent(new window.Event('change'));$('meridionalWall').value='casing';$('meridionalWall').dispatchEvent(new window.Event('change'));$('addWallPoint').click();assert.equal($('meridionalWallPoints').rows.length,4);
 let wallInput=$('meridionalWallPoints').rows[3].cells[2].querySelector('input');wallInput.value='.27';wallInput.dispatchEvent(new window.Event('change'));await click('applyMeridional');assert.match($('meridionalState').textContent,/適用中/);assert.ok(canvasLogs.get('mesh').points.length>100);
 const gapInput=$('meridionalPlacements').rows[2].cells[5].querySelector('input');gapInput.value='.012';gapInput.dispatchEvent(new window.Event('change'));await click('applyMeridional');assert.ok(Math.abs(Number($('meridionalPlacements').rows[2].cells[5].querySelector('input').value)-.012)<1e-8);
 const wallCanvas=$('meridionalDesignPlot');wallCanvas.getBoundingClientRect=()=>({left:0,top:0,width:1100,height:390});const handle=canvasLogs.get('meridionalDesignPlot').arcs.at(-2);wallCanvas.dispatchEvent(pointerEvent('pointerdown',handle[0],handle[1]));wallCanvas.dispatchEvent(pointerEvent('pointermove',handle[0],handle[1]-3));wallCanvas.dispatchEvent(pointerEvent('pointerup',handle[0],handle[1]-3));assert.match($('meridionalState').textContent,/編集中/);await click('applyMeridional');
 await click('run');assert.equal($('meridionalComparisons').rows.length,5);assert.match($('resultState').textContent,/参考面積比較/);await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();assert.equal(current.design.schema_version,6);assert.equal(current.result.analysis_scope,'reference_meanline_only');assert.equal(current.result.meridional.input_hash,current.result.input_hash);
 $('saved').value=id;await click('load');assert.equal($('meridionalEnabled').checked,true);assert.equal($('meridionalComparisons').rows.length,5);
 await click('exportMeridional');const meridionalCsv=await downloads.at(-1).text();assert.match(meridionalCsv,/geometry_hash/);assert.match(meridionalCsv,/m2/);
 await click('runRadial',()=>$('message').className==='error');assert.match($('radialError').textContent,/子午面.*未対応/);assert.equal($('summary').children.length,6);
 $('meridionalTargetTe').value=String(Number($('meridionalTargetTe').value)+.001);await click('applyMeridionalTe');assert.equal($('meridionalComparisons').rows.length,1);await click('save');current=await(await fetch(base+'/api/design?id='+id)).json();assert.equal(current.design.stages[1].rows[1].sections[0].profile_history.at(-1).target_mode,'meridional_chord');
 $('meridionalWall').value='casing';$('meridionalWall').dispatchEvent(new window.Event('change'));wallInput=$('meridionalWallPoints').rows[3].cells[2].querySelector('input');wallInput.value='.1';wallInput.dispatchEvent(new window.Event('change'));await click('applyMeridional',()=>$('message').className==='error');assert.match($('message').textContent,/交差/);await click('discardMeridionalDraft');assert.equal($('meridionalEnabled').checked,true);
 $('meridionalInterpolation').value='linear';$('meridionalInterpolation').dispatchEvent(new window.Event('change'));await click('applyMeridional');assert.match($('meridionalWarnings').textContent,/角があり/);$('meridionalEnabled').checked=false;$('meridionalEnabled').dispatchEvent(new window.Event('change'));await click('applyMeridional');assert.match($('meridionalState').textContent,/無効/);
 // Common exchange is additional sampled output and read-only receipt, not design import.
 await click('save');const beforeCommon=await(await fetch(base+'/api/design?id='+id)).json();
 await click('commonExport');const commonDoc=JSON.parse(await downloads.at(-1).text());assert.equal(commonDoc.format,'turbomachinery-geometry');assert.equal(commonDoc.coordinates.rotation_axis,'Z');assert.equal(commonDoc.source.rotation_sign,-1);
 async function checkCommonFile(value){const input=$('commonCheck');Object.defineProperty(input,'files',{value:[{size:JSON.stringify(value).length,text:async()=>JSON.stringify(value)}],configurable:true,writable:true});input.dispatchEvent(new window.Event('change'));await waitFor(()=>!$('commonExport').disabled,'common check');}
 await checkCommonFile(commonDoc);assert.equal($('message').className,'',$('message').textContent);assert.match($('commonReceipt').textContent,/axial_turbine_designer/);assert.match($('commonReceipt').textContent,/取込.*行っていません/);assert.equal($('message').className,'');
 const afterCommon=await(await fetch(base+'/api/design?id='+id)).json();assert.deepEqual(afterCommon,beforeCommon);
 commonDoc.rows[0].curves[0].points[0][1]*=2;await checkCommonFile(commonDoc);assert.equal($('commonReceipt').textContent,'');assert.equal($('message').className,'error');assert.match($('message').textContent,/hash mismatch/);
 const power=[...$('conditions').querySelectorAll('input')][4];power.value='1000000000';power.dispatchEvent(new window.Event('change'));await click('run',()=>$('message').className==='error');assert.match($('message').textContent,/過大/);assert.equal($('summary').children.length,0);
 console.log('PASS: existing 63 scenarios plus common JSON export, read-only integrity receipt without design changes, and tampered content rejection (66 scenarios).');
}finally{if(window)await window.happyDOM.abort();proc.kill();}
