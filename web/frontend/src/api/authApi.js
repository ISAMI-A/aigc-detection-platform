// 登录体系 API 封装（批次4：登录/注册/验证码/改密/绑邮箱/导出/登出/me）
// 走统一 request()：自动带 X-Device-Id + Authorization；解包 {code,msg,data}
import { request } from "./index.js";

export const authApi = {
  // 注册：用户名+密码必选；邮箱可选（填邮箱需验证码）
  register: (data) => request("/api/auth/register", { method: "POST", body: data }),
  // 用户名+密码登录
  login: (data) => request("/api/auth/login", { method: "POST", body: data }),
  // 邮箱+验证码免密登录
  loginEmail: (data) => request("/api/auth/login_email", { method: "POST", body: data }),
  // 发送验证码：purpose=register|login|reset|bind
  sendCode: (data) => request("/api/auth/send_code", { method: "POST", body: data }),
  // 忘记密码（邮箱验证码重置）
  forgot: (data) => request("/api/auth/forgot", { method: "POST", body: data }),
  // 修改密码（需旧密码；成功后全部 token 失效）
  changePassword: (data) => request("/api/auth/change_password", { method: "POST", body: data }),
  // 绑定/更换邮箱（需登录 + purpose=bind 验证码）
  bindEmail: (data) => request("/api/auth/bind_email", { method: "POST", body: data }),
  // 更换邮箱第一步：校验旧邮箱验证码（确认本人操作）
  verifyOldEmail: (data) => request("/api/auth/verify_old_email", { method: "POST", body: data }),
  // 退出登录（仅失效当前设备 token）
  logout: () => request("/api/auth/logout", { method: "POST" }),
  // 当前用户信息（含 must_change_password）
  me: () => request("/api/auth/me"),
  // 导出我的数据（账号信息 + 三系统记录摘要 JSON）
  exportData: () => request("/api/auth/export"),
  // 完整备份（zip：JSON + 图片）与恢复（导入 zip，合并追加）
  backup: async () => {
    const res = await request("/api/auth/backup");
    return res.blob(); // 非 JSON 响应 → Response 对象
  },
  restore: async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/auth/restore", { method: "POST", body: fd });
  },
};
