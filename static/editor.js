'use strict';
// Editing is local until an explicit evaluation or drag release. Server validates all saved data.
let curveData=null,curveTransform=null,curveDrag=null,curveUndo=[],curveSectionKey='',curveStale=true;
const modeNames={basic:'基本の角度・厚み',distribution:'角度・厚み分布',direct:'両面直接編集（3次B-spline）'};
function editingSection(){return active().row.sections.find(s=>s.id===$('editSection').value)||active().row.sections[0];}
function resetCurveContext(){curveUndo=[];curveSectionKey='';curveData=null;curveStale=true;curveDrag=null;}
function sectionMode(s){return s.profile?.mode||'basic';}
function sideLabel(side){const pressure=active().row.pressure_side;return`面${side}${!pressure||pressure==='unspecified'?'':pressure===side?'（圧力面・想定）':'（負圧面・想定）'}`;}
function invalidateCurveEvaluation(){curveStale=true;$('sectionMetrics').replaceChildren();$('conversionInfo').textContent='変更後の評価が必要です。';$('gapResults').replaceChildren();const c=$('curvatureCanvas');c.getContext('2d').clearRect(0,0,c.width,c.height);}
function renderCurveEditor(){
 const old=$('editSection').value;$('editSection').replaceChildren();active().row.sections.forEach(s=>$('editSection').add(new Option(`${fmt(s.span*100)}% スパン / ${modeNames[sectionMode(s)]}`,s.id)));
 $('editSection').value=active().row.sections.some(s=>s.id===old)?old:active().row.sections[0].id;
 const s=editingSection(),mode=sectionMode(s);if(curveSectionKey!==s.id){curveUndo=[];curveSectionKey=s.id;curveData=null;curveStale=true;}
 $('editMode').textContent=modeNames[mode];$('pressureSide').value=active().row.pressure_side||'unspecified';
 $('modeHelp').textContent=mode==='direct'?'面A・面Bの制御点を直接編集できます。前縁始点は共有します。形状からの再近似による分布方式への変換は行わず、履歴から元の方式へ戻せます。':mode==='distribution'?'角度[°]は軸方向の局所勾配、厚み[m]は中心線法線方向です。取付角は角度分布の積分結果になります。':'基本値の表から形状を作成しています。「角度・厚み分布の編集へ」で分布曲線を編集できます。';
 const oldKind=$('curveKind').value;$('curveKind').replaceChildren();const keys=mode==='direct'?[['side_a',sideLabel('A')+' 制御点'],['side_b',sideLabel('B')+' 制御点']]:mode==='distribution'?[['angles','中心線角度分布'],['thicknesses','法線厚み分布']]:[];
 keys.forEach(([value,label])=>$('curveKind').add(new Option(label,value)));if(keys.some(([v])=>v===oldKind))$('curveKind').value=oldKind;
 $('lockNose').checked=s.profile?.lock_nose_tangent!==false;$('lockNose').disabled=mode!=='direct';renderCurvePoints();drawCurveEditor();
}
function rememberCurve(){curveUndo.push({section:structuredClone(editingSection()),id:editingSection().id});if(curveUndo.length>30)curveUndo.shift();}
function replaceEditingSection(s){const row=active().row;const index=row.sections.findIndex(x=>x.id===s.id);if(index<0)throw Error('断面が見つかりません。');row.sections[index]=s;}
function curvePoints(){const s=editingSection();return s.profile?.[$('curveKind').value]||[];}
function setCurvePoint(key,index,point){
 const s=editingSection(),p=s.profile;if(!p)return;
 if(!point.every(Number.isFinite))throw Error('曲線の点は有限の数値で指定してください。');
 if(p.mode==='distribution'){
  const points=p[key];
  if(index>0&&point[0]<=points[index-1][0]||index<points.length-1&&point[0]>=points[index+1][0])throw Error('分布点の位置は前後の点の間に指定してください。');
  if(key==='angles'&&Math.abs(point[1])>75)throw Error('角度は±75°以内です。');
  if(key==='thicknesses'&&(point[1]<0||point[1]>=s.chord*.4||index>0&&point[1]===0))throw Error('前縁以外の厚みは正で、軸方向コードの40%未満にしてください。');
 }else if(point.some(v=>Math.abs(v)>5))throw Error('制御点の座標は±5 m以内です。');
 if(p.mode==='direct'){
  const other=key==='side_a'?'side_b':'side_a';
  if(index===0){const delta=point.map((v,j)=>v-p[key][0][j]);for(const side of [key,other])for(const i of [0,1])p[side][i]=p[side][i].map((v,j)=>v+delta[j]);}
  else {p[key][index]=point;if(index===1&&p.lock_nose_tangent!==false){const nose=p[key][0],v=point.map((x,j)=>x-nose[j]),length=Math.hypot(...v),h=Math.hypot(...p[other][1].map((x,j)=>x-nose[j]));if(length>1e-12)p[other][1]=nose.map((x,j)=>x-h*v[j]/length);}}
 }else{
  const points=p[key];if(index===0)point[0]=0;if(index===points.length-1)point[0]=1;
  if(key==='thicknesses'&&index===0)point[1]=0;
  points[index]=point;
 }
}
function renderCurvePoints(){const table=$('curvePoints');table.replaceChildren();const s=editingSection(),mode=sectionMode(s),key=$('curveKind').value,points=curvePoints();const head=document.createElement('tr');for(const title of ['点',mode==='direct'?'x [mm]':'軸方向位置比 u',mode==='direct'?'y [mm]':key==='angles'?'局所中心線角 [°]':'法線厚み [mm]','']){const th=document.createElement('th');th.textContent=title;head.append(th);}table.append(head);
 points.forEach((point,i)=>{const tr=document.createElement('tr'),index=document.createElement('td');index.textContent=i;tr.append(index);for(let j=0;j<2;j++){const td=document.createElement('td'),input=document.createElement('input');input.type='number';input.step='any';const scale=mode==='direct'||key==='thicknesses'&&j===1?1000:1;input.value=Number((point[j]*scale).toPrecision(9));input.setAttribute('aria-label',`${key} ${i} ${j}`);if(mode==='distribution'&&(j===0&&(i===0||i===points.length-1)||key==='thicknesses'&&j===1&&i===0))input.disabled=true;input.onchange=()=>{rememberCurve();const p=points[i].slice();p[j]=input.value===''?NaN:Number(input.value)/scale;try{setCurvePoint(key,i,p);changed();}catch(e){curveUndo.pop();message(e.message,true);}renderCurvePoints();drawCurveEditor();};td.append(input);tr.append(td);}const td=document.createElement('td');if(mode==='distribution'&&i>0&&i<points.length-1&&points.length>3){const button=document.createElement('button');button.textContent='削除';button.onclick=()=>{rememberCurve();points.splice(i,1);changed();renderCurvePoints();drawCurveEditor();};td.append(button);}tr.append(td);table.append(tr);});
}
function splineBasis(count,u){if(u>=1)return Array(count-1).fill(0).concat(1);const knots=[0,0,0,0,...Array.from({length:count-4},(_,i)=>(i+1)/(count-3)),1,1,1,1];let weights=knots.slice(0,-1).map((v,i)=>Number(v<=u&&u<knots[i+1]));for(let degree=1;degree<=3;degree++){weights=weights.slice(0,-1).map((v,i)=>{const a=knots[i+degree]-knots[i],b=knots[i+degree+1]-knots[i+1];return(a?(u-knots[i])/a*v:0)+(b?(knots[i+degree+1]-u)/b*weights[i+1]:0);});}return weights;}
function directSides(s){return['side_a','side_b'].map(key=>Array.from({length:161},(_,i)=>{const w=splineBasis(s.profile[key].length,i/160);return[0,1].map(j=>s.profile[key].reduce((sum,p,k)=>sum+p[j]*w[k],0)+(j?s.lean:s.sweep));}));}
function drawCurveEditor(){
 const s=editingSection(),mode=sectionMode(s),canvas=$('curveCanvas'),reference=curveData?.reference_sides;
 const sides=mode==='direct'?directSides(s):curveData?.sides;
 const controls=mode==='direct'?['side_a','side_b'].map(key=>s.profile[key].map(([x,y])=>[x+s.sweep,y+s.lean])):[];
 const all=[...(sides||[]).flat(),...(reference||[]).flat(),...controls.flat()].filter(p=>p.every(Number.isFinite));
 if(all.length){let t;if(curveDrag?.id==='curveCanvas'){const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);t={ctx,...curveDrag.transform};}else t=fitted(canvas,all,45);const {ctx,at,scale}=t;curveTransform={at,scale,center:at([0,0])};reference?.forEach(side=>path(ctx,side.map(at),'#b8c2cb',2));sides?.forEach((side,j)=>path(ctx,side.map(at),j?'#ce792e':'#008c83',2));controls.forEach((points,j)=>{path(ctx,points.map(at),j?'#edc7a3':'#a5d9d1',1);points.forEach(p=>{const q=at(p);ctx.fillStyle=j?'#ce792e':'#008c83';ctx.beginPath();ctx.arc(q[0],q[1],5,0,7);ctx.fill();});});ctx.fillStyle='#52697e';ctx.font='13px sans-serif';ctx.fillText(curveStale?'編集中：評価・3D更新が必要':'評価済み / x,y [m]',15,24);}else{canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);curveTransform=null;}
 drawDistributionEditor('angleCanvas','angles');drawDistributionEditor('thicknessCanvas','thicknesses');
}
let graphTransforms={};
function pchipValue(points,x){
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),h=xs.slice(1).map((v,i)=>v-xs[i]),d=ys.slice(1).map((v,i)=>(v-ys[i])/h[i]),m=Array(xs.length).fill(0);
 for(let i=1;i<xs.length-1;i++)if(d[i-1]*d[i]>0){const w1=2*h[i]+h[i-1],w2=h[i]+2*h[i-1];m[i]=(w1+w2)/(w1/d[i-1]+w2/d[i]);}
 const end=(h0,h1,d0,d1)=>{const v=((2*h0+h1)*d0-h0*d1)/(h0+h1);return v*d0<=0?0:d0*d1<0?Math.sign(v)*Math.min(Math.abs(v),3*Math.abs(d0)):v;};
 m[0]=end(h[0],h[1],d[0],d[1]);m[m.length-1]=end(h.at(-1),h.at(-2),d.at(-1),d.at(-2));let i=h.findIndex((_,j)=>x<=xs[j+1]);if(i<0)i=h.length-1;const t=Math.max(0,Math.min(1,(x-xs[i])/h[i]));return(2*t**3-3*t*t+1)*ys[i]+(t**3-2*t*t+t)*h[i]*m[i]+(-2*t**3+3*t*t)*ys[i+1]+(t**3-t*t)*h[i]*m[i+1];
}
function drawDistributionEditor(id,key){const canvas=$(id),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);const s=editingSection();const points=s.profile?.mode==='distribution'?s.profile[key]:[];ctx.font='14px sans-serif';ctx.fillStyle='#52697e';ctx.fillText(key==='angles'?'中心線角度 [°] / 位置比 u':'法線厚み [mm] / 位置比 u',16,22);if(!points.length){ctx.fillText('角度・厚み分布方式で編集できます',16,65);delete graphTransforms[id];return;}
 const ymin=key==='angles'?-75:0,ymax=curveDrag?.id===id?curveDrag.graph.ymax:key==='angles'?75:Math.max(...points.map(p=>p[1]),.00001)*1.35;
 const left=45,top=40,width=canvas.width-80,height=canvas.height-70;const at=([u,v])=>[left+u*width,top+height-(v-ymin)/(ymax-ymin)*height];graphTransforms[id]={left,top,width,height,ymin,ymax,at,key};const interp=key==='thicknesses'?points.map(([u,v])=>[Math.sqrt(u),v]):points;const samples=Array.from({length:201},(_,i)=>{const u=i/200;return[u,pchipValue(interp,key==='thicknesses'?Math.sqrt(u):u)];});path(ctx,samples.map(at),key==='angles'?'#008c83':'#ce792e',2);points.forEach(p=>{const q=at(p);ctx.beginPath();ctx.arc(q[0],q[1],5,0,7);ctx.fillStyle=key==='angles'?'#008c83':'#ce792e';ctx.fill();});ctx.fillStyle='#52697e';ctx.fillText('0',left,canvas.height-5);ctx.fillText('1',left+width,canvas.height-5);ctx.fillText(fmt(ymax*(key==='angles'?1:1000)),5,top+10);ctx.fillText(fmt(ymin),5,top+height);}
