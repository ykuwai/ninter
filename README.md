<p align="center"><img src="docs/images/hero.svg" alt="Ninter 斜体に対応した日本語フォント" width="720"></p>

<p align="center">
  <a href="https://www.npmjs.com/package/ninter-p"><img src="https://img.shields.io/npm/v/ninter-p" alt="npm"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-OFL--1.1-blue.svg" alt="License OFL-1.1"></a>
</p>

<p align="center">Noto Sans JP と Inter を合わせて作った、斜体に対応した日本語フォントです。<br><a href="https://ykuwai.github.io/ninter/">サイトで太さと斜体を試せます</a></p>

<p align="center"><img src="docs/images/compare.svg" alt="疑似イタリックと Ninter の斜体の比較" width="720"></p>

- 日本語は 5.5° の傾き
- 欧文は Inter 本来の斜体
- 9 つの太さすべてに斜体
- 無料で商用利用もできる

<p align="center"><img src="docs/images/weights.svg" alt="Thin から Black まで 9 つの太さ" width="720"></p>

| ファミリー | 字の並び |
|---|---|
| **Ninter P** | かなと括弧が詰まる。ふだんはこちら |
| **Ninter** | 全角でそろう。字を升目のように並べたいときに |

## Web で使う

CSS を読み込んで、フォント名を指定します。

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ninter-p@1/cdn/400.css">
```

```css
body { font-family: "Ninter P", sans-serif; }
```

Ninter を使うときは、パッケージ名を `ninter`、フォント名を `"Ninter"` にします。

### 太さと斜体

太さは `100.css` から `900.css` まであります。斜体も同じファイルに入っていて、使ったときだけ読み込まれます。

複数の太さは 1 行で読み込めます。

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/combine/npm/ninter-p@1/cdn/400.css,npm/ninter-p@1/cdn/700.css">
```

本番では `ninter-p@1.0.2` のようにバージョンを固定できます。`all.css` は CSS だけで約 1.7MB あるので、通常は使いません。

### 太さを自由に選ぶ（可変フォント）

`variable.css` を読み込むと、100 から 900 までの好きな太さを使えます。フォント名は `"Ninter P Variable"` です。3 つ以上の太さを使うページでは、こちらのほうが軽くなります。

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ninter-p@1/cdn/variable.css">
```

```css
body { font-family: "Ninter P Variable", sans-serif; font-weight: 450; }
```

Ninter のときは、パッケージ名を `ninter`、フォント名を `"Ninter Variable"` にします。

### npm

Vite や Next.js などのバンドラで使えます。

```bash
npm install ninter-p
```

```js
import "ninter-p/400.css";
// 可変フォントなら
import "ninter-p/variable.css";
```

| 読み込み方 | 使うファイル |
|---|---|
| CDN | `cdn/*.css` |
| npm と自前配信 | 直下の `*.css` |

### Tailwind CSS v4

```css
@theme { --font-sans: "Ninter P", sans-serif; }
```

## パソコンにインストールする

Word や PowerPoint で使うときの手順です。GitHub の Code ボタンから Download ZIP を選び、展開したフォルダで次のコマンドを実行します。

| | コマンド |
|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -File scripts/install.ps1` |
| Mac | `cp build/*.ttf ~/Library/Fonts/` |

Windows でアンインストールするときは、最後に `-Uninstall` をつけます。

インストールしたらアプリを開き直してください。Ctrl+I（Mac は Command+I）で斜体、Ctrl+B で太字になります。動作確認は Windows の Word と PowerPoint で行っています。

可変フォント（`Ninter P Variable` と `Ninter Variable`）は、[Releases](https://github.com/ykuwai/ninter/releases/latest) の `NinterVariable` の ZIP に入っています。Figma やデザインのアプリで太さを細かく選びたいとき向けです。Word や PowerPoint では、上の 9 つの太さのフォントをおすすめします。

## ライセンス

SIL Open Font License 1.1 で公開しています。ビルドや調整の方法は [docs/BUILDING.md](docs/BUILDING.md) を見てください。
