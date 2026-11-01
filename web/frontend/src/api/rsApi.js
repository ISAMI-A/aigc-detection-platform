// 遥感变化核验子系统 API（FastAPI 子应用，主应用挂载在 /rsverify 前缀下）
// 使用相对路径：开发环境由 vite proxy 转发到后端，构建后同源直达
// 所有请求携带 X-Device-Id（游客设备标识），后端按设备隔离数据；JSON 响应统一 {code,msg,data}

import { getDeviceId } from "./deviceId.js";
import { request, imgUrl } from "./index.js";

const BASE = "/rsverify/api";

function get(path) { return request(`${BASE}${path}`); }
function post(path, body) { return request(`${BASE}${path}`, { method: "POST", body }); }
function del(path) { return request(`${BASE}${path}`, { method: "DELETE" }); }

export const rsApi = {
  // 上传一对图片（before=旧时/整改前, after=现在/整改后），返回 {before:{id,filename}, after:{id,filename}}
  async upload(beforeFile, afterFile, scenario = "detect") {
    const fd = new FormData();
    if (beforeFile) fd.append("before", beforeFile);
    if (afterFile) fd.append("after", afterFile);
    fd.append("scenario", scenario);
    return request(`${BASE}/upload`, { method: "POST", body: fd });
  },
  // 触发一次分析（阻塞约 30-60s）
  analyze(beforeId, afterId, scenario) {
    return post("/analyze", { before_id: beforeId, after_id: afterId, scenario });
  },
  // 上传单张图片（支持 position: before/after/single），按场景隔离
  async uploadSingle(file, position = "single", scenario = "detect") {
    const fd = new FormData();
    fd.append("image", file);
    fd.append("scenario", scenario);
    return request(`${BASE}/upload-single?position=${position}`, { method: "POST", body: fd });
  },
  // 四乱核验：单图检测分析（classify 场景）
  analyzeSingle(imageId) {
    return post("/analyze", { image_id: imageId, scenario: "classify" });
  },
  // 重新核验单条结果（用原图重新分析并覆盖该记录）
  rerun(recordId) { return post(`/analyze/${recordId}/rerun`); },
  // 结果列表（新→旧）
  results() { return get("/results"); },
  // 数据统计 / 重置（供系统设置全局清理）
  stats() { return get("/stats"); },
  reset() { return post("/reset"); },
  // 删除单条 / 批量删除（ids 为空=全部）
  deleteResult(id) { return del(`/results/${id}`); },
  deleteBatch(ids) { return post("/results/batch-delete", { ids: ids || [] }); },
  // 删除上传图片（未被分析记录引用时；核验失败清理用）
  deleteImage(id) { return del(`/images/${id}`); },
  // 标注图 URL：<img> 无法带请求头，URL 携带 dev（游客设备隔离）+ token（登录跨设备，B135）
  imageUrl(id) { return imgUrl(`${BASE}/images/${id}?dev=${getDeviceId()}`); },
  // 上传原图 URL（上传面板缩略图用）
  uploadImageUrl(id) { return imgUrl(`${BASE}/uploads/${id}?dev=${getDeviceId()}`); },
  // 当前设备已上传图片列表（按场景隔离，上传面板刷新后从后端恢复）
  getUploadedImages(scenario = "") { return get(`/images/list?scenario=${scenario}`); },
  // 功能页面设置（预设平台存数据库）
  getSettings() { return get("/settings"); },
  saveSettings(payload) { return post("/settings", payload); },
  // 预设平台 CRUD（数据库存储，非写死）
  getPresets() { return get("/presets"); },
  createPreset(payload) { return post("/presets", payload); },
  updatePreset(id, payload) { return post(`/presets/${id}`, payload); },
  deletePreset(id) { return del(`/presets/${id}`); },
  activatePreset(id) { return post(`/presets/${id}/activate`); },
  // 手动刷新本地 Ollama 已安装模型列表（本地模型页"获取模型"按钮）
  fetchLocalModels() { return get("/local/models"); },
  // 导出 Excel（ids 为空=全部；binary 下载，不包装，返回 Response 供前端下载）
  exportExcel(ids) {
    return request(`${BASE}/export/excel`, { method: "POST", body: { ids: ids || null } });
  },
};
