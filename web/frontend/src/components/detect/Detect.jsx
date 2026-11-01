import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from 'react-i18next';
import {
  detect, exportExcel, fetchParams, uploadImages, fetchUploads, deleteUploads,
  fetchDetectResults, updateDetectResult, deleteDetectResults,
} from "../../api/detectApi.js";
import { deviceHeaders } from "../../api/deviceId.js";
import { imgUrl } from "../../api/index.js";
import SettingsModal from "./SettingsModal.jsx";
import Dropdown from "../common/Dropdown.jsx";

// 图像篡改检测页：数据统一存后端（web/data/detect_uploads + detect_results），按游客设备隔离。
// 上传即落盘（刷新可恢复）、检测结果落盘 + 写记录、删除/清空联动删除文件（无落盘）。
export default function Detect() {
  const { t } = useTranslation();
  const [uploads, setUploads] = useState([]);   // 上传列表（后端落盘记录）
  const [results, setResults] = useState([]);   // 结果列表（后端落盘记录）
  const [detecting, setDetecting] = useState(false);
  const [progress, setProgress] = useState(null); // {pct, msg} 流式进度条
  const [filter, setFilter] = useState("全部");
  const [sortKey, setSortKey] = useState("");   // '' | score | area
  const [detail, setDetail] = useState(null);   // 详情弹窗对象
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [exporting, setExporting] = useState(false); // 导出进行中（禁用按钮防重复点击）
  const [exportMsg, setExportMsg] = useState("");    // 导出进度提示
  const [showSettings, setShowSettings] = useState(false); // 检测参数弹窗（仅本功能生效）
  const [params, setParams] = useState({});     // 判定参数（默认=后端默认值，调参仅影响本功能）
  const fileInput = useRef(null);
  const dirInput = useRef(null);
  const abortRef = useRef(null); // 进行中的检测请求（可中途取消）
  const exportRef = useRef(null); // 导出菜单（点击外部关闭）
  // 轻提示（右下角 toast，3 秒自动消失，不用浏览器 alert）
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  const showToast = (msg, type = "info") => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ msg, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  };

  // 组件卸载（关闭页面/刷新/切换标签页）时取消进行中的检测，后端收到中断即清理临时文件
  useEffect(() => () => {
    if (abortRef.current) abortRef.current.abort();
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  // 初始化：拉取默认参数 + 从后端恢复上传列表/结果（刷新不丢；游客设备隔离）
  useEffect(() => {
    fetchParams().then((d) => setParams({ ...d.defaults })).catch(() => {});
    fetchUploads().then((d) => {
      setUploads((d.items || []).map((it) => ({
        id: it.id, name: it.name, size: 0,
        status: it.done ? "完成" : "待检测",   // 已检测过的文件恢复为"完成"，避免重复检测
        checked: false, thumb: `${imgUrl(it.url)}&t=${Date.now()}`, url: it.url,  // 时间戳防缓存（SQLite 删除后 rowid 复用 → 同 URL 浏览器不刷新）
      })));
    }).catch((e) => console.error("加载上传列表失败", e));
    fetchDetectResults().then((d) => {
      setResults((d.items || []).map((it) => ({ ...it, checked: false })));
    }).catch((e) => console.error("加载结果失败", e));
    // 系统设置"一键清理"后同步清空界面
    const onCleared = () => { setResults([]); setUploads([]); };
    window.addEventListener("cache-cleared", onCleared);
    return () => window.removeEventListener("cache-cleared", onCleared);
  }, []);

  // 新增上传项：先落盘后端（归属当前设备），成功后加入列表（缩略图用后端 URL）
  async function addUploads(files) {
    const list = files.filter((f) => /\.(jpg|jpeg|png|bmp|webp|tif|tiff)$/i.test(f.name || ""));
    if (!list.length) return;
    try {
      const { items } = await uploadImages(list);
      const merged = (items || []).map((it) => ({
        id: it.id, name: it.name, size: 0, status: "待检测", checked: false,
        thumb: `${imgUrl(it.url)}&t=${Date.now()}`, url: it.url,  // 时间戳防缓存（同 URL 复用 → 浏览器显示旧图）
      }));
      // 同名幂等：后端返回已有记录 id，前端按 id 去重，重复文件不再加入列表
      const existIds = new Set(uploads.map((u) => u.id));
      const fresh = merged.filter((m) => !existIds.has(m.id));
      if (fresh.length < merged.length) {
        showToast(t('detect.dupSkipped', { n: merged.length - fresh.length }), "warn");
      }
      setUploads((u) => {
        const seen = new Set(u.map((x) => x.id));
        return [...u, ...fresh.filter((m) => !seen.has(m.id))];
      });
    } catch (e) {
      alert(t('detect.uploadFail', { msg: e.message }));
    }
  }

  // 拖拽上传（单图/多图 + 文件夹，只扫一层）
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

  // 开始检测：勾选了 → 只检测勾选项中未完成的；未勾选 → 检测全部未完成项（已完成自动跳过，不重复检测）
  function startDetect() {
    const pending = uploads.filter((u) => u.status === "待检测" || u.status === "失败");
    const targets = checkedUpIds.length ? pending.filter((u) => checkedUpIds.includes(u.id)) : pending;
    runDetect(targets);
  }

  // 通用检测执行（上传检测 / 结果重检共用；后端流式推送进度；结果图落盘后端）
  async function runDetect(targets) {
    if (!targets.length) return;
    const ac = new AbortController();
    abortRef.current = ac;
    setDetecting(true);
    setProgress({ pct: 2, msg: t('detect.preparing') });
    try {
      const data = await detect(targets.map((t) => t.id), params, (ev) => {
        if (ev.type === "phase" || ev.type === "progress") {
          setProgress({ pct: ev.pct || 0, msg: ev.msg || "" });
        }
      }, ac.signal);
      setProgress(null);
      const ok = data.results.filter((r) => !r.error);
      const fail = data.results.filter((r) => r.error);
      // 更新上传列表状态
      setUploads((us) => us.map((u) => {
        const r = data.results.find((x) => x.file === u.name);
        if (!r) return u;
        return { ...u, status: r.error ? "失败" : "完成" };
      }));
      if (fail.length) alert(t('detect.detectFail', { n: fail.length, list: fail.map((f) => f.file).join("、") }));
      if (ok.length) {
        // 结果已由后端落盘，重新拉取最新列表（含记录 id 与图片 URL）
        const d = await fetchDetectResults();
        setResults((d.items || []).map((it) => ({ ...it, checked: false })));
      }
    } catch (e) {
      if (e && e.name === "AbortError") return; // 用户关闭页面/切换标签而取消，静默退出
      setProgress(null);
      alert(t('detect.detectError', { msg: e.message }));
    } finally {
      setDetecting(false);
      if (abortRef.current === ac) abortRef.current = null;
    }
  }

  // 结果重新检测：从上传列表找同名文件（已落盘后端，刷新后也可用）
  async function recheck(names) {
    const items = names
      .map((n) => uploads.find((u) => u.name === n))
      .filter((u) => u && u.id);
    if (!items.length) {
      alert(t('detect.noFileForRetry'));
      return;
    }
    await runDetect(items);
  }

  // 删除上传项（联动删除后端文件，无落盘）
  async function removeUploads(ids) {
    setUploads((us) => us.filter((u) => !ids.includes(u.id)));
    try { await deleteUploads(ids); } catch (e) { console.error(e); }
  }
  // 上传列表勾选管理
  const checkedUpIds = uploads.filter((u) => u.checked).map((u) => u.id);
  function toggleUpAll(e) {
    setUploads((old) => old.map((u) => ({ ...u, checked: e.target.checked })));
  }
  function toggleUpOne(id) {
    setUploads((old) => old.map((u) => (u.id === id ? { ...u, checked: !u.checked } : u)));
  }
  // 删除结果（按 record_id，联动删除落盘图片，无落盘）
  async function removeResults(recordIds) {
    setResults((old) => old.filter((r) => !recordIds.includes(r.record_id)));
    try { await deleteDetectResults(recordIds); } catch (e) { console.error(e); }
  }

  // 人工修正判定/备注（同步后端 + 同步详情弹窗显示）
  function editResult(file, patch) {
    const item = results.find((r) => r.file === file);
    if (!item) return;
    setResults((old) => old.map((r) => (r.file === file ? { ...r, ...patch } : r)));
    setDetail((d) => (d && d.file === file ? { ...d, ...patch } : d));
    updateDetectResult(item.record_id, patch.manualJud || "", patch.note || "").catch((e) => console.error(e));
  }

  // 单击行：稍延迟打开详情（给双击勾选留识别时间）；双击行：勾选/取消勾选
  const clickTimer = useRef(null);
  function onRowClick(r) {
    clearTimeout(clickTimer.current);
    clickTimer.current = setTimeout(() => setDetail(r), 200);
  }
  function onRowDoubleClick(file) {
    clearTimeout(clickTimer.current);
    toggleOne(file);
  }

  // 统计条
  const stat = useMemo(() => {
    const c = { 是: 0, 不是: 0, 疑似: 0 };
    for (const r of results) {
      const k = r.manualJud || r.jud_simple;
      if (k in c) c[k] += 1;
    }
    return c;
  }, [results]);

  // 筛选 + 排序后的结果
  const shown = useMemo(() => {
    let list = results;
    if (filter !== "全部") list = list.filter((r) => (r.manualJud || r.jud_simple) === filter);
    if (sortKey === "score") list = [...list].sort((a, b) => (b.score || 0) - (a.score || 0));
    if (sortKey === "area") list = [...list].sort((a, b) => (b.area || 0) - (a.area || 0));
    return list;
  }, [results, filter, sortKey]);

  // 勾选管理（按 record_id）
  const checkedNames = shown.filter((r) => r.checked).map((r) => r.file);
  const checkedIds = shown.filter((r) => r.checked).map((r) => r.record_id);
  function toggleAll(e) {
    setResults((old) => old.map((r) =>
      shown.some((s) => s.record_id === r.record_id) ? { ...r, checked: e.target.checked } : r));
  }
  function toggleOne(file) {
    setResults((old) => old.map((r) => (r.file === file ? { ...r, checked: !r.checked } : r)));
  }

  // 有效检测目标：未完成项；勾选时仅限勾选（已完成自动跳过，不重复检测）
  const pendingUploads = uploads.filter((u) => u.status === "待检测" || u.status === "失败");
  const pendTargets = checkedUpIds.length ? pendingUploads.filter((u) => checkedUpIds.includes(u.id)) : pendingUploads;
  // 结果重检：可重检 = 上传列表中能找到对应文件；勾选→重检选中，否则一键重检全部
  const recheckable = results.some((r) => uploads.some((u) => u.name === r.file && u.id));
  const recheckNames = checkedNames.length ? checkedNames : results.map((r) => r.file);

  // 导出菜单：点击空白区域关闭
  useEffect(() => {
    if (!showExportMenu) return;
    const onDoc = (e) => {
      if (exportRef.current && !exportRef.current.contains(e.target)) setShowExportMenu(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [showExportMenu]);

  // URL → base64 dataURL（导出前把后端图片转为可嵌入 Excel 的 base64）
  async function urlToDataUrl(url) {
    if (!url) return null;
    try {
      const r = await fetch(url, { headers: deviceHeaders() });
      if (!r.ok) return null;
      const blob = await r.blob();
      return await new Promise((resolve) => {
        const fr = new FileReader();
        fr.onload = () => resolve(fr.result);
        fr.onerror = () => resolve(null);
        fr.readAsDataURL(blob);
      });
    } catch (_) { return null; }
  }

  // 图片 dataURL 缩放到最大边长（导出前减小请求体；未超限则原样返回）
  function resizeImage(dataUrl, maxSide) {
    return new Promise((resolve) => {
      if (!dataUrl) return resolve(null);
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        if (scale >= 1) return resolve(dataUrl);
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * scale);
        c.height = Math.round(img.height * scale);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        resolve(c.toDataURL("image/jpeg", 0.8));
      };
      img.onerror = () => resolve(dataUrl);
      img.src = dataUrl;
    });
  }

  // 导出：勾选时仅导出勾选结果，否则导出全部
  // 简要 = 列表所有内容（文件名/判定 + 原图/热力图两张图）
  // 详细 = 详情弹窗所有内容（全部指标 + 原图/热力图/分析图三张图）
  async function doExport(mode) {
    if (exporting) return; // 防重复点击
    const selected = checkedIds.length ? results.filter((r) => checkedIds.includes(r.record_id)) : results;
    if (!selected.length) return;
    setExporting(true);
    setShowExportMenu(false);
    try {
      const rows = [];
      for (let i = 0; i < selected.length; i++) {
        const r = selected[i];
        setExportMsg(t('detect.exportProgress', { done: i + 1, total: selected.length }));
        // 后端图片 URL → base64 → 缩放（大图缓存过期时退回缩略图）
        const [orig, heat, analysis] = await Promise.all([
          urlToDataUrl(r.orig || r.thumb || null).then((d) => resizeImage(d, 800)),
          urlToDataUrl(r.heat || null).then((d) => resizeImage(d, 800)),
          urlToDataUrl(r.analysis || null).then((d) => resizeImage(d, 800)),
        ]);
        if (mode === "brief") {
          rows.push({ file: r.file, jud: r.manualJud || r.jud_simple, orig, heat });
        } else {
          rows.push({
            file: r.file, jud: r.manualJud || r.jud_simple, jud_orig: r.jud || "",
            src: r.src || "", score: r.score, level: r.level, area: r.area, peak: r.peak, conf: r.conf,
            param: t('detect.presetFormat', { preset: params.preset || "默认", threshold: params.threshold }),
            note: r.note || "", orig, heat, analysis,
          });
        }
      }
      setExportMsg(t('detect.exportDownloading'));
      await exportExcel(mode, rows);
    } catch (e) {
      alert(t('detect.exportFail', { msg: e.message }));
    } finally {
      setExporting(false);
      setExportMsg("");
    }
  }

  return (
    <div className="detect">
      {/* 页头：功能名 + 右上角调参入口（仅对本功能生效） */}
      <div className="page-head">
        <div className="page-title">{t('detect.title')}</div>
        <button className="btn small" onClick={() => setShowSettings(true)}>⚙ {t('detect.params')}</button>
      </div>

      {/* 上传区 */}
      <div className="upload-zone" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
        <div className="upload-hint">{t('detect.dropHint')}</div>
        <div className="upload-btns">
          <button className="btn" onClick={() => fileInput.current && fileInput.current.click()}>{t('detect.selectImage')}</button>
          <button className="btn" onClick={() => dirInput.current && dirInput.current.click()}>{t('detect.selectFolder')}</button>
        </div>
        <input ref={fileInput} type="file" multiple accept="image/*" style={{ display: "none" }}
               onChange={(e) => { addUploads([...e.target.files]); e.target.value = ""; }} />
        <input ref={dirInput} type="file" webkitdirectory="" directory="" multiple style={{ display: "none" }}
               onChange={(e) => { addUploads([...e.target.files]); e.target.value = ""; }} />
        <div className="upload-formats">{t('detect.formatHint')}</div>
      </div>

      {/* 上传列表 */}
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title">{t('detect.uploadList', { n: uploads.length })}</span>
          <div className="panel-ops">
            {/* 勾选后按钮自动变换语义：清空↔清除选中 / 开始检测↔检测选中 */}
            <button className="btn small"
                    onClick={() => removeUploads(checkedUpIds.length ? checkedUpIds : uploads.map((u) => u.id))}>
              {checkedUpIds.length ? t('detect.clearSelected') : t('detect.clearAll')}
            </button>
            <button className="btn primary" disabled={detecting || !pendTargets.length} onClick={startDetect}>
              {detecting ? t('detect.detecting') : (checkedUpIds.length ? t('detect.detectSelected') : '▶ ' + t('detect.startDetect'))}
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
                <th style={{ width: 70 }}>{t('detect.thumb')}</th><th>{t('detect.fileName')}</th><th style={{ width: 90 }}>{t('detect.fileSize')}</th><th style={{ width: 100 }}>{t('detect.status')}</th>
              </tr>
            </thead>
            <tbody>
              {uploads.map((u) => (
                <tr key={u.id} className={u.checked ? "row-checked" : ""}
                    onDoubleClick={(e) => {
                      // 双击行勾选/取消（排除勾选列，避免与复选框交互冲突）
                      const td = e.target.closest("td");
                      if (td && td.classList.contains("check-cell")) return;
                      toggleUpOne(u.id);
                    }}>
                  <td className="check-cell"><input type="checkbox" checked={!!u.checked} onChange={() => toggleUpOne(u.id)} /></td>
                  <td>{u.thumb ? <img src={u.thumb} alt="" className="thumb" /> : <div className="thumb thumb-ph">{t('detect.placeholder')}</div>}</td>
                  <td className="cell-name">{u.name}</td>
                  <td>-</td>
                  <td><span className={`status ${u.status}`}>{u.status === '待检测' ? t('detect.pending') : u.status === '失败' ? t('detect.failed') : u.status === '完成' ? t('detect.done') : u.status}</span></td>
                </tr>
              ))}
              {!uploads.length && <tr><td colSpan={5} className="empty">{t('detect.noUploads')}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* 结果列表 */}
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title">{t('detect.resultList', { n: results.length })}</span>
          {results.length > 0 && (
            <span className="stat">
              {t('detect.stats', { yes: stat["是"], no: stat["不是"], sus: stat["疑似"] })}
            </span>
          )}
          <div className="panel-ops">
            <Dropdown value={filter} options={[t('detect.filterAll'), t('detect.filterYes'), t('detect.filterNo'), t('detect.filterSus')]} onChange={setFilter} />
            <Dropdown value={sortKey} className="dd-sort"
                      options={[{ label: t('detect.sortDefault'), value: "" }, { label: t('detect.sortProb'), value: "score" }, { label: t('detect.sortArea'), value: "area" }]}
                      onChange={setSortKey} />
            {/* 勾选→删除选中，否则一键清空全部结果 */}
            <button className="btn small" disabled={!results.length}
                    onClick={() => removeResults(checkedIds.length ? checkedIds : results.map((r) => r.record_id))}>
              {checkedNames.length ? t('detect.deleteSelected') : t('detect.clearResult')}
            </button>
            {/* 勾选→重检选中，否则一键重检全部 */}
            <button className="btn small" disabled={detecting || !recheckable}
                    onClick={() => recheck(recheckNames)}>
              {checkedNames.length ? t('detect.reVerifySelected') : t('detect.reVerifyAll')}
            </button>
            <div className="export-wrap" ref={exportRef}>
              {/* 勾选后按钮自动切换为"导出选中表格"；导出中禁用防重复下载 */}
              <button className="btn primary" disabled={exporting} onClick={() => setShowExportMenu(!showExportMenu)}>
                {exporting ? t('detect.exporting') : (checkedNames.length ? t('detect.exportSelected') : t('detect.export'))}
              </button>
              {exportMsg && <span className="dim">{exportMsg}</span>}
              {showExportMenu && (
                <div className="export-menu">
                  <div onClick={() => doExport("brief")}>{t('detect.exportBrief')}</div>
                  <div onClick={() => doExport("detail")}>{t('detect.exportDetail')}</div>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="table-wrap result-table">
          <table>
            <thead>
              <tr>
                <th style={{ width: 40 }}><input type="checkbox" onChange={toggleAll}
                    checked={shown.length > 0 && shown.every((r) => r.checked)} /></th>
                <th>{t('detect.colFile')}</th><th className="th-center" style={{ width: 84 }}>{t('detect.colOriginal')}</th><th className="th-center" style={{ width: 84 }}>{t('detect.colHeatmap')}</th>
                <th className="th-center" style={{ width: 110 }}>{t('detect.colJudgment')}</th><th className="th-center" style={{ width: 150 }}>{t('detect.colAction')}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.record_id} className={r.checked ? "row-checked" : ""}
                    onClick={() => onRowClick(r)}
                    onDoubleClick={(e) => {
                      // 双击行勾选/取消（排除勾选列与操作列，避免与复选框/按钮交互冲突）
                      const td = e.target.closest("td");
                      if (td && (td.classList.contains("check-cell") || td.classList.contains("cell-ops"))) return;
                      onRowDoubleClick(r.file);
                    }}>
                  {/* 勾选列：整列点击均视为选中，不触发打开详情 */}
                  <td className="check-cell" onClick={(e) => { e.stopPropagation(); toggleOne(r.file); }}>
                    <input type="checkbox" checked={!!r.checked} readOnly />
                  </td>
                  <td className="cell-name" title={r.file}>{r.file}</td>
                  <td><img src={imgUrl(r.thumb)} alt="" className="thumb" /></td>
                  <td><img src={imgUrl(r.heat)} alt="" className="thumb heat" /></td>
                  <td className="jud-cell">
                    {r.manualJud && r.manualJud !== r.jud_simple
                      ? <span className="jud-manual">{r.manualJud}</span>
                      : <span className="jud-text">{r.jud_simple}</span>}
                  </td>
                  <td className="cell-ops">
                    <button className="btn small btn-view" onClick={(e) => { e.stopPropagation(); setDetail(r); }}>{t('detect.view')}</button>
                    <button className="btn small btn-recheck" disabled={!uploads.some((u) => u.name === r.file && u.id)}
                            onClick={(e) => { e.stopPropagation(); recheck([r.file]); }}>{t('detect.reVerify')}</button>
                  </td>
                </tr>
              ))}
              {!shown.length && <tr><td colSpan={6} className="empty">{t('detect.noResults')}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* 详情弹窗 */}
      {detail && <DetailModal item={detail} params={params} onEdit={editResult} onClose={() => setDetail(null)} />}

      {/* 检测参数弹窗（预设 + 高级参数，仅影响本功能检测） */}
      {showSettings && (
        <SettingsModal
          params={params}
          onChange={setParams}
          onClose={() => setShowSettings(false)}
        />
      )}

      {/* 轻提示（右下角，自动消失） */}
      {toast && (
        <div className={`toast toast-${toast.type}`}>
          {toast.type === "success" ? "✓ " : toast.type === "error" ? "✕ " : toast.type === "warn" ? "! " : ""}
          {toast.msg}
        </div>
      )}
    </div>
  );
}

