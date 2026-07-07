# Ninter — 日本語イタリック対応 混植フォント

**Noto Sans JP × Inter** を合成した混植（こんしょく）フォントパックです。2つの狙いがあります。

1. **日本語に「きれいなイタリック」を。** PowerPoint などで日本語を斜体にすると 18° も傾く擬似イタリックになり不格好です。Ninter は Ctrl+I で押せる本物のイタリック面を持ち、CJK をわずか **3°**（調整可）だけ傾けて、躍動感のある自然な強調にします。
2. **欧文はもっと美しく。** アルファベット・数字・記号は **Inter** の字形を使い、和文は Noto Sans JP。イタリック時、Latin は Inter 本来のイタリック（-9.4°）、CJK は 3° スラント。

Regular / Bold / Italic / Bold Italic は1つの `Ninter` ファミリー（RIBBI）にまとまり、9ウェイト全体も `Ninter` タイポグラフィックファミリー（WWS）で連結。これにより **Ctrl+I / Ctrl+B が旧来(GDI)・最新(DirectWrite)両方の Office で機能** します。

---

## クイックスタート

```bash
# 1) 元フォント（OFL）を取得
python scripts/download_sources.py

# 2) フルウェイト（Thin〜Black × Italic = 18面）をビルド
python build.py

# 3) プレビュワーで微調整（再ビルド不要でライブ確認）
python scripts/preview.py        # ブラウザが開きます

# 4) Windows にインストール（管理者不要・ユーザー単位）
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
#   アンインストール: 同コマンドに -Uninstall
```

インストール後、Word / PowerPoint を再起動してフォント **「Ninter」** を選択。日本語を選んで **Ctrl+I** で自然な斜体、**Ctrl+B** で太字。

---

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
| `cjk_tighten` | Noto の `palt`（プロポーショナル字幅）を既定字幅に焼き込む割合 0–1。かな・約物が詰まり、漢字は全角維持。約物は半角化 | `1.0` |
| `cjk_tracking` | 全 CJK グリフを一律に詰める追加量（units、+で詰め） | `0` |
| `weights` | ビルドするウェイト | `100..900` |
| `opsz` | Inter の光学サイズ軸 | `14` |
| `subset` | 未使用グリフを削ってファイル縮小 | `true` |

**Inter を和文に合わせて細くする**：Inter は Noto より太く見えるので、`inter_weights` で和文ウェイトごとに Inter の wght を下げます（例 `"400": 300`）。プレビュワーの「欧文ウェイト（独立調整）」で各ウェイトの最適値を探し「この対応を記録」→ config にコピー。値は連続値（小数可, 100–900）。

CLI で個別上書きも可能: `python build.py --weights 400 700 --slant 5.5 --inter-weight-offset -100`

---

## 仕組み（build.py）

各ウェイト・各スタイルについて:

1. **インスタンス化** — Inter VF（Roman/Italic）と Noto Sans JP VF を目的ウェイトで静的化。
2. **upm 統一** — Inter を 2048→1000 に縮小（Noto に合わせる）。縮小後、Inter の cap/x-height は Noto とほぼ一致（727/546 vs 733/543）。
3. **Inter 位置合わせ** — `inter_yshift` / `inter_scale` を適用。
4. **CJK スラント** — イタリック面のみ Noto を `slant_angle` でシアー（アウトライン＋合成グリフのオフセットを変換、送り幅は保持）。
5. **マージ** — `fontTools.merge`（Inter を先に）で Latin は Inter、CJK は Noto。cmap 競合は先勝ちで Latin が Inter になる。
6. **メトリクス統一** — 行送りは Noto に合わせ（typo 880/-120、win 1160/288）、CJK が切れない 1em 行に。
7. **命名 / スタイル連結** — RIBBI（Ninter: R/B/I/BI）＋ タイポグラフィック/WWS（全9ウェイトを Ninter に）。`fsSelection` / `macStyle` / `usWeightClass` / `italicAngle` を設定。
8. **サブセット**（任意）— Noto 側の重複 Latin など到達不能グリフを削除。

> fontforge ではなく **fontTools** に一本化しています（name table の精密制御が Ctrl+I 連結に有利、スクリプト再現性、追加インストール不要のため）。

---

## 既知の制約 / 今後

- **縦書き** は非対応（`vhea`/`vmtx`/`BASE` を除去）。PowerPoint の横書き用途向け。
- **Latin と CJK の傾き差**（Inter -9.4° / CJK 3°）は仕様どおり。気になる場合はプレビュワーで CJK 角を上げて調整。
- Noto の一部 OpenType 機能（`vert`, `palt` 等）はマージ時に整理。基本の横組み表示は cmap 経由で問題なし。
- ファイルは 1 面あたり約 5〜6MB（CJK が主）。全 18 面で約 100MB。

## ライセンス

Noto Sans JP（© Google）と Inter（© The Inter Project Authors）はともに **SIL Open Font License 1.1**。派生の Ninter も OFL 1.1 に従います。`sources/` の元フォントおよび各配布物のライセンスを尊重してください。
