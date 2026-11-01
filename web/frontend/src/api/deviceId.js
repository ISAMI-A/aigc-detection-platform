// 游客设备标识（浏览器缓存级）：localStorage 持久化，本浏览器唯一
// 语义：游客身份 = 本浏览器本缓存；换浏览器 / 清缓存 = 新游客
// 所有后端请求经 X-Device-Id 头携带，用于游客数据隔离（登录体系上线后改按账号）
const KEY = "aigc_device_id";

export function getDeviceId() {
  let id = "";
  try { id = localStorage.getItem(KEY) || ""; } catch (_) {}
  if (!id) {
    id = (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : `d-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    try { localStorage.setItem(KEY, id); } catch (_) {}
  }
  return id;
}

// 统一的请求头（供各 API 模块 fetch 使用）
export function deviceHeaders() {
  return { "X-Device-Id": getDeviceId() };
}
