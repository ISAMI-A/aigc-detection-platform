// 人脸识别接口封装（/face/api 前缀，经 vite proxy 转发到后端 8000）
import { request, getToken } from "./index.js";
import { deviceHeaders } from "./deviceId.js";

const BASE = "/face/api";

// ==================== 上传 ====================

// 批量上传图片（同名幂等：后端已有直接复用记录）
export async function uploadImages(files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  return request(`${BASE}/upload`, { method: "POST", body: fd });
}

// 上传列表（刷新恢复；status=pending/done/no_face/error）
export async function fetchUploads() {
  return request(`${BASE}/uploads`);
}

// 删除上传图（ids 空=全部；联动删识别结果）
export async function deleteUploads(ids) {
  return request(`${BASE}/uploads/delete`, { method: "POST", body: { ids: ids || [] } });
}

// ==================== 识别（NDJSON 流式） ====================

// 批量识别：逐图推送 onProgress({type:'phase'|'progress', pct, msg})，完成返回 {results}
export async function recognize(uploadIds, onProgress, signal) {
  const r = await fetch(`${BASE}/recognize`, {
    method: "POST",
    headers: { ...deviceHeaders(), Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
    body: JSON.stringify({ upload_ids: uploadIds }),
    signal,
  });
  if (!r.ok) {
    let msg = "识别失败";
    try {
      const d = await r.json();
      msg = (d && (d.msg || d.detail)) || msg;
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
  if (!doneEv) throw new Error("识别中断：未收到结果");
  return { results: doneEv.results || [] };
}

// ==================== 结果 ====================

// 结果列表（一行=一张脸）
export async function fetchResults() {
  return request(`${BASE}/results`);
}

// 结果详情（Top-K 候选 + 512 维特征 + 阈值）
export async function fetchResultDetail(id) {
  return request(`${BASE}/results/${id}/detail`);
}

// 人工标注入库：need_confirm 时返回 {need_confirm, conflict}；确认后带 mode=overwrite/new
export async function manualSave(resultId, name, mode = "") {
  return request(`${BASE}/results/manual_save`, {
    method: "POST", body: { result_id: resultId, name, mode },
  });
}

// 删除结果（ids 空=全部）
export async function deleteResults(ids) {
  return request(`${BASE}/results/delete`, { method: "POST", body: { ids: ids || [] } });
}

// 导出 Excel（ids 空=全部；返回 blob 直接下载）
export async function exportExcel(ids) {
  const r = await fetch(`${BASE}/export`, {
    method: "POST",
    headers: { ...deviceHeaders(), Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
    body: JSON.stringify({ ids: ids || [] }),
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
  a.download = "人脸识别结果.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}

// ==================== 个人资料 · 人脸录入 ====================

export async function fetchProfileFace() {
  return request(`${BASE}/profile_face`);
}

// 录入/更新（mode：""=先查重 / overwrite=改名+补样本 / new=独立新人员）
export async function saveProfileFace(file, name, mode = "") {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("name", name);
  fd.append("mode", mode);
  return request(`${BASE}/profile_face`, { method: "POST", body: fd });
}

export async function deleteProfileFace() {
  return request(`${BASE}/profile_face`, { method: "DELETE" });
}

// ==================== 人脸登录 ====================

// 上传照片人脸登录
export async function loginByFace(file) {
  const fd = new FormData();
  fd.append("file", file);
  return request(`${BASE}/login_face`, { method: "POST", body: fd });
}

// 摄像头帧人脸登录（base64 dataURL）
export async function loginByFaceFrame(dataUrl) {
  return request(`${BASE}/login_face_frame`, { method: "POST", body: { image: dataUrl } });
}

// ==================== admin · 人脸库管理 ====================

export async function fetchLibrary(q = "", page = 1, size = 20) {
  return request(`${BASE}/library?q=${encodeURIComponent(q)}&page=${page}&size=${size}`);
}

// admin 新增人员（查重同 manual_save：need_confirm 或 status ok）
export async function libraryAdd(file, name, mode = "") {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("name", name);
  fd.append("mode", mode);
  return request(`${BASE}/library`, { method: "POST", body: fd });
}

export async function libraryRename(recordId, name) {
  return request(`${BASE}/library/rename`, { method: "POST", body: { record_id: recordId, name } });
}

export async function libraryPhoto(recordId, file) {
  const fd = new FormData();
  fd.append("record_id", recordId);
  fd.append("file", file);
  return request(`${BASE}/library/photo`, { method: "POST", body: fd });
}

export async function libraryDelete(ids) {
  return request(`${BASE}/library`, { method: "DELETE", body: { ids: ids || [] } });
}

// ==================== 统计 ====================

export async function fetchFaceStats() {
  return request(`${BASE}/stats`);
}

// 重置（清空当前归属的识别数据；不动全局人脸库）
export async function resetFace() {
  return request(`${BASE}/reset`, { method: "POST" });
}
