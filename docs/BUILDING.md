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
| `palt_keep_fullwidth` | `palt` 焼き込みを控えめにする文字（Ninter P の句読点） | `"、。，．"` |
| `palt_keep_tighten` | 上の文字に `palt` をどれだけ効かせるか。0 で全角（1000）、1 で Noto の詰め（500）、0.5 で 750 | `0.5` |
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
5. **CJK文脈記号を Noto へ** — 丸数字（①②）・ローマ数字・囲み/幾何記号や、Inter が特大に描く記号は、Inter の cmap から外して **Noto の全角版**を採用（`defer_cjk_symbols`）。Latin の約物（— … ‰ ™ 等）は Inter のまま。特大かどうかは、使う Inter のうち一番細い太さで一度だけ判定します。太さごとに判定すると、太い面だけ ‰ が Noto に回っていました。
   - **palt の焼き込み**（`cjk_tighten`）— Noto の `palt` の値を既定の字幅に入れる。Noto は wght 700 から上で `palt` に補正のルックアップを重ねるので、シェーパーと同じく全ルックアップの値を足し合わせる。
   - **半角コロンの数字センター化**（`numeric_colon`）— Inter の既定 `:` は本文用で低い位置にあり、`12:34` の `:` を数字の縦中央へ上げる字形（`colon.case`）は本来 `case`/`calt` 機能で切り替わる。だが PowerPoint はこの機能を確実には適用せず、サブセットで無エンコードの `colon.case` が落ちることもあるため、**上げた字形を既定の `:` に焼き込む**（tabular の `colon.tf` も同様）。アプリの機能対応に依存せず常に数字センターになる。
6. **マージ** — `fontTools.merge`（Inter を先に）で Latin は Inter、CJK は Noto。cmap 競合は先勝ちで Latin が Inter になる。
7. **スクリプト機能の統一** — Inter の Latin OpenType 機能（kern, liga, ss01-08, cv*, tnum, frac 等）を **CJK スクリプト（kana/hani）からも参照可能に**する。Illustrator 等は混植行を CJK スクリプトでシェーピングするため、これをしないと同一行に和文がある英字で欧文機能が無効化される（gen-interface-jp #1 の教訓）。
8. **メトリクス統一** — 行送りは Noto に合わせ（typo 880/-120、win 1160/288）、CJK が切れない 1em 行に。
9. **命名 / スタイル連結** — RIBBI（Ninter: R/B/I/BI）＋ タイポグラフィック/WWS（全9ウェイトを Ninter に）。`fsSelection` / `macStyle` / `usWeightClass` / `italicAngle` を設定。名前テーブルは再構築し空レコードを残さない。
10. **サブセット**（任意）— Noto 側の重複 Latin など到達不能グリフを削除。
11. **全角半角変換のつなぎ直し** — `fwid` `hwid` `pwid` を Inter の英数字に向け直す。マージで Noto の英数字が消えると、これらの変換が効かなくなるため。
12. **ゼロ幅グリフの追加** — U+200C、U+200D、U+FE00 から U+FE0F に空のグリフを割り当てる。絵文字の並びが Illustrator などで豆腐にならない。
13. **言語別の機能の修復** — 日本語のときも Inter のカーニングや機能が選ばれるように、言語ごとの機能一覧を整える。同じ機能の重複もここで除く。重複はサブセットで生じるので、最後に行う。Web 版は `scripts/build_web.py` がスライスごとに同じ処理を行う。

> fontforge ではなく **fontTools** に一本化しています（name table の精密制御が Ctrl+I 連結に有利、スクリプト再現性、追加インストール不要のため）。

---

## Web 版のビルドと公開

`build/` の完成フォントから、npm に公開する 2 つのパッケージ（`ninter` と `ninter-p`）を `dist/web/` に作ります。

```bash
pip install fonttools brotli
python scripts/build_variable.py   # 先に可変フォントを作る
python scripts/build_web.py
```

