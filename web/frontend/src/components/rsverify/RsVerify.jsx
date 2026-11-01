// 遥感变化核验功能页（Remote Sensing Verify）
// 对接后端 FastAPI 子应用 /rsverify/api，算法能力由 Remote_sensing/web_bridge.py 子进程提供
// 交互约定：提示全部用组件内 toast / 确认用组件内弹窗，不用浏览器 alert/confirm
// 预设平台配置存数据库（rs_presets）：可添加多个、点击激活、参数与 key 独立保存、自由切换互不影响
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { rsApi } from "../../api/rsApi.js";
import UploadPanel from "../verify/UploadPanel.jsx";

// API Key 脱敏显示：只露首尾几个字符，中间打码，方便辨认当前是哪个 key
function maskKey(k) {
  if (!k) return "";
  const s = String(k);
  if (s.length <= 10) return `${s.slice(0, 2)}••••${s.slice(-2)}`;
  return `${s.slice(0, 6)}••••${s.slice(-4)}`;
}

// 本地 Ollama 模型列表缓存（localStorage）：点"从服务器获取模型"后的列表刷新页面不丢，
// 再次打开设置直接显示；需要最新列表时再点一次按钮强制刷新即可。
const LOCAL_MODELS_KEY = "rsverify_local_models";
function readLocalModelsCache() {
  try {
    const arr = JSON.parse(localStorage.getItem(LOCAL_MODELS_KEY) || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch (_) { return []; }
}
function writeLocalModelsCache(models) {
  try { localStorage.setItem(LOCAL_MODELS_KEY, JSON.stringify(models)); } catch (_) {}
}

export default function RsVerify() {
  const { t } = useTranslation();

  // 双面板上传（参考点位核验：拖拽排序/选择勾选/本地缓存刷新不丢）
  const beforeRef = useRef(null);
  const afterRef = useRef(null);
  const [beforeCount, setBeforeCount] = useState(0);
  const [afterCount, setAfterCount] = useState(0);
  const [beforeSel, setBeforeSel] = useState(0);
  const [afterSel, setAfterSel] = useState(0);
  const [pairMode, setPairMode] = useState("sequential"); // sequential 顺序匹配 / select 选择比对

  // 四乱核验单图上传
  const singleRef = useRef(null);
  const [singleCount, setSingleCount] = useState(0);

  // 场景与状态（从 localStorage 恢复上次选的场景）
  const [scenario, setScenario] = useState(() => {
    try { return localStorage.getItem("rsverify_scenario") || "detect"; } catch (_) { return "detect"; }
  });
  const switchScenario = useCallback((s) => {
    setScenario(s);
    try { localStorage.setItem("rsverify_scenario", s); } catch (_) {}
  }, []);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState(null); // {done, total, current}
  const [swapping, setSwapping] = useState(false); // 两侧面板一键交换动画中
  const [records, setRecords] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);

  // 弹窗状态
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);
  const [confirm, setConfirm] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [viewImageId, setViewImageId] = useState(null);
  const [viewFull, setViewFull] = useState(false); // 标注图弹窗全窗口展示
  const [exporting, setExporting] = useState(false);
  const [rerunning, setRerunning] = useState(false); // 重新核验中（进度提示）
  const [detailRecord, setDetailRecord] = useState(null); // classify 详情弹窗

  const showToast = useCallback((msg, type = "info") => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ msg, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  // 页面加载：结果 + 后端恢复当前设备已上传图片 + 系统设置全局清理事件联动
  useEffect(() => {
    loadResults();
    restoreUploads();
    const onCleared = () => {
      beforeRef.current?.reset(); afterRef.current?.reset(); singleRef.current?.reset();
      setRecords([]); setSelectedIds([]);
      showToast(t('rsverify.dataCleared'));
    };
    window.addEventListener("rsverify-cleared", onCleared);
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
      window.removeEventListener("rsverify-cleared", onCleared);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 场景切换时刷新该场景的上传图片列表（场景隔离）
  useEffect(() => {
    restoreUploads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario]);

  // 从后端恢复当前设备当前场景已上传图片到面板（先清空旧文件，再恢复）
  async function restoreUploads() {
    try {
      // 先清空所有面板，避免前一个场景的文件残留
      beforeRef.current?.reset();
      afterRef.current?.reset();
      singleRef.current?.reset();
      const res = await rsApi.getUploadedImages(scenario);
      const items = res.items || [];
      beforeRef.current?.restoreImages(items.filter((r) => r.position === "before"));
      afterRef.current?.restoreImages(items.filter((r) => r.position === "after"));
      singleRef.current?.restoreImages(items.filter((r) => r.position === "single"));
    } catch (_) { /* 后端未连接时忽略 */ }
  }

  // 清空面板：后端级联删除已上传图片及引用它的结果记录（标注图/rec 目录一并清理）
  async function handleClearUploads(side, list) {
    if (!list || list.length === 0) return;
    for (const f of list) {
      if (f.id) { try { await rsApi.deleteImage(f.id); } catch (_) {} }
    }
    (side === "before" ? beforeRef : side === "single" ? singleRef : afterRef).current?.removeFiles(list);
    await loadResults(true); // 级联删除可能清掉了结果记录，静默刷新结果列表
  }

  async function loadResults(silent) {
    try {
      const res = await rsApi.results();
      setRecords(res.records || []);
      if (!silent) showToast(t('rsverify.loadDone', { n: res.records?.length || 0 }));
    } catch (e) {
      console.error("加载结果失败", e);
      if (!silent) showToast(t('rsverify.resultsLoadFail', { msg: e.message }), "error");
    }
  }

  // 匹配：顺序匹配=列表顺序两两配对；选择比对=按点击编号（1,2,3...）顺序配对
  function buildPairs() {
    const b = beforeRef.current?.getFiles() || [];
    const a = afterRef.current?.getFiles() || [];
    if (pairMode === "select") {
      const bl = b.filter((f) => f.selected).sort((x, y) => (x.selOrder || 0) - (y.selOrder || 0));
      const al = a.filter((f) => f.selected).sort((x, y) => (x.selOrder || 0) - (y.selOrder || 0));
      const n = Math.min(bl.length, al.length);
      return bl.slice(0, n).map((x, i) => ({ before: x, after: al[i] }));
    }
    const n = Math.min(b.length, a.length);
    return b.slice(0, n).map((x, i) => ({ before: x, after: a[i] }));
  }

  const canAnalyze = useMemo(() => {
    if (scenario === "classify") return singleCount > 0;
    if (beforeCount === 0 || afterCount === 0) return false;
    if (pairMode === "select") return beforeSel > 0 && afterSel > 0;
    return true;
  }, [scenario, singleCount, beforeCount, afterCount, beforeSel, afterSel, pairMode]);

  const selectedPairCount = pairMode === "select"
    ? Math.min(beforeSel, afterSel) : Math.min(beforeCount, afterCount);

  // ===== 一键交换两侧上传文件（带动画：面板先向对方滑出淡出，换数据后滑回淡入） =====
  async function swapFiles() {
    if (swapping) return;
    const b = beforeRef.current?.getFiles() || [];
    const a = afterRef.current?.getFiles() || [];
    if (b.length === 0 && a.length === 0) return;
    setSwapping(true);
    await new Promise((r) => setTimeout(r, 260)); // 等待滑出动画（与 CSS transition 时长一致）
    beforeRef.current?.replaceFiles(a);
    afterRef.current?.replaceFiles(b);
    setSwapping(false); // 移除动画类 → 面板从偏移位置滑回原位（内容已是对方）
  }

  // ===== 开始核验：classify 单图 / detect-verify 双图（批量循环 + 进度条） =====
  async function doAnalyze() {
    if (scenario === "classify") return doAnalyzeSingle();
    const pairs = buildPairs();
    if (pairs.length === 0) { showToast(t('rsverify.needBoth'), "warn"); return; }
    // 开始前校验当前激活预设配置：未配置模型/地址/Key 时直接失败并说明原因（不进入检测流程）
    try {
      const cfg = await rsApi.getSettings();
      const p = cfg.preset;
      if (!p) { showToast(t('rsverify.needConfig'), "error"); return; }
      if (p.api === "local") {
        if (!p.local_model_name) { showToast(t('rsverify.needModel'), "error"); return; }
      } else {
        if (!p.base_url) { showToast(t('rsverify.needBaseUrl'), "error"); return; }
        if (!p.model_name) { showToast(t('rsverify.needModel'), "error"); return; }
        if (!p.api_key) { showToast(t('rsverify.needApiKey'), "error"); return; }
      }
    } catch (e) {
      showToast(t('rsverify.configFail', { msg: e.message }), "error");
      return;
    }
    // 跳过已核验过的图片对（同场景 + 同名图片已有结果），避免重复点击重复落盘/重复核验
    const doneKey = new Set(records.map((r) => `${r.scenario}|${r.before_file}|${r.after_file}`));
    const todo = pairs.filter((p) => !doneKey.has(`${scenario}|${p.before.name}|${p.after.name}`));
    const skipped = pairs.length - todo.length;
    if (todo.length === 0) {
      showToast(t('rsverify.skipAllVerified', { n: pairs.length }), "warn");
      return;
    }
    setAnalyzing(true);
    setProgress({ done: 0, total: todo.length, current: skipped > 0 ? t('rsverify.skipSome', { n: skipped }) : "" });
    let ok = 0;
    for (let i = 0; i < todo.length; i++) {
      const p = todo[i];
      if (!p.before.id || !p.after.id) {
        showToast(t('rsverify.uploadPending', { name: p.before.name || p.after.name }), "warn");
        continue;
      }
      setProgress({ done: i, total: todo.length, current: `${p.before.name} → ${p.after.name}` });
      try {
        const record = await rsApi.analyze(p.before.id, p.after.id, scenario);
        setRecords((prev) => [record, ...prev]);
        ok += 1;
      } catch (e) {
        showToast(t('rsverify.analyzeFail', { msg: e.message }), "error");
      }
    }
    setProgress(null);
    setAnalyzing(false);
    if (ok === 0) {
      // 全部失败：错误提示说明原因，不显示"完成"
      showToast(t('rsverify.analyzeAllFail', { pairs: todo.length }), "error");
    } else {
      showToast(t('rsverify.analyzeDone', { n: ok }), "success");
    }
  }

  // ===== 四乱核验（单图）：逐张上传+分析（批量循环 + 进度条） =====
  async function doAnalyzeSingle() {
    const files = singleRef.current?.getFiles() || [];
    if (files.length === 0) { showToast(t('rsverify.needSingle'), "warn"); return; }
    // 开始前校验当前激活预设配置（与双图核验一致）
    try {
      const cfg = await rsApi.getSettings();
      const p = cfg.preset;
      if (!p) { showToast(t('rsverify.needConfig'), "error"); return; }
      if (p.api === "local") {
        if (!p.local_model_name) { showToast(t('rsverify.needModel'), "error"); return; }
      } else {
        if (!p.base_url) { showToast(t('rsverify.needBaseUrl'), "error"); return; }
        if (!p.model_name) { showToast(t('rsverify.needModel'), "error"); return; }
        if (!p.api_key) { showToast(t('rsverify.needApiKey'), "error"); return; }
      }
    } catch (e) {
      showToast(t('rsverify.configFail', { msg: e.message }), "error");
      return;
    }
    // 跳过已核验过的图片（同场景 + 同名已有结果）
    const doneKey = new Set(records.filter((r) => r.scenario === "classify").map((r) => `${r.scenario}|${r.before_file}`));
    const todo = files.filter((f) => !doneKey.has(`classify|${f.name}`));
    const skipped = files.length - todo.length;
    if (todo.length === 0) {
      showToast(t('rsverify.skipAllVerified', { n: files.length }), "warn");
      return;
    }
    setAnalyzing(true);
    setProgress({ done: 0, total: todo.length, current: skipped > 0 ? t('rsverify.skipSome', { n: skipped }) : "" });
    let ok = 0;
    for (let i = 0; i < todo.length; i++) {
      const f = todo[i];
      if (!f.id) {
        showToast(t('rsverify.uploadPending', { name: f.name }), "warn");
        continue;
      }
      setProgress({ done: i, total: todo.length, current: f.name });
      try {
        const record = await rsApi.analyzeSingle(f.id);
        setRecords((prev) => [record, ...prev]);
        ok += 1;
      } catch (e) {
        showToast(t('rsverify.analyzeFail', { msg: e.message }), "error");
      }
    }
    setProgress(null);
    setAnalyzing(false);
    if (ok === 0) {
      showToast(t('rsverify.analyzeAllFail', { pairs: todo.length }), "error");
    } else {
      showToast(t('rsverify.analyzeDone', { n: ok }), "success");
    }
  }

  // ===== 导出 =====
  async function doExport() {
    const ids = selectedIds.length > 0 ? selectedIds : null; // 空=全部
    if (!ids && records.length === 0) { showToast(t('rsverify.noData'), "error"); return; }
    setExporting(true);
    try {
      const r = await rsApi.exportExcel(ids);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = t('rsverify.exportFile');
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast(t('rsverify.exportSuccess', { n: ids ? ids.length : records.length }), "success");
    } catch (e) {
      showToast(t('rsverify.exportFail', { msg: e.message }), "error");
    } finally {
      setExporting(false);
    }
  }

  // ===== 重新核验（用原图重新分析并覆盖该记录） =====
  function handleRerun(record) {
    setConfirm({
      title: t('rsverify.rerunTitle'),
      body: t('rsverify.rerunConfirm'),
      okText: t('common.confirm'),
      onOk: async () => {
        setConfirm(null);
        setRerunning(true);
        try {
          const rec = await rsApi.rerun(record.id);
          setRecords((prev) => prev.map((r) => (r.id === rec.id ? rec : r)));
          showToast(t('rsverify.rerunDone'), "success");
        } catch (e) {
          showToast(t('rsverify.rerunFail', { msg: e.message }), "error");
        } finally {
          setRerunning(false);
        }
      },
    });
  }

  // ===== 删除 =====
  async function handleDeleteOne(record) {
    setConfirm({
      title: t('common.delete'),
      body: t('rsverify.confirmDelete', { n: 1 }),
      okText: t('common.delete'),
      onOk: async () => {
        setConfirm(null);
        try {
          await rsApi.deleteResult(record.id);
          setRecords((prev) => prev.filter((r) => r.id !== record.id));
          setSelectedIds((prev) => prev.filter((x) => x !== record.id));
          showToast(t('rsverify.deleteDone'), "success");
        } catch (e) {
          showToast(t('rsverify.deleteFail', { msg: e.message }), "error");
        }
      },
    });
  }

  async function handleBatchDelete() {
    const ids = selectedIds.length > 0 ? selectedIds : null; // 空=全部
    setConfirm({
      title: t('common.delete'),
      body: ids ? t('rsverify.confirmDelete', { n: ids.length }) : t('rsverify.confirmClearAll'),
      okText: t('common.delete'),
      onOk: async () => {
        setConfirm(null);
        try {
          await rsApi.deleteBatch(ids || []);
          setSelectedIds([]);
          await loadResults(true);
          showToast(t('rsverify.deleteDone'), "success");
        } catch (e) {
          showToast(t('rsverify.deleteFail', { msg: e.message }), "error");
        }
      },
    });
  }

  function toggleSelect(id) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  const isClassify = scenario === "classify";
  const filteredRecords = isClassify
    ? records.filter((r) => r.scenario === "classify")
    : records.filter((r) => r.scenario !== "classify");

  return (
    <div className="rs-page">
      {/* 页面头：标题 + 右上角圆形设置按钮 */}
      <div className="rs-page-head">
        <h2 className="rs-page-title">{t('rsverify.title')}</h2>
        <button className="rs-settings-btn" title={t('rsverify.settingsTitle')}
                onClick={() => setShowSettings(true)}>⚙</button>
      </div>
      <p className="rs-page-desc">{t('rsverify.uploadHint')}</p>

      {/* 匹配方式切换（四乱核验单图无需配对，隐藏） */}
      {scenario !== "classify" && (
      <div className="mode-select">
        <button className={`mode-btn ${pairMode === "sequential" ? "on" : ""}`}
                onClick={() => setPairMode("sequential")}>{t('rsverify.pairSequential')}</button>
        <button className={`mode-btn ${pairMode === "select" ? "on" : ""}`}
                onClick={() => setPairMode("select")}>{t('rsverify.pairSelect')}</button>
      </div>
      )}

      {/* 上传区：四乱核验为单面板，detect/verify 为双面板（中间圆形按钮一键交换两侧） */}
      <div className={`upload-section${swapping ? " swapping" : ""}`}>
        {scenario === "classify" ? (
          <div className="upload-panel-wrap">
            <UploadPanel ref={singleRef} title={t('rsverify.singleLabel')}
                         imageUrlFn={rsApi.uploadImageUrl}
                         onFilesChanged={(list) => setSingleCount(list.length)}
                         onUploadFile={async (raw) => { const r = await rsApi.uploadSingle(raw, "single", scenario); return r.image; }}
                         onNotify={showToast}
                         onClearFiles={(list) => handleClearUploads("single", list)} />
          </div>
        ) : (
          <>
            <div className="upload-panel-wrap">
              <UploadPanel ref={beforeRef} title={t('rsverify.beforeLabel')}
                           showCheckbox={pairMode === "select"}
                           imageUrlFn={rsApi.uploadImageUrl}
                           onFilesChanged={(list) => { setBeforeCount(list.length); setBeforeSel(list.filter((f) => f.selected).length); }}
                           onUploadFile={async (raw) => { const r = await rsApi.uploadSingle(raw, "before", scenario); return r.image; }}
                           onNotify={showToast}
                           onClearFiles={(list) => handleClearUploads("before", list)} />
            </div>
            <button className={`rs-swap-btn${swapping ? " spin" : ""}`} title={t('rsverify.swapTitle')}
                    onClick={swapFiles}>⇄</button>
            <div className="upload-panel-wrap">
              <UploadPanel ref={afterRef} title={t('rsverify.afterLabel')}
                           showCheckbox={pairMode === "select"}
                           imageUrlFn={rsApi.uploadImageUrl}
                           onFilesChanged={(list) => { setAfterCount(list.length); setAfterSel(list.filter((f) => f.selected).length); }}
                           onUploadFile={async (raw) => { const r = await rsApi.uploadSingle(raw, "after", scenario); return r.image; }}
                           onNotify={showToast}
                           onClearFiles={(list) => handleClearUploads("after", list)} />
            </div>
          </>
        )}
      </div>

      {/* 场景选择 */}
      <div className="rs-scenario">
        <span className="rs-scenario-label">{t('rsverify.scenarioLabel')}</span>
        <div className="rs-scenario-opts">
          <button className={`rs-scenario-btn ${scenario === "detect" ? "on" : ""}`}
                  onClick={() => switchScenario("detect")}>
            <span className="rs-scenario-name">{t('rsverify.scenarioDetect')}</span>
            <span className="rs-scenario-desc">{t('rsverify.scenarioDetectDesc')}</span>
          </button>
          <button className={`rs-scenario-btn ${scenario === "verify" ? "on" : ""}`}
                  onClick={() => switchScenario("verify")}>
            <span className="rs-scenario-name">{t('rsverify.scenarioVerify')}</span>
            <span className="rs-scenario-desc">{t('rsverify.scenarioVerifyDesc')}</span>
          </button>
          <button className={`rs-scenario-btn ${scenario === "classify" ? "on" : ""}`}
                  onClick={() => switchScenario("classify")}>
            <span className="rs-scenario-name">{t('rsverify.scenarioClassify')}</span>
            <span className="rs-scenario-desc">{t('rsverify.scenarioClassifyDesc')}</span>
          </button>
        </div>
      </div>

      {/* 操作栏 */}
      <div className="action-bar">
        <button className="btn primary rs-analyze-btn" disabled={analyzing || !canAnalyze}
                onClick={doAnalyze}>
          {analyzing ? t('rsverify.analyzing') : (
            // 四乱核验或顺序匹配固定"开始核验"；选择比对模式显示"核验选中 (N)"
            scenario === "classify" || pairMode !== "select" || selectedPairCount === 0
              ? t('rsverify.analyze')
              : t('rsverify.verifySelected', { n: selectedPairCount })
          )}
        </button>
      </div>

      {/* 结果区（常驻显示表格，无数据时空态行提示） */}
      <div className="rs-results">
        <div className="batch-actions">
          <span className="rs-results-title">{t('rsverify.resultTitle', { n: filteredRecords.length })}</span>
          <button className="btn" disabled={exporting || filteredRecords.length === 0} onClick={doExport}>
            {selectedIds.length > 0 ? t('rsverify.exportSelected', { n: selectedIds.length }) : t('rsverify.exportAll')}
          </button>
          <button className="btn btn-del-solid" disabled={filteredRecords.length === 0} onClick={handleBatchDelete}>
            {selectedIds.length > 0 ? t('rsverify.deleteSelected', { n: selectedIds.length }) : t('rsverify.clearAll')}
          </button>
        </div>

          <div className="smart-table-wrap">
            <table className="smart-table rs-table">
              <thead>
                <tr>
                  <th className="th-center" style={{ width: 36 }}>
                    <input type="checkbox"
                           checked={selectedIds.length === filteredRecords.length && filteredRecords.length > 0}
                           onChange={() => setSelectedIds(selectedIds.length === filteredRecords.length ? [] : filteredRecords.map((r) => r.id))} />
                  </th>
                  <th style={{ width: 56 }}>{t('rsverify.colNo')}</th>
                  <th style={{ width: 120 }}>{t('rsverify.colScenario')}</th>
                  <th style={{ width: 110 }}>{t('rsverify.colModel')}</th>
                  <th>{t('rsverify.colFiles')}</th>
                  {isClassify ? (
                    <>
                      <th style={{ width: 110 }}>{t('rsverify.colMajor')}</th>
                      <th style={{ width: 120 }}>{t('rsverify.colSpecific')}</th>
                    </>
                  ) : (
                    <>
                      <th>{t('rsverify.colConclusion')}</th>
                      <th style={{ width: 90 }}>{t('rsverify.colConfidence')}</th>
                    </>
                  )}
                  <th style={{ width: 150 }}>{t('rsverify.colTime')}</th>
                  <th style={{ width: 110 }}>{isClassify ? t('rsverify.colResult') : t('rsverify.colAnnotated')}</th>
                  <th style={{ width: isClassify ? 180 : 140 }} className="th-center">{t('common.action')}</th>
                </tr>
              </thead>
              <tbody>
                {filteredRecords.map((r, idx) => (
                  <tr key={r.id} className={selectedIds.includes(r.id) ? "row-checked" : ""}
                      onDoubleClick={(e) => {
                        const td = e.target.closest("td");
                        const ci = td ? [...td.parentElement.children].indexOf(td) : -1;
                        if (ci === 0 || ci === (isClassify ? 9 : 9)) return;
                        toggleSelect(r.id);
                      }}>
                    <td className="check-cell"
                        onClick={(e) => { if (e.target.tagName !== "INPUT") toggleSelect(r.id); }}>
                      <input type="checkbox" checked={selectedIds.includes(r.id)}
                             onChange={() => toggleSelect(r.id)} />
                    </td>
                    <td>{idx + 1}</td>
                    <td className="cell-scenario">
                      <span className="smart-tag tag-info">
                        {t(r.scenario === "detect" ? 'rsverify.scenarioDetect' : r.scenario === "verify" ? 'rsverify.scenarioVerify' : 'rsverify.scenarioClassify')}
                      </span>
                    </td>
                    <td className="cell-model" title={r.model_used}>{r.model_used || "—"}</td>
                    <td className="cell-name" title={isClassify ? r.before_file : `${r.before_file} → ${r.after_file}`}>
                      {isClassify ? r.before_file : `${r.before_file} → ${r.after_file}`}
                    </td>
                    {isClassify ? (
                      <>
                        <td className="cell-conclusion" title={r.result?.major_category || ""}>{r.result?.major_category || "—"}</td>
                        <td title={r.result?.specific_category || ""}>{r.result?.specific_category || "—"}</td>
                      </>
                    ) : (
                      <>
                        <td className="cell-conclusion" title={r.conclusion}>{r.conclusion || "—"}</td>
                        <td>{r.confidence || "—"}</td>
                      </>
                    )}
                    <td>{r.created_at}</td>
                    <td className="thumb-cell">
                      {r.annotated_image && (
                        <span className="thumb-zoom"
                              style={{ "--zoom-src": `url("${rsApi.imageUrl(r.id)}")` }}>
                          <img src={rsApi.imageUrl(r.id)} alt="annotated"
                               onClick={() => { setViewFull(false); setViewImageId(r.id); }} />
                        </span>
                      )}
                    </td>
                    <td className="cell-ops">
                      <button className="btn" title={t('rsverify.rerunTitle')} disabled={analyzing}
                              onClick={() => handleRerun(r)}>↻</button>
                      {isClassify && (
                        <button className="btn" title={t('rsverify.detail')}
                                onClick={() => setDetailRecord(r)}>📋</button>
                      )}
                      <button className="btn" title={t('common.delete')}
                              onClick={() => handleDeleteOne(r)}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      {/* 功能页面设置弹窗 */}
      {showSettings && (
        <SettingsModal onClose={() => setShowSettings(false)} onNotify={showToast} />
      )}

      {/* 标注图查看（右上角可切换全窗口展示；classify 场景标题为"结果图"） */}
      {viewImageId && (
        <div className="modal-mask" onClick={() => setViewImageId(null)}>
          <div className={`modal rs-view-modal${viewFull ? " full" : ""}`} onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{t(isClassify ? 'rsverify.colResult' : 'rsverify.colAnnotated')}</span>
              <div className="modal-head-actions">
                <span className="modal-close rs-view-full" title={viewFull ? t('rsverify.viewRestore') : t('rsverify.viewFullscreen')}
                      onClick={() => setViewFull((v) => !v)}>{viewFull ? "⤡" : "⛶"}</span>
                <span className="modal-close" onClick={() => setViewImageId(null)}>{t('common.close')}</span>
              </div>
            </div>
            <img className="rs-view-img" src={rsApi.imageUrl(viewImageId)} alt="annotated" />
          </div>
        </div>
      )}

      {/* 四乱核验详情弹窗 */}
      {detailRecord && (
        <div className="modal-mask" onClick={() => setDetailRecord(null)}>
          <div className="modal rs-detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{t('rsverify.detailTitle')}</span>
              <span className="modal-close" onClick={() => setDetailRecord(null)}>{t('common.close')}</span>
            </div>
            <div className="rs-detail-body">
              {detailRecord.annotated_image && (
                <div className="rs-detail-img-wrap">
                  <img src={rsApi.imageUrl(detailRecord.id)} alt="result"
                       onClick={() => { setViewFull(false); setViewImageId(detailRecord.id); setDetailRecord(null); }} />
                </div>
              )}
              <div className="rs-detail-info">
                <div className="rs-detail-row">
                  <span className="rs-detail-label">{t('rsverify.colFiles')}</span>
                  <span className="rs-detail-value">{detailRecord.before_file}</span>
                </div>
                <div className="rs-detail-row">
                  <span className="rs-detail-label">{t('rsverify.colMajor')}</span>
                  <span className="rs-detail-value">{detailRecord.result?.major_category || "—"}</span>
                </div>
                <div className="rs-detail-row">
                  <span className="rs-detail-label">{t('rsverify.colSpecific')}</span>
                  <span className="rs-detail-value">{detailRecord.result?.specific_category || "—"}</span>
                </div>
                <div className="rs-detail-row">
                  <span className="rs-detail-label">{t('rsverify.colFeatureDesc')}</span>
                  <span className="rs-detail-value">{detailRecord.result?.feature_description || "—"}</span>
                </div>
                <div className="rs-detail-row">
                  <span className="rs-detail-label">{t('rsverify.colModel')}</span>
                  <span className="rs-detail-value">{detailRecord.model_used || "—"}</span>
                </div>
                <div className="rs-detail-row">
                  <span className="rs-detail-label">{t('rsverify.colTime')}</span>
                  <span className="rs-detail-value">{detailRecord.created_at}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 核验进度弹窗（批量逐对，显示当前对与进度） */}
      {analyzing && progress && (
        <div className="modal-mask">
          <div className="modal smart-progress-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><span className="modal-title">{t('rsverify.analyzing')}</span></div>
            <div className="smart-progress-current">{progress.current || t('rsverify.preparing')}</div>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progress.total ? Math.round((progress.done / progress.total) * 100) : 0}%` }} />
            </div>
            <div className="progress-text">
              {t('rsverify.progressPairs', {
                done: progress.done, total: progress.total,
                pct: progress.total ? Math.round((progress.done / progress.total) * 100) : 0,
              })}
            </div>
          </div>
        </div>
      )}

      {/* 导出等待 */}
      {exporting && (
        <div className="modal-mask">
          <div className="modal smart-progress-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><span className="modal-title">{t('rsverify.exporting')}</span></div>
            <div className="smart-progress-current">{t('rsverify.exportingDesc')}</div>
            <div className="progress-bar indeterminate"><div className="progress-fill indeterminate" /></div>
          </div>
        </div>
      )}

      {/* 重新核验中（阻塞等待，显示进度提示） */}
      {rerunning && (
        <div className="modal-mask">
          <div className="modal smart-progress-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><span className="modal-title">{t('rsverify.rerunTitle')}</span></div>
            <div className="smart-progress-current">{t('rsverify.rerunning')}</div>
            <div className="progress-bar indeterminate"><div className="progress-fill indeterminate" /></div>
          </div>
        </div>
      )}

      {/* 确认弹窗 */}
      {confirm && (
        <div className="modal-mask" onClick={() => setConfirm(null)}>
          <div className="modal smart-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><span className="modal-title">{confirm.title}</span></div>
            <div className="confirm-body">{confirm.body}</div>
            <div className="modal-foot">
              <button className="btn" onClick={() => setConfirm(null)}>{t('common.cancel')}</button>
              <button className="btn primary" onClick={confirm.onOk}>{confirm.okText || t('common.confirm')}</button>
            </div>
          </div>
        </div>
      )}

      {/* 轻提示 */}
      {toast && createPortal(
        <div className={`toast toast-${toast.type}`}>
          {toast.type === "success" ? "✓ " : toast.type === "error" ? "✕ " : toast.type === "warn" ? "! " : ""}
          {toast.msg}
        </div>,
        document.body
      )}
    </div>
  );
}

// ==================== 功能页面设置弹窗 ====================
// 预设平台配置存数据库：可添加多个、点击激活、参数与 key 独立保存、自由切换互不影响；
// 模型名称由用户手动输入，保存到预设的 model_name 字段。
function SettingsModal({ onClose, onNotify }) {
  const { t } = useTranslation();
  const [form, setForm] = useState(null);          // 当前激活预设参数（null=加载中）
  const [presets, setPresets] = useState([]);      // 预设列表（数据库）
  const [activeId, setActiveId] = useState(null);  // 当前激活预设 id
  const [commonModels, setCommonModels] = useState([]); // 静态兜底模型（添加模型表单用）
  const [localModels, setLocalModels] = useState(readLocalModelsCache); // 本地 Ollama 模型（localStorage 缓存）
  const [showAdd, setShowAdd] = useState(false);   // 添加模型表单
  const [confirm2, setConfirm2] = useState(null);  // 删除预设确认（组件内弹窗）
  const [saving, setSaving] = useState(false);
  const [fetchingLocal, setFetchingLocal] = useState(false); // 本地模型列表获取中

  useEffect(() => {
    loadSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 加载当前激活预设 + 预设列表 + 该预设地址的模型（隔离）
  async function loadSettings() {
    try {
      const d = await rsApi.getSettings();
      setPresets(d.presets || []);
      setActiveId(d.preset?.id ?? null);
      setCommonModels(d.common_models || []);
      const p = d.preset;
      setForm(p ? {
        api: p.api || "openai",
        base_url: p.base_url || "",
        api_key: p.api_key || "",
        model_name: p.model_name || "",
        local_model_name: p.local_model_name || "",
        max_tokens: String(p.max_tokens ?? 2000),
        temperature: String(p.temperature ?? 0.2),
      } : { api: "openai", base_url: "", api_key: "", model_name: "", local_model_name: "", max_tokens: "2000", temperature: "0.2" });
    } catch (e) {
      onNotify(t('rsverify.loadFail', { msg: e.message }), "error");
      onClose();
    }
  }

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })); }

  // 点击预设：激活 + 回显该预设参数（key 独立，不串台）
  async function selectPreset(id) {
    try {
      const p = await rsApi.activatePreset(id);
      setActiveId(p.id);
      setForm({
        api: p.api || "openai",
        base_url: p.base_url || "",
        api_key: p.api_key || "",
        model_name: p.model_name || "",
        local_model_name: p.local_model_name || "",
        max_tokens: String(p.max_tokens ?? 2000),
        temperature: String(p.temperature ?? 0.2),
      });
      // 刷新预设列表
      const d = await rsApi.getSettings();
      setPresets(d.presets || []);
      setActiveId(d.preset?.id ?? null);
    } catch (e) {
      onNotify(t('rsverify.activateFail', { msg: e.message }), "error");
    }
  }

  // 删除预设（删除激活预设后后端自动激活剩余第一个）
  function removePreset(id) {
    const p = presets.find((x) => x.id === id);
    setConfirm2({
      title: t('rsverify.deletePresetTitle'),
      body: t('rsverify.deletePresetDesc', { name: p?.name || "" }),
      okText: t('common.delete'),
      onOk: async () => {
        setConfirm2(null);
        try {
          await rsApi.deletePreset(id);
          await loadSettings();
          onNotify(t('rsverify.deleteDone'), "success");
        } catch (e) {
          onNotify(t('rsverify.deleteFail', { msg: e.message }), "error");
        }
      },
    });
  }

  // 保存：更新当前激活预设（参数/key 独立保存，不影响其他预设）
  // 保存成功后仅轻量刷新预设/模型下拉，不重建表单，避免整窗重渲染导致按钮闪烁
  async function save() {
    if (!form) return;
    setSaving(true);
    try {
      await rsApi.saveSettings({
        api: form.api,
        base_url: form.base_url,
        api_key: form.api_key,
        model_name: form.model_name,
        local_model_name: form.local_model_name,
        max_tokens: parseInt(form.max_tokens, 10) || 2000,
        temperature: parseFloat(form.temperature) || 0.2,
      });
      onNotify(t('rsverify.saved'), "success");
      try {
        const d = await rsApi.getSettings();
        setPresets(d.presets || []);
        setActiveId(d.preset?.id ?? null);
        setCommonModels(d.common_models || []);
      } catch (_) { /* 列表刷新失败不影响保存结果 */ }
    } catch (e) {
      onNotify(t('rsverify.saveFail', { msg: e.message }), "error");
    } finally {
      setSaving(false);
    }
  }

  // 手动刷新本地 Ollama 模型列表（本地模型页"获取模型"按钮，避免打开设置/保存时实时请求拖慢）
  async function fetchLocalModels() {
    setFetchingLocal(true);
    try {
      const res = await rsApi.fetchLocalModels();
      const models = res.models || [];
      setLocalModels(models);
      writeLocalModelsCache(models);
    } catch (e) {
      onNotify(t('rsverify.fetchModelsFail', { msg: e.message }), "error");
    } finally {
      setFetchingLocal(false);
    }
  }

  // 重置：放弃未保存修改，恢复该预设数据库保存值
  function resetForm() {
    loadSettings();
    onNotify(t('rsverify.resetDone'), "info");
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal settings-modal rs-settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t('rsverify.settingsTitle')}</span>
          <span className="modal-close" onClick={onClose}>{t('common.close')}</span>
        </div>

        {!form ? (
          <div className="loading-wrapper">{t('common.loading')}</div>
        ) : (
          <>
            {/* API 类型切换：本地部署模型 / 云端 API */}
            <div className="settings-section">
              <div className="settings-label">{t('rsverify.apiType')}</div>
              <div className="mode-select">
                <button className={`mode-btn ${form.api === "local" ? "on" : ""}`}
                        onClick={() => { set("api", "local"); set("local_model_name", form.local_model_name || commonModels[0] || ""); }}>{t('rsverify.apiTypeLocal')}</button>
                <button className={`mode-btn ${form.api === "openai" ? "on" : ""}`}
                        onClick={() => set("api", "openai")}>{t('rsverify.apiTypeCloud')}</button>
              </div>
            </div>

            {form.api === "local" ? (
              /* 本地部署模式：点"获取模型"加载 Ollama 模型到下拉切换，地址/Key/参数自动读取 config.yaml */
              <>
                <div className="settings-section">
                  <div className="settings-label">{t('rsverify.localModelName')}</div>
                  <div className="rs-model-row">
                    <LocalModelDropdown value={form.local_model_name}
                                        onChange={(v) => set("local_model_name", v)}
                                        models={localModels} onFetch={fetchLocalModels} />
                    <button className="btn" disabled={fetchingLocal} onClick={fetchLocalModels}>
                      {fetchingLocal ? t('common.loading') : t('rsverify.localFetchModels')}
                    </button>
                  </div>
                  <div className="theme-hint">{t('rsverify.localModelCount', { n: localModels.length })}</div>
                </div>
                <div className="modal-foot" style={{ marginTop: 14 }}>
                  <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
                  <button className="btn primary" disabled={saving || !activeId} onClick={save}>
                    {saving ? t('common.loading') : t('rsverify.save')}
                  </button>
                </div>
              </>
            ) : (
              <>
                {/* 预设平台（数据库存储，点击激活切换；可滚动容器，多时滚轮查看） */}
                <div className="settings-section">
                  <div className="settings-label">{t('rsverify.presetModel')}</div>
                  <div className="rs-preset-scroll">
                    <div className="rs-preset-list">
                      {presets.length === 0 && <div className="rs-preset-empty">{t('rsverify.noPresets')}</div>}
                      {presets.map((p) => (
                        <span key={p.id} className={`rs-preset-chip ${p.id === activeId ? "on" : ""}`}>
                          <button className="rs-preset-name" title={t('rsverify.activatePreset')}
                                  onClick={() => selectPreset(p.id)}>
                            {p.name}
                            {p.id === activeId && <em>{t('rsverify.activeBadge')}</em>}
                          </button>
                          <span className="rs-preset-del" title={t('common.delete')}
                                onClick={(e) => { e.stopPropagation(); removePreset(p.id); }}>✕</span>
                        </span>
                      ))}
                      <button className="rs-add-preset" onClick={() => setShowAdd(true)}>＋ {t('rsverify.addPreset')}</button>
                    </div>
                  </div>
                  <div className="theme-hint">{t('rsverify.addHint')}</div>
                </div>

                {/* 当前预设配置（可修改 / 保存 / 重置恢复） */}
                <div className="settings-section">
                  <div className="settings-label">{t('rsverify.baseUrl')}</div>
                  <input className="smart-note" style={{ width: "100%" }} placeholder="https://api.openai.com/v1"
                         value={form.base_url} onChange={(e) => set("base_url", e.target.value)} />
                </div>
                <div className="settings-section">
                  <div className="settings-label">{t('rsverify.apiKey')}</div>
                  {/* Key 恒脱敏显示首尾，聚焦也不显示明文；需修改时全选删除后重新输入 */}
                  <input className="smart-note" style={{ width: "100%" }} type="text"
                         placeholder="sk-..." spellCheck={false}
                         value={maskKey(form.api_key)}
                         onChange={(e) => set("api_key", e.target.value)} />
                  <div className="theme-hint">{t('rsverify.apiKeyHint')}</div>
                </div>
                <div className="settings-section">
                  <div className="settings-label">{t('rsverify.modelName')}</div>
                  <input className="smart-note" style={{ width: "100%" }} list="rs-common-model-list"
                         placeholder={t('rsverify.modelNamePlaceholder') || "gpt-4o / qwen-vl-plus / ..."}
                         value={form.model_name} onChange={(e) => set("model_name", e.target.value)} />
                  <datalist id="rs-common-model-list">
                    {commonModels.map((m) => <option key={m} value={m} />)}
                  </datalist>
                  <div className="theme-hint">{t('rsverify.modelNameHint') || "手动输入模型名称后保存"}</div>
                </div>
                <div className="settings-section" style={{ display: "flex", gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <div className="settings-label">{t('rsverify.maxTokens')}</div>
                    <input className="smart-note" style={{ width: "100%" }} type="number" min={256} step={256}
                           value={form.max_tokens} onChange={(e) => set("max_tokens", e.target.value)} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div className="settings-label">{t('rsverify.temperature')}</div>
                    <input className="smart-note" style={{ width: "100%" }} type="number" min={0} max={2} step={0.1}
                           value={form.temperature} onChange={(e) => set("temperature", e.target.value)} />
                  </div>
                </div>

                <div className="settings-foot">{t('rsverify.settingsHint')}</div>

                <div className="modal-foot" style={{ marginTop: 14 }}>
                  <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
                  <button className="btn" onClick={resetForm}>{t('rsverify.reset')}</button>
                  <button className="btn primary" disabled={saving || !activeId} onClick={save}>
                    {saving ? t('common.loading') : t('rsverify.save')}
                  </button>
                </div>
              </>
            )}
          </>
        )}

        {/* 添加模型表单 */}
        {showAdd && (
          <AddPresetModal commonModels={commonModels} onClose={() => setShowAdd(false)}
                          onSaved={async () => { setShowAdd(false); await loadSettings(); }}
                          onNotify={onNotify} />
        )}

        {/* 删除预设确认弹窗 */}
        {confirm2 && (
          <div className="modal-mask" onClick={() => setConfirm2(null)}>
            <div className="modal smart-confirm-modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-head"><span className="modal-title">{confirm2.title}</span></div>
              <div className="confirm-body">{confirm2.body}</div>
              <div className="modal-foot">
                <button className="btn" onClick={() => setConfirm2(null)}>{t('common.cancel')}</button>
                <button className="btn primary" onClick={confirm2.onOk}>{confirm2.okText || t('common.confirm')}</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---- 本地模型下拉（自定义，展开菜单带圆角/阴影，与全局 smart-dropdown 风格一致） ----
function LocalModelDropdown({ value, onChange, models, onFetch }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState(null); // 菜单 fixed 定位坐标
  const dropRef = useRef(null);
  const btnRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e) {
      if (dropRef.current && !dropRef.current.contains(e.target)) setOpen(false);
    }
    function onScroll() { setOpen(false); }
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  function toggle() {
    if (open) { setOpen(false); return; }
    const btn = btnRef.current;
    if (btn) {
      const r = btn.getBoundingClientRect();
      setRect({ top: r.bottom + 4, left: r.left, width: r.width });
    }
    setOpen(true);
  }

  function pick(m) { onChange(m); setOpen(false); }

  return (
    <div className="smart-dropdown" style={{ flex: 1 }} ref={dropRef}>
      <button type="button" className="smart-dropdown-btn" style={{ width: "100%" }} ref={btnRef} onClick={toggle}>
        <span>{value || t('rsverify.localModelEmpty')}</span>
        <span className={`caret${open ? " up" : ""}`}>▾</span>
      </button>
      {open && (
        <div className="smart-dropdown-menu" style={rect}>
          {models.length === 0 && (
            <div className="smart-dropdown-item" onClick={() => { setOpen(false); onFetch(); }}>
              {t('rsverify.localModelEmpty')}
            </div>
          )}
          {models.map((m) => (
            <div key={m} className={`smart-dropdown-item${value === m ? " active" : ""}`} onClick={() => pick(m)}>
              {m}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- 添加模型（新预设）表单 ----
function AddPresetModal({ commonModels, onClose, onSaved, onNotify }) {
  const { t } = useTranslation();
  const [f, setF] = useState({ name: "", api: "openai", base_url: "", api_key: "", model_name: "", local_model_name: "", max_tokens: "2000", temperature: "0.2" });
  const [saving, setSaving] = useState(false);
  const [localModels, setLocalModels] = useState(readLocalModelsCache); // 本地 Ollama 模型（localStorage 缓存）
  const [fetchingLocal, setFetchingLocal] = useState(false);
  function set(k, v) { setF((o) => ({ ...o, [k]: v })); }

  async function fetchLocalModels() {
    setFetchingLocal(true);
    try {
      const res = await rsApi.fetchLocalModels();
      const models = res.models || [];
      setLocalModels(models);
      writeLocalModelsCache(models);
    } catch (e) {
      onNotify(t('rsverify.fetchModelsFail', { msg: e.message }), "error");
    } finally {
      setFetchingLocal(false);
    }
  }

  async function save() {
    if (!f.name.trim()) { onNotify(t('rsverify.nameRequired'), "warn"); return; }
    setSaving(true);
    try {
      await rsApi.createPreset({
        name: f.name.trim(),
        api: f.api,
        base_url: f.base_url,
        api_key: f.api_key,
        model_name: f.model_name,
        local_model_name: f.local_model_name,
        max_tokens: parseInt(f.max_tokens, 10) || 2000,
        temperature: parseFloat(f.temperature) || 0.2,
      });
      onNotify(t('rsverify.addDone'), "success");
      onSaved();
    } catch (e) {
      onNotify(t('rsverify.addFail', { msg: e.message }), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal settings-modal rs-settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t('rsverify.addPreset')}</span>
          <span className="modal-close" onClick={onClose}>{t('common.close')}</span>
        </div>

        <div className="settings-section">
          <div className="settings-label">{t('rsverify.presetName')}</div>
          <input className="smart-note" style={{ width: "100%" }} placeholder={t('rsverify.presetNamePlaceholder')}
                 value={f.name} onChange={(e) => set("name", e.target.value)} />
        </div>

        <div className="settings-section">
          <div className="settings-label">{t('rsverify.apiType')}</div>
          <div className="mode-select">
            <button className={`mode-btn ${f.api === "openai" ? "on" : ""}`}
                    onClick={() => set("api", "openai")}>{t('rsverify.apiTypeCloud')}</button>
            <button className={`mode-btn ${f.api === "local" ? "on" : ""}`}
                    onClick={() => set("api", "local")}>{t('rsverify.apiTypeLocal')}</button>
          </div>
        </div>

        {f.api === "openai" ? (
          <>
            <div className="settings-section">
              <div className="settings-label">{t('rsverify.baseUrl')}</div>
              <input className="smart-note" style={{ width: "100%" }} placeholder="https://api.openai.com/v1"
                     value={f.base_url} onChange={(e) => set("base_url", e.target.value)} />
            </div>
            <div className="settings-section">
              <div className="settings-label">{t('rsverify.apiKey')}</div>
              <input className="smart-note" style={{ width: "100%" }} type="password" placeholder="sk-..."
                     value={f.api_key} onChange={(e) => set("api_key", e.target.value)} />
            </div>
            <div className="settings-section">
              <div className="settings-label">{t('rsverify.modelName')}</div>
              <input className="smart-note" list="rs-add-model-list" style={{ width: "100%" }} placeholder="gpt-4o"
                     value={f.model_name} onChange={(e) => set("model_name", e.target.value)} />
              <datalist id="rs-add-model-list">
                {commonModels.map((m) => <option key={m} value={m} />)}
              </datalist>
            </div>
          </>
        ) : (
          <div className="settings-section">
            <div className="settings-label">{t('rsverify.localModelName')}</div>
            <div className="rs-model-row">
              <LocalModelDropdown value={f.local_model_name}
                                  onChange={(v) => set("local_model_name", v)}
                                  models={localModels} onFetch={fetchLocalModels} />
              <button className="btn" disabled={fetchingLocal} onClick={fetchLocalModels}>
                {fetchingLocal ? t('common.loading') : t('rsverify.localFetchModels')}
              </button>
            </div>
            <div className="theme-hint">{t('rsverify.localModelCount', { n: localModels.length })}</div>
          </div>
        )}

        {f.api === "openai" && (
          <div className="settings-section" style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <div className="settings-label">{t('rsverify.maxTokens')}</div>
              <input className="smart-note" style={{ width: "100%" }} type="number" min={256} step={256}
                     value={f.max_tokens} onChange={(e) => set("max_tokens", e.target.value)} />
            </div>
            <div style={{ flex: 1 }}>
              <div className="settings-label">{t('rsverify.temperature')}</div>
              <input className="smart-note" style={{ width: "100%" }} type="number" min={0} max={2} step={0.1}
                     value={f.temperature} onChange={(e) => set("temperature", e.target.value)} />
            </div>
          </div>
        )}

        <div className="modal-foot" style={{ marginTop: 14 }}>
          <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button className="btn primary" disabled={saving} onClick={save}>
            {saving ? t('common.loading') : t('rsverify.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
