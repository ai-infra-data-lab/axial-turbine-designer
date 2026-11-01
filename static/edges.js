'use strict';
function edgeDefaults(s){return {enabled:false,le_type:'circle',le_radius:s.chord*.015,le_ratio:1.5,le_orientation:0,le_join:.15,te_type:'circle',te_thickness:s.trailing,te_ratio:1.5,te_wedge:12,te_join:.85,continuity:'G2'};}
function renderEdgeControls(){
 const s=editingSection(),c=s.edges||edgeDefaults(s),direct=sectionMode(s)==='direct';
 $('edgeEnabled').checked=c.enabled;$('edgeEnabled').disabled=direct;$('edgeFields').replaceChildren();
 for(const [key,title,options] of [['le_type','LE形状',[['circle','円'],['ellipse','楕円']]],['te_type','TE形状',[['circle','円弧'],['ellipse','楕円'],['flat','平坦']]],['continuity','翼面との接続',[['G1','接線連続 G1'],['G2','曲率連続 G2']]]]){
  const label=document.createElement('label');label.textContent=title;const input=document.createElement('select');input.id='edge_'+key;options.forEach(([value,name])=>input.add(new Option(name,value)));input.value=c[key];input.disabled=direct;label.append(input);$('edgeFields').append(label);
 }
 for(const [key,title,factor] of [['le_radius','LE先端の曲率半径 [mm]',1000],['le_ratio','LE楕円比（軸／横半径）',1],['le_orientation','LE傾き（入口金属角から）[°]',1],['le_join','LE翼面接続位置 u',1],['te_thickness','TE接続部の厚み [mm]',1000],['te_ratio','TE楕円比（軸／横半径）',1],['te_wedge','TEくさび全角 [°]',1],['te_join','TE翼面接続位置 u',1]]){
  const label=document.createElement('label');label.textContent=title;const input=document.createElement('input');input.type='number';input.step='any';input.id='edge_'+key;input.value=Number((c[key]*factor).toPrecision(10));input.dataset.factor=factor;input.disabled=direct;label.append(input);$('edgeFields').append(label);
 }
 $('edgeHelp').textContent=direct?'両面直接編集では制御点で編集します。専用LE/TE形状へは変換前の定義に戻してください。':'設定を編集して「LE/TE設定を反映・評価」で適用します。有効にしない場合は従来形状です。円形では楕円比を使用しません。';
 clearEdgeEvaluation();
}
function clearEdgeEvaluation(){
 $('edgeConnections').replaceChildren();$('edgeSummary').textContent='断面を評価して接続状態を確認してください。';
 for(const id of ['leadingEdgePlot','trailingEdgePlot']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
}
function drawEdgeZoom(id,sides,leading){
 const canvas=$(id),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
 const samples=sides.map(side=>leading?side.slice(0,Math.ceil(side.length*.31)):side.slice(-Math.ceil(side.length*.31)));
 const points=samples.flat(),xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
 const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),factor=Math.min((canvas.width-70)/Math.max(xmax-xmin,1e-9),(canvas.height-60)/Math.max(ymax-ymin,1e-9));
 const at=p=>[canvas.width/2+(p[0]-(xmin+xmax)/2)*factor,canvas.height/2-(p[1]-(ymin+ymax)/2)*factor];
 samples.forEach((side,i)=>path(ctx,side.map(at),i?'#ce792e':'#008c83',2));
 if(!leading)path(ctx,[samples[0].at(-1),samples[1].at(-1)].map(at),'#52697e',1);
 ctx.fillStyle='#52697e';ctx.font='12px sans-serif';ctx.fillText(`${leading?'LE':'TE'}拡大 / x・y同一倍率 / 表示幅 ${fmt(canvas.width/factor*1000,3)} mm`,12,18);
}
function renderEdgeEvaluation(){
 const report=curveData?.metrics.edge_report;const table=$('edgeConnections');table.replaceChildren();
 if(report){
  $('edgeSummary').textContent=`LE先端半径 ${fmt(report.le_nose_radius_m*1000,4)} mm / TE接続部厚み ${fmt(report.te_interface_thickness_m*1000,4)} mm / ${report.settings.continuity}。接続差は片側差分による数値評価です。`;
  const header=document.createElement('tr');['接続位置','面','接線差 °','曲率差 1/m','曲率相対差'].forEach(name=>{const th=document.createElement('th');th.textContent=name;header.append(th);});table.append(header);
  report.connections.forEach(connection=>{const row=document.createElement('tr');[connection.join,connection.side,connection.tangent_error_deg,connection.curvature_jump_per_m,connection.curvature_relative].forEach(value=>{const td=document.createElement('td');td.textContent=typeof value==='number'?value.toExponential(3):value;row.append(td);});table.append(row);});
 }else $('edgeSummary').textContent='従来形状／直接編集形状：専用LE/TE設定は無効です。';
 if(curveData?.sides){drawEdgeZoom('leadingEdgePlot',curveData.sides,true);drawEdgeZoom('trailingEdgePlot',curveData.sides,false);}
}
$('applyEdges').onclick=()=>task(async()=>{
 const s=editingSection(),seq=epoch,settings={enabled:$('edgeEnabled').checked};
 for(const key of ['le_type','te_type','continuity'])settings[key]=$('edge_'+key).value;
 for(const key of ['le_radius','le_ratio','le_orientation','le_join','te_thickness','te_ratio','te_wedge','te_join'])settings[key]=$('edge_'+key).value===''?null:Number($('edge_'+key).value)/Number($('edge_'+key).dataset.factor);
 const r=await api('/api/edges',{...payload(),section_id:s.id,settings});
 if(seq!==epoch||editingSection().id!==s.id)throw Error('処理中に入力が変更されました。');
 replaceEditingSection(r.section);changed();renderSections();await preview();await refreshCurve();
 message('LE/TE設定を反映しました。形状と接続差を確認してください。変更前の定義は履歴から復元できます。');
});
