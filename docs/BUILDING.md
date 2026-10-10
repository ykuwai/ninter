# Ninter のビルドと調整（開発者向け）

フォントを使うだけなら、この文書は読まなくて大丈夫です。インストール方法は [README](../README.md) にあります。ここではフォントを自分で作り直したい人向けに、ビルド手順と設定、仕組みをまとめています。

## ビルドの流れ

```bash
# 1) 元フォント（OFL）を取得
python scripts/download_sources.py

# 2) フルウェイト（Thin〜Black × Italic = 36面）をビルド
python build.py

# 3) プレビュワーで微調整（再ビルド不要でライブ確認）
python scripts/preview.py

# 4) Windows にインストール
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

## プレビュワーの使い方（微調整 → 焼き込み）

`python scripts/preview.py` で開くツールは、**元フォントからブラウザ上で混植を合成**するので、値をいじると即座に反映されます（フォントを作り直す必要なし）。

- **傾斜角（CJK）** — 日本語イタリックのシアー角。Latin は Inter 本来のイタリックのまま。
- **ベースライン上下 / スケール / トラッキング** — Inter を和文に対してどう置くかの位置合わせ。Inter はやや背が高く見えるので、ここで視覚的に詰めます（単位は 1000upm 基準の font units）。
- 「**config をコピー**」→ `ninter.config.json` に貼り付け、または「**build cmd をコピー**」→ そのままビルド。

決まったら焼き込み:

```bash
python build.py --slant 3 --inter-yshift -8 --inter-scale 1.0
# もしくは ninter.config.json を編集して: python build.py
```

比較ペインは `build/` の実フォント（400/700）を読み込むので、焼き込み後に再読み込みするとライブ調整と一致するか確認できます。

---

## 設定 `ninter.config.json`

| キー | 意味 | 既定 |
|---|---|---|
| `slant_angle` | CJK イタリックの傾斜角（度） | `5.5` |
| `inter_yshift` | Inter 字形の上下移動（units@1000upm、+で上） | `-45` |
| `inter_scale` | Inter 字形の拡大率（プレビュワーは 1.6 まで） | `1.0` |
| `inter_tracking` | （プレビュー用の目安）Latin 字間 | `0` |
| `inter_weights` | **和文ウェイト→Interウェイトの対応表**。Inter は同じ公称ウェイトでも太く見えるため、各 Noto ウェイトに合う Inter の wght を個別指定 | 恒等 |
| `inter_weight_offset` | `inter_weights` に無いウェイトへ一律加算（例 `-100` で Inter を細く） | `0` |
| `numeric_colon` | 半角コロン `:` を Inter の数字センター字形（`colon.case`）で焼き込む。`12:34` の `:` が数字の縦中央に来る。`false` で低い本文コロンのまま | `true` |
| `cjk_tighten` | Noto の `palt`（プロポーショナル字幅）を既定字幅に焼き込む割合 0–1。かな・約物が詰まり、漢字は全角維持。約物は半角化 | `1.0` |
| `palt_keep_fullwidth` | `palt` 焼き込みから除外し全角のまま残す文字（Ninter P の句読点を全角に保つ） | `"、。，．"` |
| `cjk_tracking` | 全 CJK グリフを一律に詰める追加量（units、+で詰め） | `0` |
| `variants` | 生成するファミリー群。各要素が `family` と `cjk_tighten` を上書き（既定は Ninter=ベタ / Ninter P=詰め の2種） | 2種 |
| `weights` | ビルドするウェイト | `100..900` |
| `opsz` | Inter の光学サイズ軸 | `14` |
| `subset` | 未使用グリフを削ってファイル縮小 | `true` |

**Inter を和文に合わせて細くする**：Inter は Noto より太く見えるので、`inter_weights` で和文ウェイトごとに Inter の wght を下げます（例 `"400": 300`）。プレビュワーの「欧文ウェイト（独立調整）」で各ウェイトの最適値を探し「この対応を記録」→ config にコピー。値は連続値（小数可, 100–900）。

CLI で個別上書きも可能: `python build.py --weights 400 700 --slant 5.5 --inter-weight-offset -100`

### ビルドの並列化

36面を**マルチプロセスで並列ビルド**します（`ProcessPoolExecutor`）。各面のインスタンス化・マージ・サブセットはほぼ純Python＝GIL拘束のため、ThreadPool では速くならず**プロセス並列が正解**です。ワーカー数は**空きRAMから自動決定**（各ワーカーが Noto 全字で約0.6GB使うため、コア数ではなくメモリが律速）。

```bash
python build.py            # 自動（cores-2 と 空きRAM/0.7 の小さい方, 上限8）
python build.py --jobs 8   # 明示指定（RAMに余裕があれば増やす）
python build.py --jobs 1   # 逐次（デバッグ用）
```

---

## 仕組み（build.py）

各ウェイト・各スタイルについて:

1. **インスタンス化** — Inter VF（Roman/Italic）と Noto Sans JP VF を目的ウェイトで静的化。
2. **upm 統一** — Inter を 2048→1000 に縮小（Noto に合わせる）。縮小後、Inter の cap/x-height は Noto とほぼ一致（727/546 vs 733/543）。
3. **Inter 位置合わせ** — `inter_yshift` / `inter_scale` を適用。
4. **CJK スラント** — イタリック面のみ Noto を `slant_angle` でシアー（アウトライン＋合成グリフのオフセットを変換、送り幅は保持）。
5. **CJK文脈記号を Noto へ** — 丸数字（①②）・ローマ数字・囲み/幾何記号や、Inter が特大に描く記号は、Inter の cmap から外して **Noto の全角版**を採用（`defer_cjk_symbols`）。Latin の約物（— … ‰ ™ 等）は Inter のまま。
   - **半角コロンの数字センター化**（`numeric_colon`）— Inter の既定 `:` は本文用で低い位置にあり、`12:34` の `:` を数字の縦中央へ上げる字形（`colon.case`）は本来 `case`/`calt` 機能で切り替わる。だが PowerPoint はこの機能を確実には適用せず、サブセットで無エンコードの `colon.case` が落ちることもあるため、**上げた字形を既定の `:` に焼き込む**（tabular の `colon.tf` も同様）。アプリの機能対応に依存せず常に数字センターになる。
6. **マージ** — `fontTools.merge`（Inter を先に）で Latin は Inter、CJK は Noto。cmap 競合は先勝ちで Latin が Inter になる。
7. **スクリプト機能の統一** — Inter の Latin OpenType 機能（kern, liga, ss01-08, cv*, tnum, frac 等）を **CJK スクリプト（kana/hani）からも参照可能に**する。Illustrator 等は混植行を CJK スクリプトでシェーピングするため、これをしないと同一行に和文がある英字で欧文機能が無効化される（gen-interface-jp #1 の教訓）。
8. **メトリクス統一** — 行送りは Noto に合わせ（typo 880/-120、win 1160/288）、CJK が切れない 1em 行に。
9. **命名 / スタイル連結** — RIBBI（Ninter: R/B/I/BI）＋ タイポグラフィック/WWS（全9ウェイトを Ninter に）。`fsSelection` / `macStyle` / `usWeightClass` / `italicAngle` を設定。名前テーブルは再構築し空レコードを残さない。
10. **サブセット**（任意）— Noto 側の重複 Latin など到達不能グリフを削除。

> fontforge ではなく **fontTools** に一本化しています（name table の精密制御が Ctrl+I 連結に有利、スクリプト再現性、追加インストール不要のため）。

---

## 既知の制約 / 今後

- **縦書き** は非対応（`vhea`/`vmtx`/`BASE` を除去）。PowerPoint の横書き用途向け。
- **Latin と CJK の傾き差**（Inter -9.4° / CJK 3°）は仕様どおり。気になる場合はプレビュワーで CJK 角を上げて調整。
- Noto の一部 OpenType 機能（`vert`, `palt` 等）はマージ時に整理。基本の横組み表示は cmap 経由で問題なし。
- ファイルは 1 面あたり約 5〜6MB（CJK が主）。全 18 面で約 100MB。

## ロードマップ（今後の候補）

類似先行プロジェクト [gen-interface-jp](https://github.com/yamatoiizuka/gen-interface-jp)（Inter × Noto Sans JP, 8ウェイト・イタリック無し）の Issue/リリース履歴から得た改善候補：

- **異体字セレクタ/ZWJ のゼロ幅グリフ**（U+200C/200D, FE00–FE0F）を追加し、絵文字隣接の豆腐を回避。
- **全角/半角変換（fwid/hwid）** など、合成でリネームされたグリフに対する feature 再ターゲットの検証。
- **小書き仮名（っゃょ）** が palt 焼き込み後に詰まりすぎていないか確認・個別補正。
- **Web 配信（WOFF2 + unicode-range サブセット + CSS 自動生成）**、npm/CDN 配布。
- **見出し用 Display ファミリー**（Inter opsz=32 系）の追加。
- **約物半角のオプション化**（`ss09` 型スタイリスティックセット）で詰めを固定せず選択可能に。
- ビルド並列化する場合は ThreadPoolExecutor（プロセス spawn のデッドロック回避）。

Ninter が既に優位な点：**9ウェイト（Black 有）・イタリック対応・palt 焼き込み・Windows/PowerPoint 最適化**。

## ライセンス

Noto Sans JP（© Google）と Inter（© The Inter Project Authors）はともに **SIL Open Font License 1.1**。派生の Ninter も OFL 1.1 に従います。`sources/` の元フォントおよび各配布物のライセンスを尊重してください。
