# 圧縮機との共通形状交換（第一段階）

2026-11-03 / アプリ0.6.1 / 共通ライブラリ0.1.0。

画面上部の「選択翼列の共通形状JSON出力」で、現在の入力から選択翼列を再生成して出力します。元の設計JSONとは別形式です。共通座標はm、回転軸Z、連続角rad。タービンの元XYZから共通XYZへの変換は `(-Z,Y,X)`、円筒角は `pi−phi` で、鏡像を避けるため回転符号も−1として明示します。

「共通形状JSONの整合性確認」は圧縮機・タービンの共通出力を読み、版・単位・有限値・ID・役割・内容SHA-256を検査します。元入力ハッシュと曲線・点数を表示します。編集中の設計、SQLite、解析結果へは反映しません。4 MiBを超えるファイルはこの画面では拒否します。

元の静翼/動翼・翼列ID・金属角基準・幾何スパン定義を保持し、A/BをPS/SSへ自動変換しません。子午面有効時には、3D・OBJと同じ配置座標を使います。子午面無効時は従来の局所円筒配置です。両者を混ぜた全段アセンブリーを生成する機能ではありません。

共通形式は生成済み標本座標です。編集可能な圧縮機の設計JSONをタービンへ取り込む、逆にタービンの翼を圧縮機の設計変数へ戻す、壁面・角度・LE/TEの計算器を入れ替える機能は未実装です。CFDや製造可否も判定しません。

共通パッケージはこのアプリ内に同梱し、親フォルダーがなくても動作します。`turbomachinery_common/VENDORED.json` は版とソースSHA-256の記録です。同梱コピーを直接改変せず、正本 `../turbomachinery_common/` から同期・検査します。共通JSONのschemaは1、既存設計JSONのschema/bundleは6のままです。

検証コマンド：既存unittestへ `test_common_exchange.py` を追加。`node test_ui.mjs` は出力・読取専用の確認・改変拒否を含みます。実ブラウザーのファイル選択や描画、外部CAD/CFDの取込は別途確認が必要です。
# 追加：子午面評価API v1（2026-11-20）

`common_meridional.wall_evaluator(design, 'hub')`（または`'casing'`）で、
有効な設計子午面の既存PCHIP/linear係数を共通形式で読み取れる。
`jet(parameter, side=None)`のパラメータは軸方向位置mで、
`parameter_kind='axial_position_m'`と明示する。圧縮機の子午面距離とは区別する。
`position_m`は軸位置・半径、`first`と`second_per_m`は軸位置による導関数、
`tangent`は単位接線、`signed_curvature_per_m`は軸から半径への回転を正とした曲率。
内部境界は`knots_m`から選び、`side='left'/'right'`を必須とする。
無効な子午面と範囲外評価は拒否する。元設計のhashを保持し、設計を変更しない。
Python開発者向けAPIで、画面・HTTP操作、SQLite、既存形状生成・1D計算への接続は変更しない。
同梱`curves.py`もSHA-256を固定する。交換schema/版は維持。

## 追加：長さ写像API v1（2026-11-20）

`common_meridional.wall_length_map(design, 'hub')`（または`'casing'`）で、
開始点から指定した絶対軸位置までの距離mを求める`distance_at(x_m)`と、
距離から絶対軸位置mに戻す`parameter_at(distance_m)`を使える。
曲線開始軸位置が負でも、その点からの距離は0 m。
`total.value_m`は全長、`total.estimated_error_m`は適応Simpson積分の推定誤差。
逆変換は`distance_residual_m`と`estimated_distance_error_m`（残差絶対値＋積分推定誤差）を返す。
`absolute_tolerance_m=1e-10`、`distance_tolerance_m=1e-8`が既定値。
元のlinear/PCHIP区間を別々に積分し、片側導関数を使う。
推定誤差は厳密な上界ではなく、丸め・目標距離自体の不確かさ・実機精度は含まない。
範囲外・速度0・精度不足・反復上限到達は拒否する。新しい`lengths.py`も同梱hashを照合する。
既存の画面・配置・翼形状・1D計算・SQLiteへ自動適用しない開発者向けAPIである。
