'use strict';
function renderAnalysisControls(){
 const prediction=design.analysis.mode==='row_models';$('analysisMode').value=design.analysis.mode;
 $('gasViscosity').value=design.analysis.viscosity;$('inletFlowAngle').value=design.analysis.inlet_angle;
 $('gasViscosity').disabled=!prediction;$('inletFlowAngle').disabled=!prediction;
 const keys=Object.keys(conditionLabels),inputs=$('conditions').querySelectorAll('input');
 inputs[keys.indexOf('stage_efficiency')].disabled=prediction;
 $('stageSettings').querySelectorAll('input').forEach(input=>input.disabled=prediction);
 $('analysisHelp').textContent=prediction?'翼列モデルでは、入力した金属角・スロート比と損失から出力を予測します。要求出力は比較目標、段効率・反動度・仕事配分比は使用しません。一定軸流速度から必要面積を逆算する予備解析です。':'従来の指定出力・段効率方式です。静翼を全圧損失なしとし、段損失を動翼側に集約します。下の翼列モデル設定は使用しません。';
 renderAeroRow();
}
function renderAeroRow(){
 const a=active().row.aero;$('aeroFields').replaceChildren();
 function select(key,title,options){const label=document.createElement('label');label.textContent=title;const input=document.createElement('select');input.id='aero_'+key;options.forEach(([v,n])=>input.add(new Option(n,v)));input.value=a[key];input.onchange=()=>{a[key]=input.value;changed();renderAeroRow();};label.append(input);$('aeroFields').append(label);}
 select('loss_model','損失モデル',[['soderberg_2016','Soderberg型（2016掲載式）'],['specified_y','全圧損失係数Yを指定']]);
 select('deviation_model','流出角モデル',[['ainley_mathieson','Ainley–Mathieson 偏差'],['aungier','Aungier 偏差'],['metal_offset','金属角＋指定偏差']]);
 for(const [key,title] of [['inlet_metal_angle','入口金属角 [°]'],['outlet_metal_angle','出口金属角 [°]'],['axial_chord','相関用の軸方向コード [m]'],['throat_ratio','スロート面積比 At/Aout'],['specified_y','指定損失Y [−]'],['specified_deviation','指定偏差（流れ−金属）[°]'],['critical_mach','臨界参照Mach数 [−]']]){
  const label=document.createElement('label');label.textContent=title;const input=document.createElement('input');input.id='aero_'+key;input.type='number';input.step='any';input.value=a[key]===null?'':a[key];input.placeholder='未設定';
  input.disabled=key==='specified_y'&&a.loss_model!=='specified_y'||key==='specified_deviation'&&a.deviation_model!=='metal_offset'||key==='critical_mach'&&a.deviation_model==='metal_offset';
  input.onchange=()=>{a[key]=input.value===''?null:Number(input.value);if(['inlet_metal_angle','outlet_metal_angle','axial_chord'].includes(key)&&a.geometry_binding){a.geometry_binding=null;a.source='手動修正：'+a.source;$('aeroSource').value=a.source;}changed();renderAeroBinding();};label.append(input);$('aeroFields').append(label);
 }
 $('aeroSource').value=a.source;renderAeroBinding();
}
function renderAeroBinding(){const a=active().row.aero;$('aeroBinding').textContent=a.geometry_binding?`形状のスパン ${fmt(a.geometry_binding.span*100)}% から明示的に転記。計算時に形状変更を確認します。`:'1D用の独立入力。未設定の係数やスロート比を自動で仮定しません。';}
function clearAeroResults(){$('rowResults').replaceChildren();$('powerComparison').replaceChildren();}
function renderAeroResults(){clearAeroResults();if(result?.analysis_mode!=='row_models')return;
 $('resultState').textContent=result.applicability==='outside'?'計算完了・適用条件外を含む（実験未検証）':'計算完了・翼列相関モデル（実験未検証）';
 const p=document.createElement('p');p.className='hint';p.textContent=`予測出力 ${fmt(result.summary.power/1000)} kW / 目標 ${fmt(result.summary.target_power/1000)} kW / 差 ${fmt(result.summary.power_difference/1000)} kW。目標値への一致は拘束していません。`;$('powerComparison').append(p);
 const columns=[['stage','段'],['kind','翼列'],['loss_model','損失モデル'],['deviation_model','偏差モデル'],['inlet_angle','入口流れ角 °'],['metal_out','出口金属角 °'],['flow_out','出口流れ角 °'],['incidence','入射角 °'],['deviation','δmetal °'],['Y','全圧損失Y'],['loss_coefficient','モデル係数 ζ またはY'],['frame_mach_out','出口Ma（列の系）'],['reynolds_Dh','Re_Dh'],['entropy_generation','Δs J/(kg K)'],['applicability','適用状態']];
 const head=document.createElement('tr');columns.forEach(([,name])=>{const th=document.createElement('th');th.textContent=name;head.append(th);});$('rowResults').append(head);
 result.blade_rows.forEach(row=>{const tr=document.createElement('tr');columns.forEach(([key])=>{const td=document.createElement('td');const value=row[key];td.textContent=key==='kind'?(value==='rotor'?'動翼（相対）':'静翼（絶対）'):key==='applicability'?(value==='outside'?'条件外あり':'確認範囲内'):value===null?'未算出':typeof value==='number'?fmt(value,4):value;tr.append(td);});$('rowResults').append(tr);});
}
$('analysisMode').onchange=()=>{design.analysis.mode=$('analysisMode').value;changed();renderEditor();};
$('gasViscosity').onchange=()=>{design.analysis.viscosity=Number($('gasViscosity').value);changed();};
$('inletFlowAngle').onchange=()=>{design.analysis.inlet_angle=Number($('inletFlowAngle').value);changed();};
$('aeroSource').oninput=()=>{active().row.aero.source=$('aeroSource').value;changed();};
$('aeroFromShape').onclick=()=>task(async()=>{const seq=epoch,{si,ri}=active();const r=await api('/api/aero-from-shape',payload());if(seq!==epoch||active().si!==si||active().ri!==ri)throw Error('処理中に入力が変更されました。');active().row.aero=r.aero;changed();renderAeroRow();message('金属角とコードを転記しました。スロート面積比は根拠を確認して入力してください。');});
