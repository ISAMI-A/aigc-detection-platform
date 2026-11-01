// 全局主题：深浅色模式 + 主题主色
// 颜色统一走 CSS 变量（index.css :root 默认浅色 / [data-theme="dark"] 深色覆盖），
// 本模块只负责：持久化（localStorage）+ 动态应用（改主色时重算衍生变量）。

export const DEFAULT_PRIMARY = "#1a66ff";

// 主色衍生变量名（浅色 + 自定义主色时需 JS 重算；深色下由 CSS color-mix 自动联动，
// 浅色且为默认蓝时直接使用 :root 手写值，保证与原界面视觉零差异）
const PRIMARY_KEYS = [
  "--c-primary-hover", "--c-primary-soft", "--c-primary-soft-2", "--c-primary-soft-3",
  "--c-primary-soft-4", "--c-primary-border", "--c-primary-border-2",
  "--c-primary-row", "--c-primary-row-hover", "--c-primary-ring", "--c-grad-end",
];

const STORE_KEY = "ai-theme-settings";

export function loadTheme() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "");
    if (raw && (raw.theme === "light" || raw.theme === "dark")
        && typeof raw.primary === "string" && /^#[0-9a-f]{6}$/i.test(raw.primary)) {
      return { theme: raw.theme, primary: raw.primary.toLowerCase() };
    }
  } catch (_) {}
  return { theme: "light", primary: DEFAULT_PRIMARY };
}

export function saveTheme(s) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (_) {}
}

function hex2rgb(h) {
  const v = h.replace("#", "");
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
}
// 两色按权重混合（w = 第二色的权重 0~1），返回 #rrggbb
function mixHex(a, b, w) {
  const [r1, g1, b1] = hex2rgb(a);
  const [r2, g2, b2] = hex2rgb(b);
  const f = (x, y) => Math.round(x * (1 - w) + y * w);
  const toHex = (v) => v.toString(16).padStart(2, "0");
  return `#${toHex(f(r1, r2))}${toHex(f(g1, g2))}${toHex(f(b1, b2))}`;
}
// hex 颜色 + 透明度 → rgba 字符串
function mixAlpha(hex, a) {
  const [r, g, b] = hex2rgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

// 应用主题到 <html>：data-theme 控制深浅，--c-primary 控制主色
export function applyTheme(s) {
  const root = document.documentElement;
  root.dataset.theme = s.theme;
  // 衍生变量交给 CSS 处理（深色用 color-mix 联动主色；浅色默认用 :root 手写值）
  PRIMARY_KEYS.forEach((k) => root.style.removeProperty(k));
  const p = (s.primary || DEFAULT_PRIMARY).toLowerCase();
  if (p === DEFAULT_PRIMARY) {
    root.style.removeProperty("--c-primary"); // 恢复 :root 默认蓝
    return;
  }
  root.style.setProperty("--c-primary", p);
  if (s.theme !== "dark") {
    // 浅色 + 自定义主色：:root 默认衍生值不再适用，按新主色重算（对应原 #1a66ff 系列）
    root.style.setProperty("--c-primary-hover", mixHex(p, "#ffffff", 0.15));
    root.style.setProperty("--c-primary-soft", mixHex(p, "#ffffff", 0.86));
    root.style.setProperty("--c-primary-soft-2", mixHex(p, "#ffffff", 0.88));
    root.style.setProperty("--c-primary-soft-3", mixHex(p, "#ffffff", 0.93));
    root.style.setProperty("--c-primary-soft-4", mixHex(p, "#ffffff", 0.95));
    root.style.setProperty("--c-primary-border", mixHex(p, "#ffffff", 0.6));
    root.style.setProperty("--c-primary-border-2", mixHex(p, "#ffffff", 0.78));
    root.style.setProperty("--c-primary-row", mixHex(p, "#ffffff", 0.9));
    root.style.setProperty("--c-primary-row-hover", mixHex(p, "#ffffff", 0.95));
    root.style.setProperty("--c-primary-ring", mixAlpha(p, 0.12));
    root.style.setProperty("--c-grad-end", mixHex(p, "#ffffff", 0.35));
  }
}
