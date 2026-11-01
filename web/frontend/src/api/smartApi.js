// 点位真实性核验子系统 API（FastAPI 子应用，主应用挂载在 /smart 前缀下）
// 使用相对路径：开发环境由 vite proxy 转发到后端，构建后同源直达
// 所有请求携带 X-Device-Id（游客设备标识），后端按设备隔离数据；JSON 响应统一 {code,msg,data}

import { getDeviceId } from "./deviceId.js";
import { request, imgUrl } from "./index.js";

const BASE = "/smart/api";

function get(path) { return request(`${BASE}${path}`); }
function post(path, body) { return request(`${BASE}${path}`, { method: "POST", body }); }
function put(path, body) { return request(`${BASE}${path}`, { method: "PUT", body }); }
function del(path) { return request(`${BASE}${path}`, { method: "DELETE" }); }

export const smartApi = {
  // 上传（left=整改图, right=暗访图），返回左右已保存记录
  async upload(leftFiles, rightFiles) {
    const fd = new FormData();
    for (const f of leftFiles || []) fd.append("left_files", f);
    for (const f of rightFiles || []) fd.append("right_files", f);
    return request(`${BASE}/upload`, { method: "POST", body: fd });
  },
  // 上传单张图片（支持 photo_type: 整改图/暗访图），返回 {image:{id,filename}}
  async uploadSingle(file, photoType = "整改图") {
    const fd = new FormData();
    fd.append("image", file);
    return request(`${BASE}/upload-single?photo_type=${encodeURIComponent(photoType)}`, { method: "POST", body: fd });
  },
  pair(mode, leftIds, rightIds) {
    return post(`/pair/${mode}`, { left_ids: leftIds, right_ids: rightIds });
  },
  verifySingle(pairId) { return post(`/verify/single/${pairId}`); },
  verifyBatch() { return post("/verify/batch"); },
  verifySelected(pairIds) { return post("/verify/selected", { pair_ids: pairIds }); },
  progress() { return get("/verify/progress"); },
  results() { return get("/results?page=1&page_size=500"); },
  detail(resultId) { return get(`/results/${resultId}/detail`); },
  manualFix(resultId, isSame, note) { return put(`/results/${resultId}/manual`, { is_same: isSame, note }); },
  humanJudgment(resultId, isSame) { return put(`/results/${resultId}/human-judgment`, { is_same: isSame }); },
  imagesList() { return get("/images/list"); },
  deleteImage(imageId) { return del(`/images/${imageId}`); },
  deletePair(pairId) { return del(`/pairs/${pairId}`); },
  deletePairs(pairIds) { return post("/pairs/batch-delete", { pair_ids: pairIds }); },
  reset() { return post("/reset"); },
  stats() { return get("/stats"); },
  // 导出 Excel：pairIds 为空导出全部，否则只导出选中配对（POST，可嵌图；binary 下载，不包装）
  exportExcel(pairIds) {
    return request(`${BASE}/export/excel`, { method: "POST", body: { pair_ids: pairIds || null } });
  },
  // 图片 URL：<img> 无法带请求头，URL 携带 dev（游客设备隔离）+ token（登录跨设备，B135）
  imageUrl(id) { return imgUrl(`${BASE}/images/${id}?dev=${getDeviceId()}`); },
  visUrl(resultId) { return imgUrl(`${BASE}/visualization/${resultId}?dev=${getDeviceId()}`); },
};
