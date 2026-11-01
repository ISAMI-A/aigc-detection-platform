// 通知中心 · 聊天/好友/公告 API（仅登录用户；401 由 request() 抛错回退游客）
// 图片/zip 供 <img>/<a> 使用：URL 带 ?token=（<img>/<a> 无法带 header），后端校验
import { request, getToken } from "./index.js";

function qs(params = {}) {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, v);
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// 聊天文件（图片预览 zip 下载）URL；token 放 query 供 img/a 直接访问
export function chatFileUrl(msgId) {
  return `/api/chat/file/${msgId}?token=${encodeURIComponent(getToken() || "")}`;
}

// 全局聊天状态刷新事件：铃铛/通知中心任一端发生读已读/发送/清理/好友变更后广播，
// 两端同时刷新，避免"一个快一个慢"的未读红点/通知不同步
export const CHAT_REFRESH = "chat-refresh";

export const chatApi = {
  // 好友搜索 / 申请
  search: (q) => request(`/api/chat/search${qs({ q })}`),
  sendRequest: (receiverId) =>
    request("/api/chat/request", { method: "POST", body: { receiver_id: receiverId } }),
  requests: () => request("/api/chat/requests"),
  handleRequest: (id, action) =>
    request(`/api/chat/request/${id}/handle`, { method: "POST", body: { action } }),
  friends: () => request("/api/chat/friends"),
  deleteFriend: (id) => request(`/api/chat/friend/${id}`, { method: "DELETE" }),
  // 会话
  conversations: () => request("/api/chat/conversations"),
  setPin: (peer, pinned) =>
    request(`/api/chat/conversation/${peer}/pin`, { method: "POST", body: { pinned } }),
  deleteConversation: (peer) =>
    request(`/api/chat/conversation/${peer}`, { method: "DELETE" }),
  markUnread: (peer) =>
    request(`/api/chat/conversation/${peer}/unread`, { method: "POST" }),
  // 消息
  messages: (peer, { before_id = 0, limit = 20 } = {}) =>
    request(`/api/chat/messages${qs({ peer, before_id, limit })}`),
  send: (peer, msg_type, content) =>
    request("/api/chat/send", { method: "POST", body: { peer_id: peer, msg_type, content } }),
  sendFile: (peer, file) => {
    const fd = new FormData();
    fd.append("peer_id", String(peer));
    fd.append("file", file);
    return request("/api/chat/send_file", { method: "POST", body: fd });
  },
  // 待发附件（两段式发送）
  uploadPending: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/chat/pending/upload", { method: "POST", body: fd });
  },
  deletePending: (id) => request(`/api/chat/pending/${id}`, { method: "DELETE" }),
  sendPending: (peer, ids) =>
    request("/api/chat/pending/send", { method: "POST", body: { peer_id: peer, ids } }),
  // 公告
  notices: () => request("/api/chat/notices"),
  markNoticesRead: (annId) =>
    request("/api/chat/notices/read", { method: "POST", body: { ann_id: annId } }),
  // 概览 / 独立清理
  summary: () => request("/api/chat/summary"),
  stats: () => request("/api/chat/stats"),
  clear: () => request("/api/chat/clear", { method: "POST" }),
};