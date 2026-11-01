# 1D翼列の損失・流出角偏差モデル

2026-11-01 / 0.3.0。物理計算は `aerodynamics.py`、データ・結果の紐付けは `core.py` が担当します。管理アプリのコードやDBを変更しません。

## 操作

1. 左側「計算方式」を「翼列の損失・偏差から出力を予測」に変更します。
2. 流量、入口全温・全圧、回転数、平均半径、軸流速度、比熱・比熱比、入口絶対流れ角、粘度を設定します。要求出力は比較目標になります。
3. 「翼形状」で段・静翼／動翼を選びます。「選択翼列の1D 損失・流出角偏差」でモデルを設定します。
4. 入口／出口金属角と相関用軸方向コードを手動入力するか、「平均半径の形状から金属角・コードを転記」を使います。基本方式と、平均半径にある角度分布方式の断面から転記できます。直接曲線・座標補間の断面では金属角を一意に定義せず、手動入力を求めます。
5. 全翼列にスロート面積比 `A_throat/A_exit` と根拠を入力します。等高さの直線翼列ではopening/pitchに対応します。形状チェックの最小隙間は有効スロートではないため、自動転記しません。
6. Soderberg型または指定損失Y、AM／Aungier／金属角＋指定偏差を選択します。指定Yでは係数の明示入力が必要です。未設定を0にしません。
7. 「1D計算」で翼列ごとの入射角・流出角・偏差・損失Y・Re・エントロピー生成・適用状態を確認し、保存します。

従来の「指定出力・段効率」方式は残しています。その方式では今回の翼列モデル入力を計算に使用しません。翼列方式では指定段効率・指定反動度・段仕事配分比を使用せず、形状角度から仕事と反動度を求めます。両方の条件を同時に固定しません。

## 解析の境界条件

非冷却・定比熱理想気体・一定平均半径・一定軸流速度・亜音速を仮定します。静翼出口は絶対系、動翼出口は相対系で流出角を解きます。角度は軸方向から正回転方向を正とし、AM/Aungierの流出方向の符号は出口金属角から与えます。

```
U = 2π rpm rm / 60
Ctheta_stator_out = Cax tan(alpha_out)
Ctheta_rotor_out = U + Cax tan(beta_out)
stage_work = U (Ctheta_stator_out - Ctheta_rotor_out)
power = mass_flow Σstage_work
```

流出角とMach数は緩和反復、損失・密度・Re数は別の緩和反復で整合させます。未収束、静温非正、非正の段仕事、入口／出口の列基準Mach数が1以上のケースは計算失敗とします。

入口全温・全圧、速度、角度から出口状態を計算し、流量から必要流路面積を逆算します。固定形状の面積と背圧を境界条件に、流量を解くソルバーではありません。一定軸流速度・同じ流出角なら仕事は同じで、損失を増すと出口全圧と効率が下がります。損失だけを変えて出力も必ず低下させる扱いにはしません。

## 損失モデル

### Soderberg型・2016掲載式を採用する簡易版

出典: Bahr Ennil et al., *Minimization of Loss in Small Scale Axial Air Turbine Using CFD Modelling and Evolutionary Algorithm Optimization*, Applied Thermal Engineering 102 (2016), 841–848。

- DOI: https://doi.org/10.1016/j.applthermaleng.2016.03.077
- 著者版: https://pure-oai.bham.ac.uk/ws/portalfiles/portal/27503553/Bahr_Ennil_et_al_Minimization_of_loss_Applied_Thermal_Engineering_Accepted.pdf
- 採用式: (12)～(14)。エネルギー損失の正規化は同資料の(1)(2)を採用。

```
zeta_star = 0.04 + 0.06 (turning_deg / 100)^2
zeta_stator = (1e5 / Re_Dh)^0.25 [(1 + zeta_star)(0.993 + 0.075 b/H) - 1]
zeta_rotor  = (1e5 / Re_Dh)^0.25 [(1 + zeta_star)(0.975 + 0.075 b/H) - 1]
```

資料・版によって静翼の補正係数0.021など異なる表現があります。本版は2016年掲載式の0.075をそのまま採用し、一般的な全てのSoderberg実装と同一とは扱いません。原著の完全移植、Ainley–Mathieson損失モデル、Kacker–Okapuuモデルではありません。

本アプリで明示的に選んだ幾何・Re規約:

```
b = 入力した相関用軸方向コード
H = tip_radius - hub_radius
pitch = 2π rm / blade_count
opening = throat_ratio * pitch
Dh = 2 opening H / (opening + H)
Re_Dh = rho_out V_frame_out Dh / viscosity
turning_deg = abs(inlet_flow_angle - outlet_flow_angle)
```

