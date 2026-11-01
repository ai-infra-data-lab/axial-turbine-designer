'use strict';
let meridionalDraftRevision=0,meridionalDraft=null,meridionalReport=null,meridionalDraftDirty=false,meridionalTransform=null,meridionalDrag=null;
function syncMeridionalRows(){
 const m=design.meridional;if(!m)return false;const before=JSON.stringify(m);const rows=design.stages.flatMap(s=>s.rows),ids=new Set(rows.map(r=>r.id));
 Object.keys(m.placements).forEach(id=>{if(!ids.has(id))delete m.placements[id];});
 let cursor=Math.max(0,...rows.filter(r=>r.id in m.placements).map(r=>m.placements[r.id]+Math.max(...r.sections.map(s=>s.chord+s.sweep))+.02));let added=false;
 rows.forEach(r=>{if(!(r.id in m.placements)){m.placements[r.id]=cursor;cursor+=Math.max(...r.sections.map(s=>s.chord+s.sweep))+.02;added=true;}});
 if(added)for(const side of ['hub','casing']){const p=m[side];if(cursor>p.at(-1)[0]){if(p.length<41)p.push([cursor,p.at(-1)[1]]);else p.at(-1)[0]=cursor;}}
 return before!==JSON.stringify(m);
}
function renderMeridionalControls(){
 meridionalDraftRevision++;meridionalDraft=structuredClone(design.meridional);meridionalDraftDirty=false;
 $('meridionalEnabled').checked=meridionalDraft.enabled;$('meridionalInterpolation').value=meridionalDraft.interpolation;
 renderWallPoints();renderMeridionalPlacements();renderMeridionalTarget();
}
function clearMeridionalReport(){
 meridionalReport=null;meridionalTransform=null;
 for(const id of ['meridionalStations','meridionalComparisons','meridionalWarnings'])$(id).replaceChildren();
 $('meridionalState').textContent='更新必要';
 for(const id of ['meridionalDesignPlot','meridionalMetricPlot']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
}
function meridionalDraftChanged(){meridionalDraftRevision++;meridionalDraftDirty=true;$('meridionalState').textContent='子午面を編集中：反映が必要';$('meridionalComparisons').replaceChildren();drawMeridionalDraft();}
function renderWallPoints(){
 const side=$('meridionalWall').value,points=meridionalDraft[side],table=$('meridionalWallPoints');table.replaceChildren();
 const head=document.createElement('tr');['点','軸方向 x [m]','半径 r [m]',''].forEach(name=>{const th=document.createElement('th');th.textContent=name;head.append(th);});table.append(head);
 points.forEach((point,i)=>{const row=document.createElement('tr'),number=document.createElement('td');number.textContent=i;row.append(number);
  for(let j=0;j<2;j++){const cell=document.createElement('td'),input=document.createElement('input');input.type='number';input.step='any';input.value=Number.isFinite(point[j])?Number(point[j].toPrecision(10)):'';input.onchange=()=>{point[j]=input.value===''?null:Number(input.value);if(j===0&&(i===0||i===points.length-1)){const other=meridionalDraft[side==='hub'?'casing':'hub'];other[i===0?0:other.length-1][0]=point[j];}meridionalDraftChanged();};cell.append(input);row.append(cell);}
  const cell=document.createElement('td');if(i>0&&i<points.length-1){const button=document.createElement('button');button.textContent='削除';button.onclick=()=>{points.splice(i,1);meridionalDraftChanged();renderWallPoints();};cell.append(button);}row.append(cell);table.append(row);
 });
}
function renderMeridionalPlacements(){
 const table=$('meridionalPlacements');table.replaceChildren();const head=document.createElement('tr');['翼列','配置原点 x [m]','参照LE x [m]','参照TE x [m]','参照コード [m]','前列との包絡間隔 [m]'].forEach(name=>{const th=document.createElement('th');th.textContent=name;head.append(th);});table.append(head);
 let previous=null;
 design.stages.forEach((stage,si)=>stage.rows.forEach(row=>{
  const tr=document.createElement('tr'),name=document.createElement('td');name.textContent=`${si+1} ${row.kind==='stator'?'静翼':'動翼'}`;tr.append(name);
  const cell=document.createElement('td'),input=document.createElement('input');input.type='number';input.step='any';input.value=meridionalDraft.placements[row.id];input.onchange=()=>{meridionalDraft.placements[row.id]=input.value===''?null:Number(input.value);meridionalDraftChanged();renderMeridionalPlacements();renderMeridionalTarget();};cell.append(input);tr.append(cell);
  const p=meridionalReport?.layout.find(p=>p.row_id===row.id),origin=meridionalDraft.placements[row.id];
  const minimum=p?origin+p.minimum_x-p.origin:null,maximum=p?origin+p.maximum_x-p.origin:null;
  const prior=previous;const values=p?[origin+p.reference_le-p.origin,origin+p.reference_te-p.origin,p.reference_axial_chord,prior===null?null:minimum-prior]:[null,null,null,null];previous=maximum;
  values.forEach((v,index)=>{const td=document.createElement('td');if(index===3&&p&&prior!==null){const gap=document.createElement('input');gap.type='number';gap.step='any';gap.value=v;gap.onchange=()=>{if(gap.value==='')return message('翼列間隔を数値で指定してください。',true);meridionalDraft.placements[row.id]=prior+Number(gap.value)-(p.minimum_x-p.origin);meridionalDraftChanged();renderMeridionalPlacements();renderMeridionalTarget();};td.append(gap);}else td.textContent=v===null?'—':fmt(v,6);tr.append(td);});table.append(tr);
 }));
}
function renderMeridionalTarget(){
 if(!meridionalDraft)return;const row=active().row,p=meridionalReport?.layout.find(p=>p.row_id===row.id),s=row.sections.find(s=>s.span===.5)||row.sections[0];
 $('meridionalTargetTe').value=meridionalDraft.placements[row.id]+(p?p.reference_te-p.origin:s.chord+s.sweep);
}
function meridionalTable(id,columns,rows){const table=$(id);table.replaceChildren();const head=document.createElement('tr');columns.forEach(([,title])=>{const th=document.createElement('th');th.textContent=title;head.append(th);});table.append(head);rows.forEach(value=>{const row=document.createElement('tr');columns.forEach(([key])=>{const td=document.createElement('td'),v=value[key];td.textContent=v===null?'—':typeof v==='number'?fmt(v,6):String(v);row.append(td);});table.append(row);});}
function showMeridionalReport(report){
 if(meridionalDraftDirty)return;meridionalReport=report;
 $('meridionalState').textContent=report.enabled?'設計子午面を翼形状に適用中':'子午面は無効（従来の円筒配置）';
 labels('meridionalWarnings',report.warnings);
 meridionalTable('meridionalStations',[['x','x m'],['area','面積 m²'],['height','翼高さ m'],['mean_radius','平均半径 m'],['hub_angle','ハブ傾き °'],['casing_angle','外壁傾き °'],['hub_curvature','ハブ曲率 1/m'],['casing_curvature','外壁曲率 1/m']],report.samples);
 meridionalTable('meridionalComparisons',[['stage','段'],['station','動翼の断面'],['x','x m'],['area','設計面積 m²'],['required_area','参考1D必要面積 m²'],['relative_difference','面積相対差']],report.comparisons);
 renderMeridionalPlacements();renderMeridionalTarget();drawDesignedMeridional('meridionalDesignPlot',report,true);drawMeridionalMetric();
}
async function refreshMeridionalReport(){const seq=epoch;const report=await api('/api/meridional-report',payload());if(seq!==epoch)return;showMeridionalReport(result?.meridional?.input_hash===report.input_hash?result.meridional:report);}
function drawDesignedMeridional(id,report,required){
 const hub=report.samples.map(p=>[p.x,p.hub_radius]),casing=report.samples.map(p=>[p.x,p.casing_radius]);
 const c=$(id),{ctx,at,scale}=fitted(c,[...hub,...casing],45);path(ctx,hub.map(at),'#008c83',2);path(ctx,casing.map(at),'#ce792e',2);
 report.layout.forEach(p=>{const nearest=x=>report.samples.reduce((a,b)=>Math.abs(a.x-x)<Math.abs(b.x-x)?a:b);for(const x of [p.reference_le,p.reference_te]){const wall=nearest(x);path(ctx,[[x,wall.hub_radius],[x,wall.casing_radius]].map(at),'#81939f',1);}ctx.fillStyle='#52697e';ctx.font='11px sans-serif';ctx.fillText(`${p.stage}${p.kind==='stator'?'S':'R'}`,at([p.reference_le,nearest(p.reference_le).casing_radius])[0],32);});
 if(required&&report.comparisons.length){for(const key of ['inlet','outlet']){const values=report.comparisons.filter(p=>p.station===key);for(const sign of [-1,1])path(ctx,values.map(p=>at([p.x,design.conditions.mean_radius+sign*p.required_area/(4*Math.PI*design.conditions.mean_radius)])),'#a54d98',1);}}
 ctx.fillStyle='#52697e';ctx.font='12px sans-serif';ctx.fillText(`x,r [m] / ${report.enabled?'設計子午面':'無効・設定形状の確認'} / 紫：基準半径での必要流路`,12,c.height-10);
 if(id==='meridionalDesignPlot'){meridionalTransform={at,scale,origin:at([0,0])};for(const side of ['hub','casing'])meridionalDraft[side].forEach(p=>{const q=at(p);ctx.beginPath();ctx.arc(q[0],q[1],4,0,7);ctx.fillStyle=side==='hub'?'#008c83':'#ce792e';ctx.fill();});}
}
function drawMeridionalDraft(){
 const all=[...meridionalDraft.hub,...meridionalDraft.casing];if(all.some(p=>p.some(v=>!Number.isFinite(v))))return;
 const c=$('meridionalDesignPlot');let fittedView;
 if(meridionalDrag&&meridionalTransform){c.getContext('2d').clearRect(0,0,c.width,c.height);fittedView={ctx:c.getContext('2d'),...meridionalTransform};}else fittedView=fitted(c,all,45);
 const {ctx,at,scale}=fittedView;meridionalTransform={at,scale,origin:at([0,0])};
 for(const side of ['hub','casing']){const points=meridionalDraft[side];path(ctx,points.map(at),side==='hub'?'#008c83':'#ce792e',2);points.forEach(p=>{const q=at(p);ctx.beginPath();ctx.arc(q[0],q[1],5,0,7);ctx.fill();});}
 ctx.fillStyle='#52697e';ctx.font='12px sans-serif';ctx.fillText('入力点の仮表示：反映後に補間曲線と成立性を評価します。',12,20);
}
function drawMeridionalMetric(){
 if(!meridionalReport)return;const key=$('meridionalMetric').value,points=meridionalReport.samples.filter(p=>Number.isFinite(p[key])).map(p=>[p.x,p[key]]),c=$('meridionalMetricPlot'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(!points.length)return;
 const xmin=points[0][0],xmax=points.at(-1)[0],ys=points.map(p=>p[1]),low=Math.min(...ys),high=Math.max(...ys),pad=Math.max((high-low)*.1,Math.abs(high)*.01,1e-8);const at=p=>[70+(p[0]-xmin)/(xmax-xmin)*(c.width-110),c.height-35-(p[1]-low+pad)/(high-low+2*pad)*(c.height-80)];path(ctx,points.map(at),'#087f77',2);ctx.fillStyle='#52697e';ctx.font='12px sans-serif';ctx.fillText($('meridionalMetric').selectedOptions[0].textContent,12,18);ctx.fillText(fmt(high+pad,6),4,45);ctx.fillText(fmt(low-pad,6),4,c.height-30);ctx.fillText(`x = ${fmt(xmin,4)} ～ ${fmt(xmax,4)} m`,c.width/2,c.height-8);
}
$('meridionalWall').onchange=renderWallPoints;
$('meridionalMetric').onchange=drawMeridionalMetric;
$('meridionalEnabled').onchange=()=>{meridionalDraft.enabled=$('meridionalEnabled').checked;meridionalDraftChanged();};
$('meridionalInterpolation').onchange=()=>{meridionalDraft.interpolation=$('meridionalInterpolation').value;meridionalDraftChanged();};
$('addWallPoint').onclick=()=>{const p=meridionalDraft[$('meridionalWall').value];if(p.length>=41)return message('曲線の点は最大41点です。',true);let i=0;p.slice(1).forEach((v,j)=>{if(v[0]-p[j][0]>p[i+1][0]-p[i][0])i=j;});p.splice(i+1,0,[(p[i][0]+p[i+1][0])/2,(p[i][1]+p[i+1][1])/2]);meridionalDraftChanged();renderWallPoints();};
async function acceptMeridional(path,extra={}){const seq=epoch,draftRevision=meridionalDraftRevision;const r=await api(path,{...payload(),...extra});if(seq!==epoch||draftRevision!==meridionalDraftRevision)throw Error('処理中に入力が変更されました。');design=r.design;changed();renderEditor();await preview();message('子午面・配置を反映しました。未保存です。形状と面積比較を確認してください。');}
$('applyMeridional').onclick=()=>task(()=>acceptMeridional('/api/meridional',{settings:meridionalDraft}));
$('resetMeridional').onclick=()=>task(()=>acceptMeridional('/api/meridional-reset'));
$('discardMeridionalDraft').onclick=()=>task(async()=>{renderMeridionalControls();await refreshMeridionalReport();message('未反映の子午面編集を取り消しました。');});
$('applyMeridionalTe').onclick=()=>task(async()=>{if(meridionalDraftDirty)throw Error('先に子午面・配置を反映してください。');await acceptMeridional('/api/meridional-te',{target_te:$('meridionalTargetTe').value===''?null:Number($('meridionalTargetTe').value)});});
$('exportMeridional').onclick=()=>task(async()=>{if(!meridionalReport||meridionalDraftDirty)throw Error('先に子午面を反映・評価してください。');const fields=['x','hub_radius','casing_radius','height','mean_radius','area','hub_angle','casing_angle','hub_curvature','casing_curvature'];const unit=['m','m','m','m','m','m2','deg','deg','1/m','1/m'];const rows=[['input_hash','geometry_hash',...fields],['SHA-256','SHA-256',...unit],...meridionalReport.samples.map(p=>[meridionalReport.input_hash,meridionalReport.geometry_hash,...fields.map(k=>p[k]??'')])];download('meridional-design.csv','\ufeff'+rows.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n'),'text/csv;charset=utf-8');message('単位と入力ハッシュ付きの子午面CSVを出力しました。');});
const meridionalCanvas=$('meridionalDesignPlot');
function meridionalPointer(event){const rect=meridionalCanvas.getBoundingClientRect();return[(event.clientX-rect.left)*meridionalCanvas.width/rect.width,(event.clientY-rect.top)*meridionalCanvas.height/rect.height];}
meridionalCanvas.onpointerdown=event=>{if(!meridionalTransform||busy)return;const q=meridionalPointer(event),side=$('meridionalWall').value;let best=null,distance=14;meridionalDraft[side].forEach((p,i)=>{const a=meridionalTransform.at(p),v=Math.hypot(a[0]-q[0],a[1]-q[1]);if(v<distance){distance=v;best=i;}});if(best!==null){meridionalDrag={side,index:best};meridionalCanvas.setPointerCapture?.(event.pointerId);}};
meridionalCanvas.onpointermove=event=>{if(!meridionalDrag||busy)return;const {side,index}=meridionalDrag,p=meridionalDraft[side],q=meridionalPointer(event),t=meridionalTransform;let x=(q[0]-t.origin[0])/t.scale,r=(t.origin[1]-q[1])/t.scale;x=Math.max(index?p[index-1][0]+1e-5:-20,Math.min(index<p.length-1?p[index+1][0]-1e-5:20,x));r=Math.max(.0001,Math.min(30,r));p[index]=[x,r];if(index===0||index===p.length-1){const other=meridionalDraft[side==='hub'?'casing':'hub'];other[index===0?0:other.length-1][0]=x;}meridionalDraftChanged();renderWallPoints();};
meridionalCanvas.onpointerup=meridionalCanvas.onpointercancel=()=>{meridionalDrag=null;};
