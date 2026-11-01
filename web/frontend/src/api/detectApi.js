// 后端 API 封装（相对路径 /api，经 Vite 代理转发到 FastAPI @ 127.0.0.1:8000；
// 本地与 cpolar 公网访问均可用，避免绝对地址在外部访问时指向访问者本机/混合内容被拦截）
// 所有请求携带 X-Device-Id（游客设备标识），后端按设备隔离数据；JSON 响应统一 {code,msg,data}
import { request } from "./index.js";
import { deviceHeaders } from "./deviceId.js";

export const API_BASE = "";

// 拉取默认参数/预设/参数说明
export async function fetchParams() {
  return request(`${API_BASE}/api/params`);
}

// 批量检测（流式）：uploadIds=已上传图片 id[]，params=对象(预设+高级参数)；signal 可中途取消（关页面/切标签）；
// onProgress 接收 {type:'phase'|'progress', pct, msg, done, total} 进度事件，返回 {results:[...]}
// 注意：/api/detect 为 NDJSON 流式响应（不包装），此函数保持手动解析，不走 request()
export async function detect(uploadIds, params, onProgress, signal) {
  const r = await fetch(`${API_BASE}/api/detect`, {
    method: "POST",
    headers: { ...deviceHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ upload_ids: uploadIds, params: params || {} }),
    signal,
  });
  if (!r.ok) {
    let msg = "检测失败";
    try {
      const d = await r.json();
      msg = (d && (d.msg || d.detail)) || msg; // 异常响应为 {code,msg,data}
    } catch (_) {}
    throw new Error(msg);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let doneEv = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      let ev;
      try { ev = JSON.parse(line); } catch (_) { continue; }
      if (ev.type === "done") doneEv = ev;
      else if (onProgress) onProgress(ev);
    }
  }
  if (!doneEv) throw new Error("检测中断：未收到结果");
  return { results: doneEv.results || [] };
}

// 导出 Excel：mode='brief'|'detail'，rows=结果数组（binary 下载，不包装，保持现有行为）
export async function exportExcel(mode, rows) {
  const r = await fetch(`${API_BASE}/api/export`, {
    method: "POST",
    headers: { ...deviceHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ mode, rows }),
  });
  if (!r.ok) {
    let msg = "导出失败";
    try { const d = await r.json(); msg = (d && d.msg) || msg; } catch (_) {}
    throw new Error(msg);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "TruFor检测结果.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}

// 一键清理后端历史临时文件
export async function cleanupTmp() {
  return request(`${API_BASE}/api/cleanup`, { method: "POST" });
}

// ==================== 游客设备隔离：上传图 / 结果记录 CRUD ====================

// 上传图片落盘（归属当前设备），返回 {items:[{id,name,url}]}
export async function uploadImages(files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  return request(`${API_BASE}/api/detect/upload`, { method: "POST", body: fd });
}
// 当前设备上传列表（刷新后恢复）
export async function fetchUploads() {
  return request(`${API_BASE}/api/detect/uploads`);
}
// 删除上传图片（联动删除文件，无落盘）
export async function deleteUploads(ids) {
  return request(`${API_BASE}/api/detect/uploads/delete`, { method: "POST", body: { ids } });
}
// 当前设备结果列表
export async function fetchDetectResults() {
  return request(`${API_BASE}/api/detect/results`);
}
// 人工修正判定 / 备注
export async function updateDetectResult(recordId, manualJud, note) {
  return request(`${API_BASE}/api/detect/results/update`, {
    method: "POST",
    body: { record_id: recordId, manual_jud: manualJud, note: note || "" },
  });
}
// 删除结果（联动删除图片文件，无落盘）
export async function deleteDetectResults(ids) {
  return request(`${API_BASE}/api/detect/results/delete`, { method: "POST", body: { ids } });
}
// 清空当前设备全部结果与上传图
export async function clearDetectAll() {
  return request(`${API_BASE}/api/detect/results/clear`, { method: "POST" });
}
// 当前设备占用统计（供系统设置展示）
export async function fetchDetectStats() {
  return request(`${API_BASE}/api/detect/stats`);
}

// 模型管理器状态：GPU 显存 + 常驻/子进程模型占用（供系统设置实时展示）
export async function fetchModelStatus() {
  return request(`${API_BASE}/api/models`);
}