この規約を付したSoderberg型の予備モデルとして使います。モデルは翼型・二次流れを合わせた集約損失で、内訳は分離しません。厚み分布、曲率、後縁、翼端隙間ごとの損失補正は未実装です。粘度は全翼列で一定の入力値です。

係数zetaは等エントロピー出口運動エネルギーを分母にするため、実際の出口速度二乗と同一視しません。

```
zeta = (h_out - h_out_is)/(V_out_is²/2)
V_out_is² = V_out²/(1-zeta)
T_out_is = T_out - [zeta/(1-zeta)] V_out²/(2cp)
p_out = pt_frame_in (T_out_is/Tt_frame)^[gamma/(gamma-1)]
```

zetaが0～1外、または等エントロピー静温が0以下なら拒否します。生の係数を黙って切り詰めません。

### 指定全圧損失係数Y

```
Y = (pt_frame_in - pt_frame_out)/(pt_frame_out - p_out)
F = (Tt_frame/T_out)^[gamma/(gamma-1)]
p_out = pt_frame_in/[F + Y(F-1)]
pt_frame_out = F p_out
```

静翼は絶対全圧、動翼は相対全圧を使います。Yは圧縮性の全圧−静圧差による定義で、rho V²/2そのものを分母にしません。動翼の絶対全圧差に対して同じ係数を適用しません。

静翼では全温、一定半径の動翼では相対全温を保存し、絶対系へ戻してEuler仕事と全温低下の一致を確認します。エントロピー生成は `-Rgas ln(pt_frame_out/pt_frame_in)` です。

## 流出角偏差

参照した公開一次実装・説明:

- https://turbo-sim.github.io/turboflow/_modules/turboflow/axial_turbine/deviation_model.html
- https://turbo-sim.github.io/turboflow/source/model_description/deviation_models.html

公開式の数学的定義を確認して独立実装しており、TurboFlowのコードや依存ライブラリを組み込んでいません。低速をM<=0.5とし、ユーザー指定の臨界参照Mach数に向かって補間します。臨界値自体を求めるチョーク解析はありません。

### Ainley–Mathieson型

`q=A_throat/A_exit`、軸方向からのゲージ角を `g=acos(q)` [deg] とします。

```
delta0 = g - [35 + (45/39)(g-40)]
x = clip((M-0.5)/(Mcrit-0.5), 0, 1)
abs(flow_angle) = g - delta0(1-x)
```

### Aungier型

```
g_tangent = 90 - g
delta0 = asin(q [1+(1-q)(g_tangent/90)^2]) - g_tangent
x = clip((M-0.5)/(Mcrit-0.5), 0, 1)
abs(flow_angle) = g - delta0(1 - 10x³ + 15x⁴ - 6x⁵)
```

公開説明ページにはdelta0の増分から `g_tangent` を引く項が抜けています。本版では公開実装との照合とq→1の極限を確認し、上記の増分形を採用しました。説明文だけを転記していません。

### 金属角＋指定偏差

`flow_angle = outlet_metal_angle + specified_deviation`。この指定偏差の定義はAM/Aungier内部のゲージ角に対する偏差とは異なります。結果表のδmetalは、全方式で `flow_angle - outlet_metal_angle` に統一しています。

## 適用状態

以下を適用条件外として表示します。収束したことを、条件内・実験精度確認済みと同一視しません。

- 入射角の絶対値が5°超。入射損失補正がないための本アプリの運用判定です。
- Soderberg型で転向120°超、出口Mach数0.8超、Re_Dhが1e4～1e7外。Re限界は本版の確認範囲で、原典の保証範囲という意味ではありません。
- AM偏差のゲージ角が40～70°外。
- 指定臨界参照Mach数に達した場合。
- 反動度が0～1外、または必要出口面積と形状の環状面積が5%以上異なる場合。
- 形状から転記した後に、参照形状・半径・翼枚数が変わった場合。

適用範囲外でも亜音速で数値的に成立すれば参考値を返します。音速以上、非正静温、未収束などは結果を返しません。

## 保存と検証の限界

設計schemaと交換bundleはversion 3。version 1/2は読込時に移行し、保存までは原本を変更しません。結果に翼列の入力、モデル名、式の出典、係数の正規化、反復回数、角度残差、相対全温収支、適用状態を保存します。管理情報とのID・版・入力ハッシュの紐付けは維持します。

数式の参照値、損失ゼロ極限、全温・Euler仕事・エントロピー、偏差の符号、損失感度、設定の保存を自動検証しました。公開タービンの実験性能・CFDによる較正、非設計点性能、背圧／固定流路の連成、チョーク、半径方向分布は未検証・未実装です。
