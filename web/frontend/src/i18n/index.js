import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zhCN from './zh-CN.json';
import en from './en.json';

const LANG_KEY = 'app_lang';

// 从 localStorage 恢复语言偏好，默认为中文简体
function getSavedLang() {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === 'en' || saved === 'zh-CN') return saved;
  } catch (_) { /* localStorage 不可用时忽略 */ }
  return 'zh-CN';
}

export function saveLang(lang) {
  try { localStorage.setItem(LANG_KEY, lang); } catch (_) {}
}

i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zhCN },
    en: { translation: en },
  },
  lng: getSavedLang(),
  fallbackLng: 'zh-CN',
  interpolation: { escapeValue: false },
});

export default i18n;
