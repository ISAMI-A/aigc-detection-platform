import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  uploadImages, fetchUploads, deleteUploads, recognize,
  fetchResults, fetchResultDetail, manualSave, deleteResults, exportExcel,
} from "../../api/faceApi.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import { imgUrl } from "../../api/index.js";

// 人脸识别页：上传图/结果统一后端存储（web/data/face_uploads + face_thumbs），游客设备隔离。
// 一图多脸 → 结果列表一行一张脸；人工标注入库写全局人脸库（游客只读）。
export default function FaceRec() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [uploads, setUploads] = useState([]);       // 上传列表
  const [results, setResults] = useState([]);       // 结果列表（一行=一张脸）
  const [recognizing, setRecognizing] = useState(false);
  const [progress, setProgress] = useState(null);   // {pct, msg}
  const [detail, setDetail] = useState(null);       // 详情弹窗（含 candidates/embed）
  const [manual, setManual] = useState(null);       // 人工标注入库弹窗 {row, name}
  const [conflict, setConflict] = useState(null);   // 冲突确认弹窗 {row, name, conflict}
  const [exporting, setExporting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef(null);
  const dirInput = useRef(null);
  const abortRef = useRef(null);
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  const showToast = (msg, type = "info") => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ msg, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  };

  useEffect(() => () => {
    if (abortRef.current) abortRef.current.abort();
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  // 初始化：从后端恢复上传列表与结果（刷新不丢）
  useEffect(() => {
    fetchUploads().then((d) => {
      setUploads((d.items || []).map((it) => ({
        id: it.id, name: it.name, status: it.status || "pending",
        thumb: `${imgUrl(it.url)}&t=${Date.now()}`, url: it.url, checked: false,
      })));
    }).catch(() => {});
    fetchResults().then((d) => {
      setResults((d.items || []).map((it) => ({ ...it, checked: false })));
    }).catch(() => {});
    const onCleared = () => { setResults([]); setUploads([]); };
    window.addEventListener("cache-cleared", onCleared);
    return () => window.removeEventListener("cache-cleared", onCleared);
  }, []);

  // ==================== 上传 ====================
  async function addUploads(files) {
    const list = files.filter((f) => /\.(jpg|jpeg|png|bmp|webp|tif|tiff)$/i.test(f.name || ""));
    if (!list.length) return;
    try {
      const { items } = await uploadImages(list);
      const merged = (items || []).map((it) => ({
        id: it.id, name: it.name, status: "pending", checked: false,
        thumb: `${imgUrl(it.url)}&t=${Date.now()}`, url: it.url,
      }));
      const existIds = new Set(uploads.map((u) => u.id));
      const fresh = merged.filter((m) => !existIds.has(m.id));
      if (fresh.length < merged.length) {
        showToast(t("face.dupSkipped", { n: merged.length - fresh.length }), "warn");
      }
      setUploads((u) => {
        const seen = new Set(u.map((x) => x.id));
        return [...u, ...fresh.filter((m) => !seen.has(m.id))];
      });
    } catch (e) {
      showToast(t("face.uploadFail", { msg: e.message }), "error");
    }
  }

  function onDrop(e) {
    e.preventDefault();
    const items = [...(e.dataTransfer.items || [])];
    const files = [];
    const dirs = [];
    for (const it of items) {
      const entry = it.webkitGetAsEntry && it.webkitGetAsEntry();
      if (entry && entry.isDirectory) dirs.push(entry);
      else if (it.kind === "file") files.push(it.getAsFile());
    }
    Promise.all(dirs.map(readDirOnce)).then((arrs) => {
      addUploads([...files, ...arrs.flat()]);
    });
  }
  function readDirOnce(dirEntry) {
    return new Promise((resolve) => {
      const reader = dirEntry.createReader();
      reader.readEntries(
        (entries) => Promise.all(
          entries.filter((en) => en.isFile)
            .map((en) => new Promise((res) => en.file(res)))
        ).then(resolve),
        () => resolve([])
      );
    });
  }

  // ==================== 识别（含重测） ====================
  async function runRecognize(targets) {
    if (!targets.length) return;
    const ac = new AbortController();
    abortRef.current = ac;
    setRecognizing(true);
    setProgress({ pct: 2, msg: t("face.preparing") });
    try {
      const data = await recognize(targets.map((u) => u.id), (ev) => {
        if (ev.type === "phase" || ev.type === "progress") {
          setProgress({ pct: ev.pct || 0, msg: ev.msg || "" });
        }
      }, ac.signal);
      setProgress(null);
      // 更新上传列表状态
      setUploads((us) => us.map((u) => {
        const r = (data.results || []).find((x) => x.upload_id === u.id);
        if (!r) return u;
        return { ...u, status: r.status || "pending" };
      }));
      // 无脸/失败提示
      const noFace = (data.results || []).filter((r) => r.status === "no_face");
      const errs = (data.results || []).filter((r) => r.status === "error");
      if (errs.length) showToast(t("face.recogFail", { n: errs.length }), "error");
      if (noFace.length) showToast(t("face.noFaceTip", { n: noFace.length }), "warn");
      // 重新拉取结果（覆盖旧结果）
      const d = await fetchResults();
      setResults((d.items || []).map((it) => ({ ...it, checked: false })));
    } catch (e) {
      if (e && e.name === "AbortError") return;
      setProgress(null);
      showToast(t("face.recogError", { msg: e.message }), "error");
    } finally {
      setRecognizing(false);
      if (abortRef.current === ac) abortRef.current = null;
    }
  }

  // 开始识别：勾选→识别选中；未勾选→识别全部未完成
  function startRecognize() {
    const pending = uploads.filter((u) => u.status === "pending" || u.status === "error");
    const targets = checkedUpIds.length ? pending.filter((u) => checkedUpIds.includes(u.id)) : pending;
    if (!targets.length && checkedUpIds.length) {
      showToast(t("face.allDone"), "warn");
      return;
    }
    runRecognize(targets);
  }

  // 重测：结果行操作列（单图）/ 表头上方（全部/选中）
  function retest(uploadIds) {
    const targets = uploads.filter((u) => uploadIds.includes(u.id));
    if (!targets.length) { showToast(t("face.noFileForRetry"), "warn"); return; }
    runRecognize(targets);
  }

  // ==================== 删除 ====================
  async function removeUploads(ids) {
    setUploads((us) => us.filter((u) => !ids.includes(u.id)));
    try {
      await deleteUploads(ids);
      const d = await fetchResults();
      setResults((d.items || []).map((it) => ({ ...it, checked: false })));
    } catch (e) { console.error(e); }
  }
  async function removeResults(ids) {
    setResults((old) => old.filter((r) => !ids.includes(r.id)));
    try { await deleteResults(ids); } catch (e) { console.error(e); }
  }

  // ==================== 勾选管理 ====================
  const checkedUpIds = uploads.filter((u) => u.checked).map((u) => u.id);
  function toggleUpAll(e) {
    setUploads((old) => old.map((u) => ({ ...u, checked: e.target.checked })));
  }
  function toggleUpOne(id) {
    setUploads((old) => old.map((u) => (u.id === id ? { ...u, checked: !u.checked } : u)));
  }
  const checkedResIds = results.filter((r) => r.checked).map((r) => r.id);
  function toggleAll(e) {
    setResults((old) => old.map((r) => ({ ...r, checked: e.target.checked })));
  }
  function toggleOne(id) {
    setResults((old) => old.map((r) => (r.id === id ? { ...r, checked: !r.checked } : r)));
  }

  // 单击行开详情 / 双击行勾选
  const clickTimer = useRef(null);
  function onRowClick(r) {
    clearTimeout(clickTimer.current);
    clickTimer.current = setTimeout(() => openDetail(r), 200);
  }
  function onRowDoubleClick(id) {
    clearTimeout(clickTimer.current);
    toggleOne(id);
  }

  async function openDetail(r) {
    setDetail({ ...r, loading: true });
    try {
      const d = await fetchResultDetail(r.id);
      setDetail({ ...r, ...d });
    } catch (e) {
      setDetail(null);
      showToast(t("face.detailFail", { msg: e.message }), "error");
    }
  }

  // ==================== 人工标注入库 ====================
  function openManual(row) {
    if (!auth.isLoggedIn) {
      window.dispatchEvent(new CustomEvent("require-login"));
      return;
    }
    setManual({ row, name: row.manual_name || row.matched_name || "" });
  }

  async function submitManual() {
    const name = (manual.name || "").trim();
    if (!name) { showToast(t("face.nameRequired"), "warn"); return; }
    try {
      const d = await manualSave(manual.row.id, name);
      if (d && d.need_confirm) {
        setManual(null);
        setConflict({ row: manual.row, name, conflict: d.conflict });
        return;
      }
      setManual(null);
      showToast(t("face.saved"), "success");
      const dd = await fetchResults();
      setResults((dd.items || []).map((it) => ({ ...it, checked: false })));
      if (detail && detail.id === manual.row.id) openDetail({ ...manual.row });
    } catch (e) {
      showToast(t("face.saveFail", { msg: e.message }), "error");
    }
  }

  async function resolveConflict(mode) {
    const { row, name } = conflict;
    setConflict(null);
    try {
      await manualSave(row.id, name, mode);
      showToast(mode === "overwrite" ? t("face.overwritten") : t("face.addedNew"), "success");
      const dd = await fetchResults();
      setResults((dd.items || []).map((it) => ({ ...it, checked: false })));
      if (detail && detail.id === row.id) openDetail({ ...row });
    } catch (e) {
      showToast(t("face.saveFail", { msg: e.message }), "error");
    }
  }

  // ==================== 导出 ====================
  async function doExport() {
    if (exporting) return;
    const ids = checkedResIds.length ? checkedResIds : [];
    if (!checkedResIds.length && !results.length) return;
    setExporting(true);
    try {
      await exportExcel(ids);
      showToast(t("face.exportDone"), "success");
    } catch (e) {
      showToast(t("face.exportFail", { msg: e.message }), "error");
    } finally {
      setExporting(false);
    }
  }

  // 统计：识别成功/失败
  const stat = useMemo(() => {
    const ok = results.filter((r) => r.matched).length;
    return { ok, fail: results.length - ok };
  }, [results]);

  // 可重测目标（结果对应的上传图）
  const retestAllIds = [...new Set(results.map((r) => r.upload_id))];
  const retestCheckedIds = [
    ...new Set(results.filter((r) => r.checked).map((r) => r.upload_id)),
  ];

  return (
    <div className="face">
      <div className="page-head">
        <div className="page-title">{t("face.title")}</div>
      </div>

      {/* 上传区 */}
      <div className={`upload-zone${dragOver ? " dragover" : ""}`}
           onDragOver={(e) => e.preventDefault()}
           onDragEnter={() => setDragOver(true)}
           onDragLeave={(e) => { if (e.currentTarget === e.target) setDragOver(false); }}
           onDrop={(e) => { setDragOver(false); onDrop(e); }}>
        <div className="upload-hint">{t("face.dropHint")}</div>
        <div className="upload-btns">
          <button className="btn" onClick={() => fileInput.current && fileInput.current.click()}>{t("face.selectImage")}</button>
          <button className="btn" onClick={() => dirInput.current && dirInput.current.click()}>{t("face.selectFolder")}</button>
        </div>
        <input ref={fileInput} type="file" multiple accept="image/*" style={{ display: "none" }}
               onChange={(e) => { addUploads([...e.target.files]); e.target.value = ""; }} />
        <input ref={dirInput} type="file" webkitdirectory="" directory="" multiple style={{ display: "none" }}
               onChange={(e) => { addUploads([...e.target.files]); e.target.value = ""; }} />
        <div className="upload-formats">{t("face.formatHint")}</div>
      </div>

      {/* 上传列表 */}
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title">{t("face.uploadList", { n: uploads.length })}</span>
          <div className="panel-ops">
            <button className="btn small"
                    onClick={() => removeUploads(checkedUpIds.length ? checkedUpIds : uploads.map((u) => u.id))}>
              {checkedUpIds.length ? t("face.clearSelected") : t("face.clearAll")}
            </button>
            <button className="btn primary" disabled={recognizing} onClick={startRecognize}>
              {recognizing ? t("face.recognizing")
                : (checkedUpIds.length ? t("face.recogSelected", { n: checkedUpIds.length })
                  : "▶ " + t("face.startRecognize"))}
            </button>
          </div>
        </div>
        {progress && (
          <div className="progress-wrap">
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progress.pct}%` }} />
            </div>
            <div className="progress-text">{progress.msg} · {progress.pct}%</div>
          </div>
        )}
        <div className="table-wrap upload-table">
          <table>
            <thead>
              <tr>
                <th style={{ width: 32 }}><input type="checkbox" onChange={toggleUpAll}
                    checked={uploads.length > 0 && uploads.every((u) => u.checked)} /></th>
                <th style={{ width: 70 }}>{t("face.thumb")}</th>
                <th>{t("face.fileName")}</th>
                <th style={{ width: 110 }}>{t("face.status")}</th>
              </tr>
            </thead>
            <tbody>
              {uploads.map((u) => (
                <tr key={u.id} className={u.checked ? "row-checked" : ""}
                    onDoubleClick={(e) => {
                      const td = e.target.closest("td");
                      if (td && td.classList.contains("check-cell")) return;
                      toggleUpOne(u.id);
                    }}>
                  <td className="check-cell"><input type="checkbox" checked={!!u.checked} onChange={() => toggleUpOne(u.id)} /></td>
                  <td>{u.thumb ? <img src={u.thumb} alt="" className="thumb" /> : <div className="thumb thumb-ph">{"-"}</div>}</td>
                  <td className="cell-name" title={u.name}>{u.name}</td>
                  <td>
                    <span className={`status ${u.status === "done" ? "完成" : u.status === "no_face" ? "失败" : u.status === "error" ? "失败" : "待检测"}`}>
                      {u.status === "done" ? t("face.stDone")
                        : u.status === "no_face" ? t("face.stNoFace")
                        : u.status === "error" ? t("face.stError")
                        : t("face.stPending")}
                    </span>
                  </td>
                </tr>
              ))}
              {!uploads.length && <tr><td colSpan={4} className="empty">{t("face.noUploads")}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* 结果列表（一行=一张脸） */}
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title">{t("face.resultList", { n: results.length })}</span>
          {results.length > 0 && (
            <span className="stat">{t("face.stats", { ok: stat.ok, fail: stat.fail })}</span>
          )}
          <div className="panel-ops">
            <button className="btn small" disabled={!results.length}
                    onClick={() => removeResults(checkedResIds.length ? checkedResIds : results.map((r) => r.id))}>
              {checkedResIds.length ? t("face.deleteSelected") : t("face.clearResult")}
            </button>
            <button className="btn small" disabled={recognizing || !retestAllIds.length}
                    onClick={() => retest(retestCheckedIds.length ? retestCheckedIds : retestAllIds)}>
              {retestCheckedIds.length ? t("face.retestSelected") : t("face.retestAll")}
            </button>
            <button className="btn primary" disabled={exporting || !results.length} onClick={doExport}>
              {exporting ? t("face.exporting")
                : (checkedResIds.length ? t("face.exportSelected", { n: checkedResIds.length }) : t("face.export"))}
            </button>
          </div>
        </div>
        <div className="table-wrap result-table">
          <table>
            <thead>
              <tr>
                <th style={{ width: 40 }}><input type="checkbox" onChange={toggleAll}
                    checked={results.length > 0 && results.every((r) => r.checked)} /></th>
                <th className="th-center" style={{ width: 76 }}>{t("face.faceThumb")}</th>
                <th>{t("face.name")}</th>
                <th className="th-center" style={{ width: 90 }}>{t("face.similarity")}</th>
                <th className="th-center" style={{ width: 100 }}>{t("face.result")}</th>
                <th>{t("face.sourceFile")}</th>
                <th className="th-center" style={{ width: 170 }}>{t("face.action")}</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.id} className={r.checked ? "row-checked" : ""}
                    onClick={() => onRowClick(r)}
                    onDoubleClick={(e) => {
                      const td = e.target.closest("td");
                      if (td && (td.classList.contains("check-cell") || td.classList.contains("cell-ops"))) return;
                      onRowDoubleClick(r.id);
                    }}>
                  <td className="check-cell" onClick={(e) => { e.stopPropagation(); toggleOne(r.id); }}>
                    <input type="checkbox" checked={!!r.checked} readOnly />
                  </td>
                  <td><img src={imgUrl(r.thumb)} alt="" className="thumb face-thumb" /></td>
                  <td className="cell-name">
                    {r.manual_name
                      ? <><span className="jud-manual">{r.manual_name}</span><span className="badge">{t("face.manualTag")}</span></>
                      : (r.matched ? <span className="jud-text">{r.matched_name}</span>
                        : <span className="dim">{t("face.unknown")}</span>)}
                  </td>
                  <td className="cell-num">{r.matched || r.manual_name ? (r.similarity ?? "-") : "-"}</td>
                  <td>
                    <span className={`jud-text ${r.matched ? "jud-yes" : "jud-no"}`}>
                      {r.matched ? t("face.matched") : t("face.notMatched")}
                    </span>
                    {!r.matched && <div className="dim face-fail-reason">{t("face.notInLib")}</div>}
                  </td>
                  <td className="cell-name" title={r.upload_name}>{r.upload_name}</td>
                  <td className="cell-ops">
                    <button className="btn small btn-view" onClick={(e) => { e.stopPropagation(); openDetail(r); }}>{t("face.view")}</button>
                    <button className="btn small" title={t("face.manualSave")} onClick={(e) => { e.stopPropagation(); openManual(r); }}>✎</button>
                    <button className="icon-btn" title={t("face.retest")} disabled={recognizing}
                            onClick={(e) => { e.stopPropagation(); retest([r.upload_id]); }}>
                      {/* 重测小 SVG 图标（刷新箭头） */}
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                           strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
                      </svg>
                    </button>
                  </td>
                </tr>
              ))}
              {!results.length && <tr><td colSpan={7} className="empty">{t("face.noResults")}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* 详情弹窗 */}
      {detail && <DetailModal item={detail} onManual={() => openManual(detail)} onClose={() => setDetail(null)} />}

      {/* 人工标注入库弹窗 */}
      {manual && (
        <div className="modal-mask" onClick={() => setManual(null)}>
          <div className="modal face-manual-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{t("face.manualTitle")}</span>
              <button className="btn small" onClick={() => setManual(null)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="detail-row"><span>{t("face.faceThumb")}</span>
                <img src={imgUrl(manual.row.thumb)} alt="" className="thumb face-thumb" /></div>
              <div className="detail-row"><span>{t("face.currentName")}</span>
                <b>{manual.row.manual_name || manual.row.matched_name || t("face.unknown")}</b></div>
              <div className="detail-row"><span>{t("face.inputName")}</span>
                <input className="note-input" autoFocus
                       placeholder={t("face.namePlaceholder")}
                       value={manual.name}
                       onChange={(e) => setManual({ ...manual, name: e.target.value })}
                       onKeyDown={(e) => { if (e.key === "Enter") submitManual(); }} /></div>
              <div className="dim face-manual-tip">{t("face.manualTip")}</div>
            </div>
            <div className="modal-foot">
              <button className="btn" onClick={() => setManual(null)}>{t("common.cancel")}</button>
              <button className="btn primary" onClick={submitManual}>{t("face.saveToLib")}</button>
            </div>
          </div>
        </div>
      )}

      {/* 冲突确认弹窗（库中相似人脸但姓名不同） */}
      {conflict && (
        <div className="modal-mask" onClick={() => setConflict(null)}>
          <div className="modal face-manual-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{t("face.conflictTitle")}</span>
              <button className="btn small" onClick={() => setConflict(null)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="face-conflict-body">
                <div className="face-conflict-text"
                     dangerouslySetInnerHTML={{ __html: t("face.conflictBody", {
                       name: conflict.name, old: conflict.conflict.name,
                       sim: Math.round((conflict.conflict.similarity || 0) * 100),
                     }) }} />
                <div className="face-conflict-opts">
                  <button className="btn primary" onClick={() => resolveConflict("overwrite")}>
                    {t("face.conflictOverwrite")}<div className="dim">{t("face.conflictOverwriteDesc")}</div>
                  </button>
                  <button className="btn" onClick={() => resolveConflict("new")}>
                    {t("face.conflictNew")}<div className="dim">{t("face.conflictNewDesc")}</div>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 轻提示 */}
      {toast && (
        <div className={`toast toast-${toast.type}`}>
          {toast.type === "success" ? "✓ " : toast.type === "error" ? "✕ " : toast.type === "warn" ? "! " : ""}
          {toast.msg}
        </div>
      )}
    </div>
  );
}

// 原图 + bbox 红框叠加（bbox 为落盘图坐标，onLoad 取实际尺寸换算百分比定位）
function OrigWithBox({ src, bbox }) {
  const [size, setSize] = useState(null);
  return (
    <div className="face-orig-box">
      <img src={src} alt=""
           onLoad={(e) => setSize({ w: e.target.naturalWidth, h: e.target.naturalHeight })} />
      {size && bbox.length === 4 && (
        <div style={{
          position: "absolute",
          left: `${(bbox[0] / size.w) * 100}%`,
          top: `${(bbox[1] / size.h) * 100}%`,
          width: `${((bbox[2] - bbox[0]) / size.w) * 100}%`,
          height: `${((bbox[3] - bbox[1]) / size.h) * 100}%`,
          border: "2px solid #ff4d4f", borderRadius: 2, boxSizing: "border-box",
        }} />
      )}
    </div>
  );
}

// 详情弹窗：人脸大图 + 原图带框 + 检测参数 + Top-K 候选 + 512 维特征
function DetailModal({ item, onManual, onClose }) {
  const { t } = useTranslation();
  const [showEmbed, setShowEmbed] = useState(false);
  const bbox = item.bbox || [];

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal face-detail-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t("face.detailTitle")}</span>
          <button className="btn small" onClick={onClose}>✕</button>
        </div>
        <div className="detail-imgs">
          <div className="detail-img">
            <div className="detail-label">{t("face.faceThumb")}</div>
            {item.thumb ? <img src={imgUrl(item.thumb)} alt="" className="face-detail-face" /> : null}
            <div className="dim face-det-score">{t("face.detScore")}: {item.det_score ?? "-"}</div>
          </div>
          <div className="detail-img">
            <div className="detail-label">{t("face.origWithBox")}</div>
            {item.orig ? <OrigWithBox src={imgUrl(item.orig)} bbox={bbox} />
              : <div className="expired">{t("face.origExpired")}</div>}
            <div className="dim">{t("face.bboxLabel")}: [{bbox.join(", ")}]</div>
          </div>
        </div>
        <div className="detail-info">
          <div className="detail-row"><span>{t("face.name")}</span>
            <b>{item.manual_name || item.matched_name || t("face.unknown")}</b>
            {item.manual_name && <span className="badge">{t("face.manualTag")}</span>}</div>
          <div className="detail-row"><span>{t("face.result")}</span>
            <b className={item.matched ? "jud-yes" : "jud-no"}>
              {item.matched ? t("face.matched") : t("face.notMatched")}</b></div>
          <div className="detail-row"><span>{t("face.similarity")}</span>
            <b>{item.similarity ?? "-"}（{t("face.threshold")}: {item.threshold ?? "-"}）</b></div>
          <div className="detail-row"><span>{t("face.sourceFile")}</span><b>{item.upload_name}</b></div>
          <div className="detail-row"><span>{t("face.time")}</span><b>{item.created_at}</b></div>
        </div>

        {/* Top-K 候选相似度表 */}
        <div className="face-cand">
          <div className="detail-label">{t("face.candidates")}</div>
          <table className="face-cand-table">
            <thead>
              <tr><th>{t("face.candRank")}</th><th>{t("face.name")}</th>
                <th>{t("face.personId")}</th><th>{t("face.similarity")}</th></tr>
            </thead>
            <tbody>
              {(item.candidates || []).map((c, i) => (
                <tr key={i} className={i === 0 && item.matched ? "row-checked" : ""}>
                  <td>#{i + 1}</td><td>{c.name}</td>
                  <td className="dim">{c.person_id}</td>
                  <td className="cell-num">{Math.round((c.similarity || 0) * 10000) / 10000}</td>
                </tr>
              ))}
              {!(item.candidates || []).length && (
                <tr><td colSpan={4} className="empty">{t("face.noCandidates")}</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 512 维特征（折叠） */}
        <div className="face-embed">
          <button className="btn small" onClick={() => setShowEmbed(!showEmbed)}>
            {showEmbed ? t("face.hideEmbed") : t("face.showEmbed")}
          </button>
          {showEmbed && (
            <div className="face-embed-grid">
              {(item.embed || []).map((v, i) => <span key={i} className="face-embed-cell">{v}</span>)}
              {!(item.embed || []).length && <span className="dim">{t("face.noEmbed")}</span>}
            </div>
          )}
        </div>

        <div className="modal-foot">
          <button className="btn" onClick={onClose}>{t("common.close")}</button>
          <button className="btn primary" onClick={onManual}>{t("face.manualSave")}</button>
        </div>
      </div>
    </div>
  );
}
