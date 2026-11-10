const CDN = "https://cdn.jsdelivr.net/npm";
// Both families load as variable fonts (index.html), so any weight from 100 to 900 works.
const FAMILIES = { ninter: "Ninter Variable", "ninter-p": "Ninter P Variable" };
const WEIGHTS = [100, 200, 300, 400, 500, 600, 700, 800, 900];

const $ = (selector) => document.querySelector(selector);

/* Light and dark */

const root = document.documentElement;
const darkQuery = matchMedia("(prefers-color-scheme: dark)");
try {
  const saved = localStorage.getItem("theme");
  if (saved === "light" || saved === "dark") root.dataset.theme = saved;
} catch {}

$("#theme").addEventListener("click", () => {
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : darkQuery.matches;
  root.dataset.theme = dark ? "light" : "dark";
  try {
    localStorage.setItem("theme", root.dataset.theme);
  } catch {}
});

/* Hero */

const hero = $(".hero");
const heroText = document.querySelectorAll(".hero-claim, .wordmark, .tagline");
const heroWeight = $("#hero-weight");
const heroValue = $("#hero-weight-value");

function setHeroWeight(weight) {
  heroWeight.value = weight;
  heroValue.textContent = weight;
  heroText.forEach((el) => (el.style.fontWeight = weight));
}

heroWeight.addEventListener("input", () => setHeroWeight(heroWeight.value));
$("#hero-italic").addEventListener("change", (event) => {
  hero.dataset.italic = event.target.checked;
  $(".tilt-label").textContent = event.target.checked ? "5.5°" : "0°";
});

// Sweep once, smoothly, from thin to black once the hero text has loaded.
async function introSweep() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const sample = document.querySelectorAll(".hero-claim, .wordmark, .tagline");
  await document.fonts.load(`italic 900 1em "Ninter P Variable"`, [...sample].map((el) => el.textContent).join(""));
  const duration = 1100;
  const start = performance.now();
  await new Promise((resolve) => {
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      setHeroWeight(Math.round(100 + 800 * eased));
      if (t < 1) requestAnimationFrame(step);
      else resolve();
    };
    requestAnimationFrame(step);
  });
}
introSweep();

/* Plain Inter + Noto Sans JP against Ninter */

const mixRows = $("#mix-rows");
$("#mix-weight").addEventListener("input", (event) => {
  mixRows.style.setProperty("--w", event.target.value);
  $("#mix-weight-value").textContent = event.target.value;
});
$("#mix-italic").addEventListener("change", (event) => {
  mixRows.style.setProperty("--s", event.target.checked ? "italic" : "normal");
});

/* Italic comparison */

const ANGLES = { upright: "0", faux: "18", ninter: "5.5" };
const stage = $(".stage");
const gauge = $(".gauge");

stage.querySelectorAll(".segments button").forEach((button) => {
  button.addEventListener("click", () => {
    const { mode } = button.dataset;
    stage.dataset.mode = mode;
    stage.querySelectorAll(".segments button").forEach((b) => b.setAttribute("aria-pressed", b === button));
    gauge.style.setProperty("--angle", `${ANGLES[mode]}deg`);
    $(".gauge-value").textContent = `${ANGLES[mode]}°`;
  });
});

/* Weight ladder */

$("#ladder").innerHTML = WEIGHTS.map(
  (w) => `<div class="rung" style="font-weight:${w}"><span>和A</span><em>和A</em><small>${w}</small></div>`,
).join("");

/* Slides: the thumbnails are live copies of the slides */

const slides = [...document.querySelectorAll(".screen .slide")];
const thumbs = $("#thumbs");

function copyOf(slide) {
  const copy = slide.cloneNode(true);
  copy.hidden = false;
  copy.querySelectorAll("[contenteditable]").forEach((el) => el.removeAttribute("contenteditable"));
  return copy;
}

slides.forEach((slide, index) => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "thumb";
  button.setAttribute("aria-label", `スライド ${index + 1}`);
  button.setAttribute("aria-pressed", index === 0);
  button.innerHTML = `<span class="thumb-no" aria-hidden="true">${index + 1}</span>`;
  button.append(copyOf(slide));
  button.addEventListener("click", () => {
    slides.forEach((s, i) => (s.hidden = i !== index));
    thumbs.querySelectorAll(".thumb").forEach((b, i) => b.setAttribute("aria-pressed", i === index));
  });
  thumbs.append(button);
  slide.addEventListener("input", () => button.querySelector(".slide").replaceWith(copyOf(slide)));
});

/* Tester */

const state = { pkg: "ninter-p", weight: 700, italic: true, size: 60 };
const text = $("#tester-text");
const code = $("#tester-code");

function renderTester() {
  const family = FAMILIES[state.pkg];
  text.style.fontFamily = `"${family}", sans-serif`;
  text.style.fontWeight = state.weight;
  text.style.fontStyle = state.italic ? "italic" : "normal";
  text.style.fontSize = `min(${state.size}px, ${(state.size / 11).toFixed(1)}vw + 18px)`;
  $("#tester-weight-value").textContent = state.weight;
  $("#tester-size-value").textContent = state.size;
  const italicLine = state.italic ? "\n  font-style: italic;" : "";
  code.textContent =
    `<link rel="stylesheet" href="${CDN}/${state.pkg}@1/cdn/variable.css">\n\n` +
    `<style>\n.title {\n  font-family: "${family}", sans-serif;\n  font-weight: ${state.weight};${italicLine}\n}\n</style>`;
}

document.querySelectorAll("[data-family]").forEach((button) => {
  button.addEventListener("click", () => {
    state.pkg = button.dataset.family;
    document.querySelectorAll("[data-family]").forEach((b) => b.setAttribute("aria-pressed", b === button));
    renderTester();
  });
});

$("#tester-weight").addEventListener("input", (event) => {
  state.weight = Number(event.target.value);
  renderTester();
});
$("#tester-size").addEventListener("input", (event) => {
  state.size = Number(event.target.value);
  renderTester();
});
$("#tester-italic").addEventListener("change", (event) => {
  state.italic = event.target.checked;
  renderTester();
});

$("#copy").addEventListener("click", async (event) => {
  try {
    await navigator.clipboard.writeText(code.textContent);
    event.target.textContent = "コピーしました";
  } catch {
    getSelection().selectAllChildren(code);
    event.target.textContent = "選択しました";
  }
  setTimeout(() => {
    event.target.textContent = "コピー";
  }, 1600);
});

renderTester();
