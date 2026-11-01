'use strict';
let radialCandidateContext=null;
function clearRadialCandidates(){radialCandidateContext=null;$('radialCandidateResults').replaceChildren();}
function renderRadialControls(){
 const r=design.radial;$('radialEnabled').checked=r.enabled;$('radialExponent').value=r.exponent;
 $('radialLaw').value=[-1,0,1].includes(r.exponent)?String(r.exponent):'custom';
 $('radialPoints').value=String(r.points);$('radialFlow').value=r.flow_mode;
 $('radialIncidence').value=r.design_incidence;$('radialDeviation').value=r.design_deviation;
}
function clearRadialResults(){
 clearRadialCandidates();
 $('radialState').textContent='未実行／更新必要';
 for(const id of ['radialSummary','radialResults','radialCandidateResults','radialWarnings','radialError','radialStation','radialStageSummary'])$(id).replaceChildren();
 for(const id of ['radialPlot','radialStagePlot','radialStreamtubes']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
}
function radialReport(){return result?.radial;}
function selectedRadialStation(){return radialReport()?.stations.find(s=>s.id===$('radialStation').value);}
function addRadialTable(id,columns,rows){const table=$(id);table.replaceChildren();const head=document.createElement('tr');columns.forEach(([,name])=>{const th=document.createElement('th');th.textContent=name;head.append(th);});table.append(head);rows.forEach(row=>{const tr=document.createElement('tr');columns.forEach(([key])=>{const td=document.createElement('td');td.textContent=row[key]===null||row[key]===undefined?'—':typeof row[key]==='number'?fmt(row[key],5):String(row[key]);tr.append(td);});table.append(tr);});}
function renderRadialResults(){
 if(!radialReport()){clearRadialResults();return;}
 const r=radialReport();const old=$('radialStation').value;$('radialStation').replaceChildren();
 r.stations.forEach(s=>$('radialStation').add(new Option(s.label,s.id)));
 if(r.stations.some(s=>s.id===old))$('radialStation').value=old;
 $('radialError').replaceChildren();clearRadialCandidates();labels('radialWarnings',r.warnings);
 if(r.status==='failed'){
  $('radialState').textContent='不成立（1D結果は保持）';$('resultState').textContent='1D計算完了・径方向解析は不成立';
  const error=document.createElement('div');error.className='warn';error.textContent=r.error;$('radialError').append(error);
 }else $('radialState').textContent=r.applicability==='outside'?'計算完了・適用条件の確認が必要':'計算完了（簡易径方向平衡）';
 drawRadialStation();drawRadialStreamtubes();
}
function drawIndependentChart(id,series,title,xlabel='スパン [%]'){
 const c=$(id),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);const valid=series.filter(p=>p[1]!==null&&Number.isFinite(p[0])&&Number.isFinite(p[1]));
 ctx.fillStyle='#52697e';ctx.font='13px sans-serif';ctx.fillText(title,16,20);if(!valid.length)return;
 const xs=valid.map(p=>p[0]),ys=valid.map(p=>p[1]);const xmin=Math.min(...xs),xmax=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys),pad=Math.max((y1-y0)*.1,Math.abs(y1)*.02,1e-6),ymin=y0-pad,ymax=y1+pad;
 const at=p=>[65+(p[0]-xmin)/(xmax-xmin||1)*(c.width-100),c.height-40-(p[1]-ymin)/(ymax-ymin)*(c.height-85)];
 path(ctx,valid.map(at),'#087f77',2);ctx.fillText(fmt(ymax,3),4,48);ctx.fillText(fmt(ymin,3),4,c.height-38);ctx.fillText(fmt(xmin),65,c.height-15);ctx.fillText(fmt(xmax),c.width-55,c.height-15);ctx.fillText(xlabel,c.width/2,c.height-5);
}
function drawRadialStation(){
 const s=selectedRadialStation();if(!s){$('radialSummary').replaceChildren();return;}
 $('radialSummary').replaceChildren();for(const [name,value,unit] of [['積分流量',s.mass_flow,'kg/s'],['流量残差',s.mass_residual,'kg/s'],['平均半径の軸流速度',s.reference_axial_velocity,'m/s'],['圧力平衡残差（正規化）',s.pressure_balance_relative,''],['最大絶対Mach数',s.max_mach,''],['最大相対Mach数',s.max_relative_mach,'']]){const el=document.createElement('div');el.className='metric';const label=document.createElement('span');label.textContent=name;const b=document.createElement('b');b.textContent=`${Math.abs(value)<.0001?value.toExponential(2):fmt(value,5)} ${unit}`;el.append(label,b);$('radialSummary').append(el);}
 const metric=$('radialMetric').value;drawIndependentChart('radialPlot',s.points.map(p=>[p.span*100,p[metric]]),`${s.label} / ${$('radialMetric').selectedOptions[0].textContent}`);
 const stage=radialReport().stages.find(x=>x.stage===(s.stage||active().si+1));const skey=$('radialStageMetric').value;
 drawIndependentChart('radialStagePlot',stage?stage.points.map(p=>[p.span*100,p[skey]]):[],$('radialStageMetric').selectedOptions[0].textContent);
 const table=s.points.map(p=>({...p,span_percent:p.span*100}));addRadialTable('radialResults',[['span_percent','スパン %'],['radius','半径 m'],['axial_velocity','Cax m/s'],['swirl_velocity','Cθ m/s'],['alpha','α °'],['beta','β °'],['temperature','静温 K'],['pressure','静圧 Pa'],['mach','Ma絶対'],['relative_mach','Ma相対'],['mass_fraction','累積流量比']],table);
 $('radialStageSummary').textContent=stage?`第${stage.stage}段 積分出力 ${fmt(stage.mass_weighted_power/1000)} kW / 元の1D出力 ${fmt(stage.source_1d_power/1000)} kW / 流管エネルギー最大整合誤差 ${fmt(stage.max_streamtube_energy_residual,5)} J/kg。`:'段の分布は未計算です。';
}
function interpolateRadial(points,key,value,xkey='mass_fraction'){
 if(value<=points[0][xkey])return points[0][key];if(value>=points.at(-1)[xkey])return points.at(-1)[key];
 for(let i=0;i<points.length-1;i++){const a=points[i],b=points[i+1];if(a[xkey]<=value&&value<=b[xkey]){const w=(value-a[xkey])/(b[xkey]-a[xkey]);return a[key]*(1-w)+b[key]*w;}}return null;
}
function drawRadialStreamtubes(){const report=radialReport(),c=$('radialStreamtubes'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(!report?.stations.length)return;
 const stations=report.stations,hub=design.geometry.hub_radius,tip=design.geometry.tip_radius;const at=(i,r)=>[55+i/Math.max(1,stations.length-1)*(c.width-90),c.height-40-(r-hub)/(tip-hub)*(c.height-85)];
 for(const q of [0,.25,.5,.75,1]){path(ctx,stations.map((s,i)=>at(i,interpolateRadial(s.points,'radius',q))),'#168e84',q===0||q===1?2:1);}
 ctx.font='13px sans-serif';ctx.fillStyle='#52697e';ctx.fillText('累積流量 0 / 25 / 50 / 75 / 100% の断面間対応（模式図）',15,20);stations.forEach((s,i)=>ctx.fillText(s.kind==='inlet'?'IN':`${s.stage}${s.kind==='rotor'?'R':'S'}`,at(i,hub)[0]-8,c.height-15));
}
async function calculateRadial(){design.radial.enabled=true;$('radialEnabled').checked=true;changed();const seq=epoch;const r=await api('/api/run',payload());if(seq!==epoch)return;result=r;dirty=true;$('status').textContent='計算完了・未保存';renderResults();message(r.radial.status==='computed'?'半径方向の解析が完了しました。':'1D結果を保持しました。径方向解析の不成立理由を確認してください。',r.radial.status!=='computed');}
$('runRadial').onclick=()=>task(calculateRadial);
$('radialEnabled').onchange=()=>{design.radial.enabled=$('radialEnabled').checked;changed();};
$('radialLaw').onchange=()=>{if($('radialLaw').value==='custom')return;design.radial.exponent=Number($('radialLaw').value);$('radialExponent').value=design.radial.exponent;changed();};
for(const [id,key] of [['radialExponent','exponent'],['radialPoints','points'],['radialIncidence','design_incidence'],['radialDeviation','design_deviation']])$(id).onchange=()=>{design.radial[key]=$(id).value===''?null:Number($(id).value);if(key==='exponent')$('radialLaw').value=[-1,0,1].includes(design.radial.exponent)?String(design.radial.exponent):'custom';changed();};
$('radialFlow').onchange=()=>{design.radial.flow_mode=$('radialFlow').value;changed();};
for(const id of ['radialStation','radialMetric','radialStageMetric'])$(id).onchange=drawRadialStation;
$('radialCandidates').onclick=()=>task(async()=>{if(!result?.radial||result.radial.status!=='computed')throw Error('先に半径方向の解析を完了してください。');const seq=epoch,{si,ri}=active();const r=await api('/api/radial-candidates',payload());if(seq!==epoch)return;radialCandidateContext={hash:r.input_hash,epoch:seq,si,ri};addRadialTable('radialCandidateResults',[['span_percent','スパン %'],['inlet_flow_angle','入口流れ角 °'],['outlet_flow_angle','出口流れ角 °'],['inlet_metal_candidate','入口金属角候補 °'],['outlet_metal_candidate','出口金属角候補 °'],['limit_note','反映対象'],['inlet_change','入口角変更 °'],['outlet_change','出口角変更 °']],r.candidates.map(c=>{const section=active().row.sections.find(s=>s.id===c.section_id);return {...c,span_percent:c.span*100,limit_note:section.profile?'対象外（曲線方式）':c.within_editor_limits?'基本断面へ反映可能':'反映不可（±75°外）',inlet_change:section.profile?null:c.inlet_metal_candidate-section.inlet_angle,outlet_change:section.profile?null:c.outlet_metal_candidate-section.outlet_angle};}));message(r.notice);});
$('exportRadial').onclick=()=>task(async()=>{const report=radialReport();if(report?.status!=='computed')throw Error('先に半径方向の解析を完了してください。');const fields=['span','radius','axial_velocity','swirl_velocity','alpha','beta','temperature','pressure','total_temperature','total_pressure','density','mach','relative_mach','mass_fraction','radial_pressure_residual'];const units=['-','m','m/s','m/s','deg','deg','K','Pa','K','Pa','kg/m3','-','-','-','Pa/m'];const rows=[['station_id','station_label','input_hash',...fields],['-','-','SHA-256',...units]];report.stations.forEach(s=>s.points.forEach(p=>rows.push([s.id,s.label,result.input_hash,...fields.map(k=>p[k]??'')])));const escape=v=>'"'+String(v).replaceAll('"','""')+'"';download('radial-flow.csv','\ufeff'+rows.map(row=>row.map(escape).join(',')).join('\r\n'),'text/csv;charset=utf-8');message('径方向の流れ分布をCSV出力しました。');});

$('applyRadialAngles').onclick=()=>task(async()=>{
 const context=radialCandidateContext,{si,ri}=active();
 if(!context||context.epoch!==epoch||context.si!==si||context.ri!==ri)throw Error('選択翼列の金属角候補を再表示してください。');
 const seq=epoch;
 const r=await api('/api/radial-apply',{...payload(),expected_hash:context.hash});
 if(seq!==epoch||active().si!==si||active().ri!==ri)throw Error('処理中に入力が変更されました。候補を再表示してください。');
 design=r.design;changed();resetCurveContext();renderSections();await preview();
 message(`${r.applied_count}断面：${r.notice}`);
});
