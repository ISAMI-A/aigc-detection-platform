// 系统管理 API（批次5，仅 admin 调用；401/403 由 request() 抛错）
import { request } from "./index.js";

function qs(params = {}) {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, v);
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const adminApi = {
  overview: () => request("/api/admin/overview"),
  users: (params) => request(`/api/admin/users${qs(params)}`),
  createUser: (d) => request("/api/admin/users", { method: "POST", body: d }),
  toggleUser: (id) => request(`/api/admin/users/${id}/toggle`, { method: "POST" }),
  resetPassword: (id, password) =>
    request(`/api/admin/users/${id}/reset_password`, { method: "POST", body: { password } }),
  setRole: (id, role) => request(`/api/admin/users/${id}/role?role=${role}`, { method: "POST" }),
  deleteUser: (id) => request(`/api/admin/users/${id}`, { method: "DELETE" }),
  features: () => request("/api/admin/features"),
  setFeature: (name, enabled) =>
    request(`/api/admin/features/${name}`, { method: "PUT", body: { enabled } }),
  announcements: () => request("/api/admin/announcements"),
  createAnnouncement: (d) => request("/api/admin/announcements", { method: "POST", body: d }),
  updateAnnouncement: (id, d) => request(`/api/admin/announcements/${id}`, { method: "PUT", body: d }),
  deleteAnnouncement: (id) => request(`/api/admin/announcements/${id}`, { method: "DELETE" }),
  logs: (params) => request(`/api/admin/logs${qs(params)}`),
  clearLogs: () => request("/api/admin/logs", { method: "DELETE" }),
  // 数据管理：三级清理
  dataStats: () => request("/api/admin/data"),
  clearFiles: () => request("/api/admin/data/clear_files", { method: "POST" }),
  clearConfig: () => request("/api/admin/data/clear_config", { method: "POST" }),
  clearAll: () => request("/api/admin/data/clear_all", { method: "POST" }),
};
