import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { smartApi } from "../../api/smartApi.js";
import UploadPanel from "./UploadPanel.jsx";
import ResultTable from "./ResultTable.jsx";
import ImageCompare from "./ImageCompare.jsx";

// 点位真实性核验系统（Smart Matching System 的 React 集成版）
// 交互约定：提示全部用组件内 toast（3s 自动消失）/ 确认用组件内弹窗，不用浏览器 alert/confirm
export default function SmartVerify() {
  const { t } = useTranslation();
  const [pairMode, setPairMode] = useState("auto");
  const leftRef = useRef(null);
  const rightRef = useRef(null);
  // 上传面板状态上报（响应式：上传/删除/排序即时驱动按钮可用态）
  const [leftCount, setLeftCount] = useState(0);
  const [rightCount, setRightCount] = useState(0);
  const [leftSel, setLeftSel] = useState(0);
  const [rightSel, setRightSel] = useState(0);

  const [pairResults, setPairResults] = useState([]);
  const [currentPair, setCurrentPair] = useState(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedPairs, setSelectedPairs] = useState([]);
  const [progress, setProgress] = useState(null);
  const progressTimer = useRef(null);

  // 轻提示（自动消失）
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);
  // 确认弹窗（组件内，非浏览器 confirm）
  const [confirm, setConfirm] = useState(null);
  // 导出预览弹窗（未核验跳过统计）与导出等待条
  const [exportInfo, setExportInfo] = useState(null);
  const [exporting, setExporting] = useState(false);

  const showToast = useCallback((msg, type = "info") => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ msg, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  // 页面加载恢复数据；监听系统设置清空事件
  useEffect(() => {
    loadResults();
    loadImages();
    const onPanelCleared = () => { leftRef.current && leftRef.current.reset(); rightRef.current && rightRef.current.reset(); };
    const onDataCleared = () => {
      leftRef.current && leftRef.current.reset();
      rightRef.current && rightRef.current.reset();
      setPairResults([]); setCurrentPair(null); setSelectedPairs([]); setPairMode("auto");
      showToast(t('verify.dataCleared'));
    };
    window.addEventListener("smart-verify-panel-cleared", onPanelCleared);
    window.addEventListener("smart-verify-cleared", onDataCleared);
    return () => {
      if (progressTimer.current) clearInterval(progressTimer.current);
      if (toastTimer.current) clearTimeout(toastTimer.current);
      window.removeEventListener("smart-verify-panel-cleared", onPanelCleared);
      window.removeEventListener("smart-verify-cleared", onDataCleared);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ===== 数据加载 =====
  async function loadResults(silent) {
    try {
      const res = await smartApi.results();
      setPairResults(res.items || []);
      if (!silent) showToast(t('verify.refreshDone', { count: res.items?.length || 0 }));
    } catch (e) {
      console.error("加载结果失败", e);
      if (!silent) showToast(t('verify.refreshFail', { msg: e.message }), "error");
    }
  }
  async function loadImages() {
    try {
      const res = await smartApi.imagesList();
      leftRef.current && leftRef.current.restoreImages(res.left_images);
      rightRef.current && rightRef.current.restoreImages(res.right_images);
    } catch (e) {
      console.error("加载图片失败", e);
    }
  }

  // ===== 按钮可用态 =====
  const canGenerate = useMemo(() => {
    if (pairMode === "manual") return leftSel > 0 && leftSel === rightSel;
    return leftCount > 0 && rightCount > 0;
  }, [pairMode, leftCount, rightCount, leftSel, rightSel]);
  const manualHint = useMemo(() => {
    if (pairMode !== "manual") return "";
    if (leftSel === 0 && rightSel === 0) return t('verify.needSelect');
    if (leftSel !== rightSel) return t('verify.countMismatch', { left: leftSel, right: rightSel });
    return "";
  }, [pairMode, leftSel, rightSel, t]);

  const pendingCount = pairResults.filter((p) => ["pending", "error", "running"].includes(p.status)).length;

  const stats = useMemo(() => {
    const done = pairResults.filter((p) => p.status === "done");
    const passed = done.filter((p) => p.is_same === true).length;
    const failed = done.filter((p) => p.is_same === false).length;
    const missing = pairResults.filter((p) => p.status === "missing").length;
    const passRate = done.length > 0 ? Math.round((passed / done.length) * 1000) / 10 : 0;
    return { valid: done.length, passed, failed, passRate, missing };
  }, [pairResults]);

  // ===== 生成配对（含重复配对检查） =====
  async function doGeneratePairs(deleteOld) {
    if (!leftRef.current || !rightRef.current) return;
    const leftPanel = leftRef.current;
    const rightPanel = rightRef.current;
    // manual（选择比对）：按点击顺序编号（selOrder 1,2,3...）排序后再一一配对
    const sortBySel = (a, b) => (a.selOrder || 0) - (b.selOrder || 0);
    const leftList = pairMode === "manual"
      ? leftPanel.getFiles().filter((f) => f.selected).sort(sortBySel)
      : leftPanel.getFiles();
    const rightList = pairMode === "manual"
      ? rightPanel.getFiles().filter((f) => f.selected).sort(sortBySel)
      : rightPanel.getFiles();

    // 重复配对确认后：先删除旧配对及其结果，再重新生成
    if (deleteOld && pairResults.length > 0) {
      await smartApi.deletePairs(pairResults.map((p) => p.pair_id));
      await loadResults(true);
    }

    // 上传即落盘后，所有文件应已有 id；未上传完的提示等待
    const pending = leftList.some((f) => !f.id) || rightList.some((f) => !f.id);
    if (pending) {
      showToast(t('rsverify.uploadPending', { name: 'files' }), "warn");
      return;
    }
    const leftIds = leftList.map((f) => f.id);
    const rightIds = rightList.map((f) => f.id);
    if (leftIds.length === 0 || rightIds.length === 0) {
      showToast(t('verify.noImages'), "error");
      return;
    }

    // 2. 配对
    try {
      await smartApi.pair(pairMode, leftIds, rightIds);
      await loadResults(true);
      showToast(t('verify.pairDone'));
    } catch (e) {
      showToast(t('verify.pairFail', { msg: e.message }), "error");
    }
  }

  function handleGeneratePairs() {
    // 重复配对检查：所选图片是否已存在于结果列表
    const usedIds = new Set();
    pairResults.forEach((p) => {
      if (p.left_image_id) usedIds.add(p.left_image_id);
      if (p.right_image_id) usedIds.add(p.right_image_id);
    });
    const leftList = pairMode === "manual"
      ? (leftRef.current?.getFiles() || []).filter((f) => f.selected) : (leftRef.current?.getFiles() || []);
    const rightList = pairMode === "manual"
      ? (rightRef.current?.getFiles() || []).filter((f) => f.selected) : (rightRef.current?.getFiles() || []);
    const overlap = [...leftList, ...rightList].filter((f) => f.id && usedIds.has(f.id)).length;

    if (overlap > 0) {
      setConfirm({
        title: t('verify.dupTitle'),
        body: t('verify.dupDesc', { n: overlap }),
        okText: t('verify.dupContinue'),
        onOk: () => { setConfirm(null); doGeneratePairs(true); },
      });
    } else {
      doGeneratePairs(false);
    }
  }

  // ===== 进度轮询 =====
  function startProgressPolling() {
    progressTimer.current = setInterval(async () => {
      try {
        const res = await smartApi.progress();
        if (res.running) {
          setProgress({
            visible: true,
            total: res.total, processed: res.processed,
            pct: res.total > 0 ? Math.round((res.processed / res.total) * 100) : 0,
            current: res.current || "",
          });
        } else {
          stopProgressPolling();
        }
      } catch (_) { /* 忽略轮询错误 */ }
    }, 500);
  }
  function stopProgressPolling() {
    if (progressTimer.current) { clearInterval(progressTimer.current); progressTimer.current = null; }
    setProgress(null);
  }
  function stopProgressLater() { setTimeout(stopProgressPolling, 2000); }

  // ===== 核验（成功用 toast，不弹浏览器提示） =====
  async function handleSingleVerify(pairId) {
    try {
      const res = await smartApi.verifySingle(pairId);
      await loadResults(true);
      if (res.error) showToast(t('verify.verifyFail', { msg: res.error }), "error");
      else if (res.is_same !== undefined) showToast(t(res.is_same ? 'verify.verifySuccessSame' : 'verify.verifySuccessDiff'), "success");
      else showToast(t('verify.verifySuccess'), "success");
    } catch (e) {
      showToast(t('verify.verifyFail', { msg: e.message }), "error");
    }
  }
  // ===== 一键核验（有勾选核验选中，无勾选核验全部待核验） =====
  async function handleSmartVerify() {
    const pending = selectedPairs.length > 0
      ? selectedPairs.filter((p) => ["pending", "error", "running"].includes(p.status))
      : pairResults.filter((p) => ["pending", "error", "running"].includes(p.status));
    if (pending.length === 0) {
      showToast(selectedPairs.length > 0 ? t('verify.verifySkipDone') : t('verify.verifySkipNone'), "warn");
      return;
    }
    setBatchLoading(true);
    setProgress({ visible: true, total: 0, processed: 0, pct: 0, current: t('verify.preparing') });
    startProgressPolling();
    try {
      const res = await smartApi.verifySelected(pending.map((p) => p.pair_id));
      setSelectedPairs([]);
      await loadResults(true);
      showToast(t('verify.verifyDone', { n: res.processed }), "success");
    } catch (e) {
      showToast(t('verify.verifyFail', { msg: e.message }), "error");
    } finally {
      setBatchLoading(false);
      stopProgressLater();
    }
  }

  // ===== 导出（选中/全部；跳过未核验预览；等待条） =====
  function openExport() {
    const target = selectedPairs.length > 0 ? selectedPairs : pairResults;
    if (target.length === 0) { showToast(t('verify.noExportData'), "error"); return; }
    // 未核验完成的项（missing/error/pending/running）
    const skip = target.filter((p) => !["done"].includes(p.status)).map((p) => ({
      pair_id: p.pair_id,
      name: p.left_filename || p.right_filename || `#${p.pair_id}`,
      reason: p.status === "missing" ? t('verify.skipMissing') : p.status === "error" ? t('verify.skipError') : t('verify.skipPending'),
    }));
    const okIds = target.filter((p) => p.status === "done").map((p) => p.pair_id);
    if (okIds.length === 0) {
      showToast(t('verify.allSkipExport'), "error");
      return;
    }
    setExportInfo({
      total: target.length, ok: okIds.length, okIds, skip,
      isSelected: selectedPairs.length > 0,
    });
  }

  async function doExport(ids) {
    setExportInfo(null);
    setExporting(true);
    try {
      const r = await smartApi.exportExcel(ids);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = t('verify.exportFile');
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast(t('verify.exportSuccess', { n: ids.length }), "success");
    } catch (e) {
      showToast(t('verify.exportFail', { msg: e.message }), "error");
    } finally {
      setExporting(false);
    }
  }

  // ===== 删除 =====
  async function handleDeleteImage(imageId) {
    try {
      await smartApi.deleteImage(imageId);
      leftRef.current && leftRef.current.removeFileById(imageId);
      rightRef.current && rightRef.current.removeFileById(imageId);
      await loadResults(true);
      showToast(t('verify.imageDeleted'), "success");
    } catch (e) {
      showToast(t('verify.imageDeleteFail', { msg: e.message }), "error");
    }
  }
  async function handleDeleteSingle(pairId) {
    setConfirm({
      title: t('verify.deletePairTitle'),
      body: t('verify.deletePairDesc'),
      okText: t('common.delete'),
      onOk: async () => {
        setConfirm(null);
        try {
          await smartApi.deletePair(pairId);
          await loadResults(true);
          showToast(t('verify.pairDeleted'), "success");
        } catch (e) {
          showToast(t('verify.pairDeleteFail', { msg: e.message }), "error");
        }
      },
    });
  }
  async function handleBatchDelete() {
    const ids = selectedPairs.length > 0
      ? selectedPairs.map((r) => r.pair_id)
      : pairResults.map((r) => r.pair_id);   // 无勾选时删除全部
    if (ids.length === 0) return;
    setConfirm({
      title: t('verify.batchDeleteTitle'),
      body: selectedPairs.length > 0
        ? t('verify.batchDeleteDescSel', { n: ids.length })
        : t('verify.batchDeleteDescAll', { n: ids.length }),
      okText: t('common.delete'),
      onOk: async () => {
        setConfirm(null);
        try {
          await smartApi.deletePairs(ids);
          setSelectedPairs([]);
          await loadResults(true);
          showToast(t('verify.batchDeleted', { n: ids.length }), "success");
        } catch (e) {
          showToast(t('verify.batchDeleteFail', { msg: e.message }), "error");
        }
      },
    });
  }

  // ===== 上传面板：一键清空 / 清除选中 =====
  function handleClearUploads(side, list) {
    if (!list || list.length === 0) return;
    const ids = list.filter((f) => f.id).map((f) => f.id);
    const hasLocal = list.some((f) => !f.id);
    const name = side === "left" ? t('verify.rectifyPanel') : t('verify.inspectPanel');
    setConfirm({
      title: t('verify.clearPanelTitle', { name }),
      body: ids.length > 0
        ? t('verify.clearPanelDesc', { total: list.length, n: ids.length })
        : t('verify.clearPanelLocal'),
      okText: "清空",
      onOk: async () => {
        setConfirm(null);
        try {
          if (ids.length > 0) await Promise.all(ids.map((id) => smartApi.deleteImage(id).catch(() => {})));
          (side === "left" ? leftRef : rightRef).current?.removeFiles(list);
          await loadResults(true);
          showToast(t('verify.clearPanelDone', { name }), "success");
        } catch (e) {
          showToast(t('verify.clearPanelFail', { msg: e.message }), "error");
        }
      },
    });
  }

  async function handleRefresh() {
    setRefreshing(true);
    await loadResults(false);
    setRefreshing(false);
  }

  return (
    <div className="smart-page">
      <h2 className="smart-page-title">{t('verify.title')}</h2>

      {/* 配对策略切换 */}
      <div className="mode-select">
        {[
          { v: "auto", t: t('verify.autoPair') },
          { v: "sequential", t: t('verify.seqPair') },
          { v: "manual", t: t('verify.singlePair') },
        ].map((m) => (
          <button key={m.v} className={`mode-btn ${pairMode === m.v ? "on" : ""}`}
                  onClick={() => setPairMode(m.v)}>{m.t}</button>
        ))}
      </div>

      {/* 双栏上传区（files 变化即时上报，驱动按钮可用态） */}
      <div className="upload-section">
        <UploadPanel ref={leftRef} title={t('verify.rectifyPanel')} showCheckbox={pairMode === "manual"}
                     imageUrlFn={smartApi.imageUrl}
                     onFilesChanged={(list) => { setLeftCount(list.length); setLeftSel(list.filter((f) => f.selected).length); }}
                     onUploadFile={async (raw) => { const r = await smartApi.uploadSingle(raw, "整改图"); return r.image; }}
                     onDeleteImage={handleDeleteImage} onNotify={(m) => showToast(m, "warn")}
                     onClearFiles={(list) => handleClearUploads("left", list)} />
        <UploadPanel ref={rightRef} title={t('verify.inspectPanel')} showCheckbox={pairMode === "manual"}
                     imageUrlFn={smartApi.imageUrl}
                     onFilesChanged={(list) => { setRightCount(list.length); setRightSel(list.filter((f) => f.selected).length); }}
                     onUploadFile={async (raw) => { const r = await smartApi.uploadSingle(raw, "暗访图"); return r.image; }}
                     onDeleteImage={handleDeleteImage} onNotify={(m) => showToast(m, "warn")}
                     onClearFiles={(list) => handleClearUploads("right", list)} />
      </div>

      {/* 操作栏（清空面板/重置已迁移到系统设置 · 历史内容清理） */}
      <div className="action-bar">
        <button className="btn primary" disabled={!canGenerate} onClick={handleGeneratePairs}>
          {pairMode === "manual" ? t('verify.pairSelected') : t('verify.generatePairs')}
        </button>
        {manualHint && <span className="manual-hint">{manualHint}</span>}
      </div>

      {/* 批量操作 */}
      {pairResults.length > 0 && (
        <div className="batch-actions">
          <button className="btn btn-verify" disabled={batchLoading} onClick={handleSmartVerify}>
            {batchLoading ? t('verify.verifying') : (
              selectedPairs.length > 0 ? t('verify.verifySelected', { n: selectedPairs.length })
                : (pendingCount > 0 ? t('verify.verifyAll', { n: pendingCount }) : t('verify.verifyAllNone'))
            )}
          </button>
          <button className="btn" disabled={refreshing} onClick={handleRefresh}>
            {refreshing ? t('verify.refreshing') : t('verify.refresh')}
          </button>
          <button className="btn" disabled={exporting} onClick={openExport}>
            {selectedPairs.length > 0 ? t('verify.exportSelected', { n: selectedPairs.filter((p) => p.status === "done").length }) : t('verify.exportAll')}
          </button>
          <button className="btn btn-del-solid" onClick={handleBatchDelete}>
            {selectedPairs.length > 0 ? t('verify.deleteSelected', { n: selectedPairs.length }) : t('verify.deleteAll')}
          </button>
        </div>
      )}

      {/* 核验统计汇总 */}
      {pairResults.length > 0 && stats.valid > 0 && (
        <div className="stats-bar">
          <div className="stats-item"><span className="stats-label">{t('verify.statsValid')}</span><span className="stats-value">{stats.valid}</span></div>
          <div className="stats-item passed"><span className="stats-label">{t('verify.statsPass')}</span><span className="stats-value">{stats.passed}</span></div>
          <div className="stats-item failed"><span className="stats-label">{t('verify.statsFail')}</span><span className="stats-value">{stats.failed}</span></div>
          <div className={`stats-item ${stats.passRate >= 50 ? "passed" : "failed"}`}>
            <span className="stats-label">{t('verify.statsRate')}</span><span className="stats-value">{stats.passRate}%</span>
          </div>
          {stats.missing > 0 && (
            <div className="stats-item missing"><span className="stats-label">{t('verify.statsMissing')}</span><span className="stats-value">{stats.missing}</span></div>
          )}
        </div>
      )}

      {/* 结果表格（常驻显示；无数据时 ResultTable 内部显示空态行） */}
      <ResultTable data={pairResults}
                   onVerify={handleSingleVerify}
                   onSelect={setCurrentPair}
                   onDelete={handleDeleteSingle}
                   onSelectionChange={setSelectedPairs} />

      {/* 双图对比详情 */}
      {currentPair && (
        <ImageCompare pair={currentPair} onClose={() => setCurrentPair(null)}
                      onJudgmentSaved={(msg) => {
                        if (msg) showToast(msg, "error");
                        loadResults(true);
                      }} />
      )}

      {/* 核验进度弹窗 */}
      {progress && progress.visible && (
        <div className="modal-mask">
          <div className="modal smart-progress-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><span className="modal-title">{t('verify.progressTitle')}</span></div>
            <div className="progress-wrap">
              <div className="smart-progress-current">{progress.current}</div>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${progress.pct}%` }} />
              </div>
              <div className="progress-text">{progress.processed} / {progress.total} 对 · {progress.pct}%</div>
            </div>
          </div>
        </div>
      )}

      {/* 导出预览弹窗（未核验跳过统计） */}
      {exportInfo && (
        <div className="modal-mask">
          <div className="modal smart-export-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><span className="modal-title">{t('verify.exportPreview')}</span></div>
            <div className="export-body">
              <div className="export-summary">
                将导出 <strong>{exportInfo.ok}</strong> 条已核验结果（共 {exportInfo.total} 条）
              </div>
              {exportInfo.skip.length > 0 && (
                <>
                  <div className="export-skip-title">以下 {exportInfo.skip.length} 条未完成核验，已跳过：</div>
                  <div className="export-skip-list">
                    {exportInfo.skip.slice(0, 20).map((s) => (
                      <div key={s.pair_id} className="export-skip-item">
                        <span className="export-skip-name" title={s.name}>{s.name}</span>
                        <span className="smart-tag tag-warning">{s.reason}</span>
                      </div>
                    ))}
                    {exportInfo.skip.length > 20 && <div className="export-more">…等 {exportInfo.skip.length} 条</div>}
                  </div>
                </>
              )}
            </div>
            <div className="modal-foot">
              <button className="btn" onClick={() => setExportInfo(null)}>{t('common.cancel')}</button>
              <button className="btn primary" onClick={() => doExport(exportInfo.okIds)}>
                {t('verify.exportConfirm', { n: exportInfo.ok })}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 导出等待条 */}
      {exporting && (
        <div className="modal-mask">
          <div className="modal smart-export-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><span className="modal-title">{t('verify.exporting')}</span></div>
            <div className="export-body">
              <div className="smart-progress-current">{t('verify.exportingDesc')}</div>
              <div className="progress-bar indeterminate"><div className="progress-fill indeterminate" /></div>
            </div>
          </div>
        </div>
      )}

      {/* 确认弹窗（组件内） */}
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

      {/* 轻提示（Portal 到 body，避免父元素 transform 动画影响 fixed 定位） */}
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