各スタイルを `scripts/web_slices.json` の範囲で約 125 個の WOFF2 に分割し、太さごとの CSS を作ります。可変フォントも同じ範囲で分割し、`variable.css` と `cdn/variable.css` を作ります。フォント名は `Ninter Variable` と `Ninter P Variable` で、`font-weight` は 100 から 900 の好きな値を使えます。`400.css` はファイルの相対パス、`cdn/400.css` は jsDelivr の絶対 URL を指します。最後に全ファイルを読み直し、CSS に書いた文字とファイルの中身、元の TTF の文字が一致するかを検査します。jsDelivr の上限は 1 パッケージ 150MB なので、超えたときも問題として報告します。

npm のバージョンは `ninter.config.json` の `version` から決まります。npm では同じバージョンを出し直せないので、Web 版だけを直すときは `--version 1.0.1` のように指定します。

公開は npm にログインしてから、パッケージごとに行います。

```bash
npm login
cd dist/web/ninter && npm publish
cd ../ninter-p && npm publish
```

---

## 可変フォント

太さを 100 から 900 まで滑らかに変えられる可変フォントを、静的な TTF とは別に作ります（[#2](https://github.com/ykuwai/ninter/issues/2)）。静的な TTF が今も主な配布物です。

```bash
python scripts/build_variable.py
```

9 つの太さを `build.py` の `build_face` でそのまま作り、それを親にして `fontTools.varLib` で 1 本にまとめます。出力は `build/variable/` の 4 本で、フォント名は `Ninter Variable` と `Ninter P Variable` です。静的な TTF と同時に入れても名前がぶつかりません。

- 軸の目盛りは Noto の avar と同じにしてあります。和文の多くは 100、400、900 の 3 つの親で足ります。欧文は Inter の太さの対応が一直線でないので、9 つすべてを使います。
- 字ごとに、静的な TTF との差が許容差に収まる最小の親だけを残します。全部残すと 1 本 33MB ほどになります。
- Ninter（P なし）は Noto と同じく、wght 700 から `palt` と `vpal` の補正を FeatureVariations で切り替えます。
- `build/variable/` は git に入れず、GitHub の Releases に ZIP で置きます。Web 版は `build_web.py` が同じ範囲で分割し、`variable.css` を作ります。

---

## 既知の制約 / 今後

- **縦書き** は非対応（`vhea`/`vmtx`/`BASE` を除去）。PowerPoint の横書き用途向け。
- **Latin と CJK の傾き差**（Inter 約 9.4° / CJK 5.5°）は仕様どおり。気になる場合はプレビュワーで CJK 角を上げて調整。
- Noto の一部 OpenType 機能（`vert`, `palt` 等）はマージ時に整理。基本の横組み表示は cmap 経由で問題なし。
- ファイルは 1 面あたり約 5〜6MB（CJK が主）。全 36 面で約 200MB。

## ロードマップ（今後の候補）

類似先行プロジェクト [gen-interface-jp](https://github.com/yamatoiizuka/gen-interface-jp)（Inter × Noto Sans JP, 8ウェイト・イタリック無し）の Issue/リリース履歴から得た改善候補：

- **見出し用 Display ファミリー**（Inter opsz=32 系）の追加。
- **約物半角のオプション化**（`ss09` 型スタイリスティックセット）で詰めを固定せず選択可能に。
- **縦書き** への対応。

Ninter が既に優位な点：**9ウェイト（Black 有）・イタリック対応・palt 焼き込み・Windows/PowerPoint 最適化**。

## ライセンス

Noto Sans JP（© Google）と Inter（© The Inter Project Authors）はともに **SIL Open Font License 1.1**。派生の Ninter も OFL 1.1 に従います。`sources/` の元フォントおよび各配布物のライセンスを尊重してください。

## Web サイト

`site/` はビルドの要らない静的なページで、フォントは jsDelivr から読み込みます。手元では `python3 -m http.server --directory site` で開けます。新しい版を公開したら、`site/index.html` と `site/main.js` のバージョンを合わせます。

GitHub Pages への公開は `.github/workflows/pages.yml` で行います。リポジトリの Settings で Pages の Source を GitHub Actions にしてから、Actions タブで手動で実行します。

## README 用の画像

README の画像（`docs/images/*.svg`）は、`build/` の実フォントから `scripts/build_readme_images.py` で作ります。文字は図形に変換し、背景は透明です。SVG の中に明暗それぞれの色を持たせているので、ページの色に合わせて見え方が変わります。

```bash
pip install fonttools uharfbuzz
python scripts/build_readme_images.py
```