async function refreshCurve(){const s=editingSection(),id=s.id,seq=epoch;const response=await api('/api/section',{...payload(),section_id:id});if(seq!==epoch||editingSection().id!==id)return;curveData=response;curveStale=false;drawCurveEditor();renderCurveEvaluation();}
function renderCurveEvaluation(){if(!curveData)return;const m=curveData.metrics;$('sectionMetrics').replaceChildren();for(const [name,value,unit] of [['取付角（形状から）',m.stagger_deg,'°'],['最小両面距離の目安',m.minimum_surface_distance_m===null?null:m.minimum_surface_distance_m*1000,'mm'],['前縁の接線差',m.nose_tangent_error_deg,'°'],['前縁の隙間',m.leading_gap_m*1000,'mm'],['後縁の厚み',m.trailing_gap_m*1000,'mm'],['最大絶対曲率',m.max_abs_curvature_per_m,'1/m']]){const el=document.createElement('div');el.className='metric';const label=document.createElement('span');label.textContent=name;const b=document.createElement('b');b.textContent=value===null?'評価不可':`${fmt(value,3)} ${unit}`;el.append(label,b);$('sectionMetrics').append(el);}
 const history=editingSection().profile_history||[],error=curveData.current_error;const source=history.at(-1);$('conversionInfo').textContent=source?`変換前形状を保持（${history.length}件）。変換時の最大差 ${fmt(source.conversion_error.max_m*1000,4)} mm / 現在の最大差 ${fmt(error.max_m*1000,4)} mm、RMS ${fmt(error.rms_m*1000,4)} mm。離散点と折線による双方向比較。`:'変換履歴なし。';
 const canvas=$('curvatureCanvas'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);const values=[...m.curvature_a,...m.curvature_b],ymin=Math.min(0,...values),ymax=Math.max(0,...values),range=ymax-ymin||1;const at=(u,v)=>[55+u*(canvas.width-90),canvas.height-30-(v-ymin)/range*(canvas.height-70)];
 path(ctx,[at(0,0),at(1,0)],'#d6e1e8');[m.curvature_a,m.curvature_b].forEach((series,j)=>path(ctx,series.map((v,i)=>at(i/(series.length-1),v)),j?'#ce792e':'#008c83',1.5));ctx.fillStyle='#52697e';ctx.font='13px sans-serif';ctx.fillText('符号付き曲率 [1/m] / 各面の曲線パラメータ 0 → 1（離散近似）',16,20);ctx.fillText(fmt(ymax,0),4,48);ctx.fillText(fmt(ymin,0),4,canvas.height-27);ctx.fillText('0',55,canvas.height-8);ctx.fillText('1',canvas.width-40,canvas.height-8);
}
async function afterShapePreview(){
 const table=$('gapResults');table.replaceChildren();const h=document.createElement('tr');for(const text of ['スパン','最小翼間隙間 mm（近似）']){const th=document.createElement('th');th.textContent=text;h.append(th);}table.append(h);mesh.layers.forEach(l=>{const tr=document.createElement('tr');for(const text of [`${fmt(l.span*100)}%`,fmt(l.minimum_passage_gap_m*1000,4)]){const td=document.createElement('td');td.textContent=text;tr.append(td);}table.append(tr);});await refreshCurve();
}
async function convertEditing(target){const s=editingSection();if(sectionMode(s)===target)throw Error('すでにその編集方式です。');const seq=epoch;const r=await api('/api/convert',{...payload(),section_id:s.id,target,control_count:Number($('controlCount').value)});if(seq!==epoch)throw Error('処理中に入力が変更されました。もう一度変換してください。');replaceEditingSection(r.section);changed();renderSections();await preview();message(`編集方式を変更しました。最大変換差 ${fmt(r.conversion_error.max_m*1000,4)} mm。変換前の形状を保持しています。`);}
$('toDistribution').onclick=()=>task(()=>convertEditing('distribution'));
$('toDirect').onclick=()=>task(()=>convertEditing('direct'));
$('restoreProfile').onclick=()=>task(async()=>{const s=editingSection(),seq=epoch;const r=await api('/api/restore',{...payload(),section_id:s.id});if(seq!==epoch)throw Error('処理中に入力が変更されました。');replaceEditingSection(r.section);changed();renderSections();await preview();message('変換前の定義へ戻しました。');});
$('undoCurve').onclick=()=>task(async()=>{const undo=curveUndo.pop();if(!undo||undo.id!==editingSection().id)throw Error('戻せる曲線編集がありません。');replaceEditingSection(undo.section);changed();renderSections();await preview();});
$('editSection').onchange=()=>task(async()=>{curveUndo=[];curveSectionKey=editingSection().id;curveData=null;curveStale=true;renderCurveEditor();await refreshCurve();});
$('curveKind').onchange=()=>{renderCurvePoints();drawCurveEditor();};
$('pressureSide').onchange=()=>{active().row.pressure_side=$('pressureSide').value;changed();renderCurveEditor();};
$('lockNose').onchange=()=>{const s=editingSection();if(sectionMode(s)!=='direct')return;rememberCurve();s.profile.lock_nose_tangent=$('lockNose').checked;if(s.profile.lock_nose_tangent)setCurvePoint('side_a',1,s.profile.side_a[1].slice());changed();renderCurvePoints();drawCurveEditor();};
$('evaluateSection').onclick=()=>task(preview);
$('addCurvePoint').onclick=()=>{const points=curvePoints();if(sectionMode(editingSection())!=='distribution')return message('分布曲線の点を追加する機能です。B-splineの制御点数は変換時に選択してください。',true);if(points.length>=41)return message('分布点は最大41個です。',true);let index=0,gap=0;points.slice(1).forEach((p,i)=>{const g=p[0]-points[i][0];if(g>gap){gap=g;index=i;}});rememberCurve();points.splice(index+1,0,points[index].map((x,j)=>(x+points[index+1][j])/2));changed();renderCurvePoints();drawCurveEditor();};
function canvasPosition(canvas,e){const rect=canvas.getBoundingClientRect();return[(e.clientX-rect.left)*canvas.width/rect.width,(e.clientY-rect.top)*canvas.height/rect.height];}
function beginCurveDrag(id,e){if(busy)return;const canvas=$(id),q=canvasPosition(canvas,e),s=editingSection();let candidates=[];if(id==='curveCanvas'&&sectionMode(s)==='direct'&&curveTransform){for(const key of ['side_a','side_b'])s.profile[key].forEach((p,i)=>candidates.push({key,index:i,at:curveTransform.at([p[0]+s.sweep,p[1]+s.lean])}));}else if(graphTransforms[id]){const g=graphTransforms[id];s.profile[g.key].forEach((p,i)=>candidates.push({key:g.key,index:i,at:g.at(p)}));}else return;
 const hit=candidates.map(p=>({...p,distance:Math.hypot(p.at[0]-q[0],p.at[1]-q[1])})).sort((a,b)=>a.distance-b.distance)[0];if(!hit||hit.distance>18)return;rememberCurve();curveDrag={id,key:hit.key,index:hit.index,transform:curveTransform,graph:graphTransforms[id]};canvas.setPointerCapture?.(e.pointerId);$('curveKind').value=hit.key;renderCurvePoints();}