// 详情弹窗（图片为后端 URL）
function DetailModal({ item, params, onEdit, onClose }) {
  const { t } = useTranslation();
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t('detect.detailTitle')}</span>
          <button className="btn small" onClick={onClose}>✕</button>
        </div>
        <div className="detail-imgs">
          <div className="detail-img">
            <div className="detail-label">{t('detect.origImage')}</div>
            {item.orig ? <img src={imgUrl(item.orig)} alt="" /> : <div className="expired">{t('detect.origExpired')}</div>}
            </div>
            <div className="det-detail-img">
              <div className="det-detail-label">{t('detect.heatmap')}</div>
            {item.heat ? <img src={imgUrl(item.heat)} alt="" /> : <div className="expired">{t('detect.analysisNA')}</div>}
            </div>
            <div className="det-detail-img">
              <div className="det-detail-label">{t('detect.analysis')}</div>
            {item.analysis ? <img src={imgUrl(item.analysis)} alt="" /> : <div className="expired">{t('detect.analysisNA')}</div>}
          </div>
        </div>
        <div className="detail-info">
          <div className="detail-row"><span>{t('detect.fileNameLabel')}</span><b>{item.file}</b></div>
          <div className="detail-row"><span>{t('detect.judgmentLabel')}</span>
            <Dropdown value={item.manualJud || item.jud_simple} options={[t('detect.filterYes'), t('detect.filterNo'), t('detect.filterSus')]}
                      onChange={(v) => onEdit(item.file, { manualJud: v })} />
            {item.manualJud && item.manualJud !== item.jud_simple && <span className="badge">{t('detect.fixed')}</span>}
            <span className="dim">{t('detect.origModel', { jud: item.jud })}</span>
          </div>
          <div className="detail-row"><span>{t('detect.judgeSource')}</span><b>{item.src}</b></div>
          <div className="detail-row"><span>{t('detect.tamperProb')}</span><b>{item.score}</b></div>
          <div className="detail-row"><span>{t('detect.tamperLevel')}</span><b>{item.level}</b></div>
          <div className="detail-row"><span>{t('detect.areaRatio')}</span><b>{item.area}</b></div>
          <div className="detail-row"><span>{t('detect.tamperPeak')}</span><b>{item.peak}</b></div>
          <div className="detail-row"><span>{t('detect.confidenceLabel')}</span><b>{item.conf}</b></div>
          <div className="detail-row"><span>{t('detect.judgeParams')}</span><b className="dim">{t('detect.presetFormat', { preset: params.preset || "默认", threshold: params.threshold })}</b></div>
          <div className="detail-row"><span>{t('detect.noteLabel')}</span>
            <input className="note-input" placeholder={t('detect.notePlaceholder')} defaultValue={item.note || ""}
                   onBlur={(e) => onEdit(item.file, { note: e.target.value })} />
          </div>
        </div>
      </div>
    </div>
  );
}
