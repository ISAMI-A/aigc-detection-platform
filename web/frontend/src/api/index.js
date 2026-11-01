// 统一 API 请求封装（批次1：接口统一响应格式 {code, msg, data}；批次4：登录态）
// - 自动携带 X-Device-Id（游客设备隔离）+ Authorization（登录 token，localStorage）
// - JSON 响应自动解包：{code, msg, data} → 返回 data（code!=0 抛 Error(msg)）
// - 401（token 失效且曾登录）→ 派发 auth-expired 事件（外层清理登录态回退游客）
// - 非 JSON 响应（NDJSON 流式 / 图片 / Excel 下载）原样返回 Response，保持现有行为
import { deviceHeaders } from "./deviceId.js";

export const TOKEN_KEY = "aigc_token";

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; }
}
export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (_) {}
}

// 供 <img>/<a> 使用的图片/下载 URL：登录态在 query 追加明文 token（img 无法带 header，
// B135 沿用 chat 的 ?token= 模式），游客无 token 原样返回（仍走 ?dev= 设备隔离）。
export function imgUrl(url, token = getToken()) {
  if (!token || !url) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

export async function request(path, { method = "GET", body, headers, signal } = {}) {
  const h = { ...deviceHeaders(), ...(headers || {}) };
  const token = getToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  let payload = body;
  // body 为对象时自动 JSON 序列化（FormData 除外，浏览器自动带 boundary）
  if (body !== undefined && !(body instanceof FormData) && !h["Content-Type"]) {
    h["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const r = await fetch(path, { method, headers: h, body: payload, signal });
  const ct = r.headers.get("content-type") || "";
  if (!ct.includes("application/json")) return r; // 流式/二进制：原样返回
  let json;
  try { json = await r.json(); } catch (_) { return r; }
  // 统一格式：code!=0 抛业务错误（401/507 等文案即 msg）
  if (json && typeof json === "object" && "code" in json && "msg" in json) {
    if (json.code !== 0) {
      // token 失效（曾登录才需要处理，纯游客 401 不触发）
      if (json.code === 401 && token) {
        window.dispatchEvent(new CustomEvent("auth-expired"));
      }
      throw new Error(json.msg || `请求失败 (${r.status})`);
    }
    return json.data;
  }
  // 兜底：旧格式 /detail 或非预期结构
  if (!r.ok) throw new Error(typeof json.detail === "string" ? json.detail : `请求失败 (${r.status})`);
  return json;
}