function moveCurveDrag(e){if(!curveDrag)return;const canvas=$(curveDrag.id),q=canvasPosition(canvas,e),s=editingSection();let point;if(curveDrag.id==='curveCanvas'){const t=curveDrag.transform;point=[(q[0]-t.center[0])/t.scale-s.sweep,(t.center[1]-q[1])/t.scale-s.lean];}else{const g=curveDrag.graph,points=s.profile[curveDrag.key],i=curveDrag.index;let u=Math.max(0,Math.min(1,(q[0]-g.left)/g.width));if(i>0)u=Math.max(points[i-1][0]+.0001,u);if(i<points.length-1)u=Math.min(points[i+1][0]-.0001,u);const v=Math.max(g.ymin,Math.min(g.ymax,g.ymax-(q[1]-g.top)/g.height*(g.ymax-g.ymin)));point=[u,curveDrag.key==='thicknesses'&&i>0?Math.max(.000001,v):v];}try{setCurvePoint(curveDrag.key,curveDrag.index,point);changed();drawCurveEditor();}catch(e){message(e.message,true);}}
for(const id of ['curveCanvas','angleCanvas','thicknessCanvas']){const c=$(id);c.onpointerdown=e=>beginCurveDrag(id,e);c.onpointermove=moveCurveDrag;c.onpointerup=()=>{if(!curveDrag)return;curveDrag=null;renderCurvePoints();task(preview);};c.onpointercancel=()=>{curveDrag=null;renderCurvePoints();};}
