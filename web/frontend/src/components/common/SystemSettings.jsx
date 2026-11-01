import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { cleanupTmp, fetchModelStatus, clearDetectAll, fetchDetectStats } from "../../api/detectApi.js";
import { smartApi } from "../../api/smartApi.js";
import { rsApi } from "../../api/rsApi.js";
import { fetchFaceStats, resetFace } from "../../api/faceApi.js";
import { loadTheme, saveTheme, applyTheme } from "../../theme.js";
import i18n, { saveLang } from "../../i18n/index.js";

// 主题主色色板
const PALETTE = [
  { name: "科技蓝", color: "#1a66ff" },
  { name: "翡翠绿", color: "#16a36a" },
  { name: "葡萄紫", color: "#7c4dff" },
  { name: "活力橙", color: "#f07830" },
  { name: "玫红色", color: "#e64c7c" },
  { name: "青蓝色", color: "#0e9bb5" },
];

// 系统设置（全局）：外观主题 + 语言切换 + 一键清理系统历史内容
export default function SystemSettings({ onClose }) {
  const { t } = useTranslation();
  const [usage, setUsage] = useState({ bytes: 0, results: 0, uploads: 0 });
  const [verify, setVerify] = useState(null);
  const [rs, setRs] = useState(null);
  const [face, setFace] = useState(null);
  const [gpuStatus, setGpuStatus] = useState(null); // 模型管理器状态（GPU 显存 + 模型占用）
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState(() => loadTheme());
  const [lang, setLang] = useState(i18n.language);

  useEffect(() => {
    refreshDetectStats();
    refreshVerifyStats();
    refreshRsStats();
    refreshFaceStats();
  }, []);

  // GPU 显存占用轮询（5s 一次），供用户判断"显存是否已被模型常驻占用"
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await fetchModelStatus();
        if (alive) setGpuStatus(d);
      } catch (_) {
        if (alive) setGpuStatus(null);
      }
    };
    load();
    const timer = setInterval(load, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  async function refreshDetectStats() {
    try {
      setUsage(await fetchDetectStats());
    } catch (_) {
      setUsage({ bytes: 0, results: 0, uploads: 0 });
    }
  }
  async function refreshVerifyStats() {
    try {
      setVerify(await smartApi.stats());
    } catch (_) {
      setVerify(null);
    }
  }
  async function refreshRsStats() {
    try {
      setRs(await rsApi.stats());
    } catch (e) {
      setRs(null);
    }
  }
  async function refreshFaceStats() {
    try {
      setFace(await fetchFaceStats());
    } catch (e) {
      setFace(null);
    }
  }

  function handleLangChange(lang) {
    i18n.changeLanguage(lang);
    saveLang(lang);
    setLang(lang);
  }

  async function clearAll() {
    if (!confirm(t('settings.cleanConfirm'))) return;
    setBusy(true);
    let msg = "";
    try {
      try {
        const r = await cleanupTmp();
        msg += t('settings.backendCleaned', { count: r.cleaned });
      } catch (e) { msg += t('settings.backendCleanFail', { msg: e.message }); }
      try {
        await clearDetectAll();
        msg += t('settings.cacheCleared');
      } catch (e) { msg += t('settings.cacheCleanFail', { msg: e.message }); }
      try {
        await smartApi.reset();
        window.dispatchEvent(new Event("smart-verify-cleared"));
        msg += t('settings.verifyCleared');
      } catch (e) { msg += t('settings.verifyCleanFail', { msg: e.message }); }
      try {
        await rsApi.reset();
        window.dispatchEvent(new Event("rsverify-cleared"));
        msg += t('settings.rsCleared');
      } catch (e) { msg += t('settings.rsCleanFail', { msg: e.message }); }
      try {
        await resetFace();
        msg += t('settings.faceCleared');
      } catch (e) { msg += t('settings.faceCleanFail', { msg: e.message }); }
    } finally {
      setBusy(false);
    }
    setUsage({ bytes: 0, results: 0, uploads: 0 });
    window.dispatchEvent(new Event("cache-cleared"));
    // 清理后重新拉取各后端统计（应为 0 条），避免残留"无（后端未连接或为空）"误导显示
    refreshDetectStats();
    refreshVerifyStats();
    refreshRsStats();
    refreshFaceStats();
    alert(msg);
  }

  function updateTheme(patch) {
    const next = { ...theme, ...patch };
    setTheme(next);
    saveTheme(next);
    applyTheme(next);
  }
  const isCurColor = (c) => theme.primary.toLowerCase() === c.toLowerCase();

  const gpu = gpuStatus?.gpu;
  const usedPct = gpu ? Math.min(100, Math.round((gpu.used_mb / gpu.total_mb) * 100)) : 0;

  const langOptions = [
    { value: "zh-CN", label: t('settings.langZh') },
    { value: "en", label: t('settings.langEn') },
  ];

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t('settings.title')}</span>
          <button className="btn small" onClick={onClose}>✕</button>
        </div>

        {/* GPU 显存占用（实时轮询，5s 刷新） */}
        <div className="settings-section">
          <div className="settings-label">{t('settings.gpuTitle')}</div>
          {gpu ? (
            <div className="gpu-status">
              <div className="gpu-bar">
                <div className={`gpu-fill${usedPct > 85 ? " danger" : ""}`} style={{ width: `${usedPct}%` }} />
              </div>
              <div className="gpu-text">
                {t('settings.gpuUsage', {
                  used: (gpu.used_mb / 1024).toFixed(1),
                  total: (gpu.total_mb / 1024).toFixed(1),
                  free: (gpu.free_mb / 1024).toFixed(1),
                })}
              </div>
              {(gpuStatus.models || []).length > 0 && (
                <div className="gpu-models">
                  {(gpuStatus.models || []).map((m) => (
                    <span key={m.name} className="smart-tag tag-info" title={m.type}>
                      {m.name}（{m.est_gb}GB）
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="theme-hint">{t('settings.gpuUnavailable')}</div>
          )}
        </div>

        {/* 外观 · 主题 */}
        <div className="settings-section">
          <div className="settings-label">{t('settings.appearance')}</div>
          <div className="theme-row">
            <span className="theme-sub">{t('settings.themeMode')}</span>
            <div className="theme-mode">
              <button className={theme.theme === "light" ? "on" : ""}
                      onClick={() => updateTheme({ theme: "light" })}>☀ {t('settings.light')}</button>
              <button className={theme.theme === "dark" ? "on" : ""}
                      onClick={() => updateTheme({ theme: "dark" })}>🌙 {t('settings.dark')}</button>
            </div>
          </div>
          <div className="theme-row">
            <span className="theme-sub">{t('settings.themeColor')}</span>
            <div className="theme-palette">
              {PALETTE.map((p) => (
                <button key={p.color} type="button" title={p.name}
                        className={`swatch ${isCurColor(p.color) ? "on" : ""}`}
                        style={{ background: p.color }}
                        onClick={() => updateTheme({ primary: p.color })} />
              ))}
              <label className={`swatch custom ${PALETTE.every((p) => !isCurColor(p.color)) ? "on" : ""}`}
                     title={t('settings.customColor')}>
                <input type="color" value={theme.primary}
                       onChange={(e) => updateTheme({ primary: e.target.value })} />
              </label>
            </div>
          </div>
          <div className="theme-hint">{t('settings.themeHint')}</div>
        </div>

        {/* 系统语言 */}
        <div className="settings-section">
          <div className="settings-label">{t('settings.language')}</div>
          <div className="language-row">
            {langOptions.map((opt) => (
              <button key={opt.value}
                      className={lang === opt.value ? "lang-btn active" : "lang-btn"}
                      onClick={() => handleLangChange(opt.value)}>
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* 历史内容清理 */}
        <div className="settings-section">
          <div className="settings-label">{t('settings.historyClean')}</div>

          <div className="settings-sub">{t('settings.detectSection')}</div>
          <div className="cache-info">
            {t('settings.cacheUsage', {
              mb: ((usage.bytes || 0) / 1024 / 1024).toFixed(1),
              results: usage.results ?? 0,
              uploads: usage.uploads ?? 0,
            })}
          </div>

          <div className="settings-sub">{t('settings.verifySection')}</div>
          <div className="cache-info">
            {verify
              ? t('settings.verifyStats', {
                  pairs: verify.pairs,
                  done: verify.done,
                  images: verify.images,
                  mb: (verify.bytes / 1024 / 1024).toFixed(1),
                })
              : t('settings.verifyEmpty')}
          </div>

          <div className="settings-sub">{t('settings.rsSection')}</div>
          <div className="cache-info">
            {rs
              ? t('settings.rsStats', {
                  records: rs.records,
                  mb: (rs.bytes / 1024 / 1024).toFixed(1),
                })
              : t('settings.rsEmpty')}
          </div>

          <div className="settings-sub">{t('settings.faceSection')}</div>
          <div className="cache-info">
            {face
              ? t('settings.faceStats', {
                  uploads: face.uploads,
                  results: face.results,
                  persons: face.library?.persons ?? 0,
                  mb: ((face.bytes || 0) / 1024 / 1024).toFixed(1),
                })
              : t('settings.faceEmpty')}
          </div>

          <div className="settings-divider" />
          <div className="cache-info">
            {t('settings.totalUsage', {
              mb: (((usage.bytes || 0) + (verify?.bytes || 0) + (rs?.bytes || 0)
                + (face?.bytes || 0)) / 1024 / 1024).toFixed(1),
            })}
          </div>
          <button className="btn" disabled={busy} onClick={clearAll}>
            {busy ? t('settings.cleaning') : t('settings.cleanAll')}
          </button>
        </div>

        <div className="settings-foot">{t('settings.moreSoon')}</div>
      </div>
    </div>
  );
}
