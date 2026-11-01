// 全局登录态（批次4）：AuthContext 提供 user / isLoggedIn / isAdmin / 登录登出
// - token 存 localStorage（aigc_token），初始化时拉 /me 恢复用户
// - 登录/登出/改密后派发全局 auth-changed 事件（App 重新拉取当前页数据）
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getToken, setToken } from "../api/index.js";
import { authApi } from "../api/authApi.js";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);        // 登录用户（null=游客）
  const [ready, setReady] = useState(false);     // 初始化是否完成（防闪"未登录"）
  const [loginModal, setLoginModal] = useState(false); // 全局登录/注册弹窗

  const isLoggedIn = !!user;
  const isAdmin = !!user && user.role === "admin";

  // 初始化：本地有 token 则拉 /me 恢复登录态；无/失效则清 token 保持游客
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!getToken()) { if (alive) setReady(true); return; }
      try {
        const d = await authApi.me();
        if (alive) setUser(d.user);
      } catch (_) {
        setToken("");
      }
      if (alive) setReady(true);
    })();
    return () => { alive = false; };
  }, []);

  // 重新拉取当前用户（auth-changed 后页面数据刷新用）
  const refresh = useCallback(async () => {
    if (!getToken()) { setUser(null); return null; }
    try {
      const d = await authApi.me();
      setUser(d.user);
      return d.user;
    } catch (_) {
      setToken("");
      setUser(null);
      return null;
    }
  }, []);

  // 登录成功：fn 返回 {token, user}；必须改密场景由调用方（AuthModal）接管
  const applyLogin = useCallback(async (fn) => {
    const d = await fn();
    setToken(d.token);
    setUser(d.user);
    window.dispatchEvent(new CustomEvent("auth-changed"));
    return d.user;
  }, []);

  // 退出登录：调后端失效当前 token → 清本地 → 回退游客（device_id 保留）
  const logout = useCallback(async () => {
    try { await authApi.logout(); } catch (_) {}
    setToken("");
    setUser(null);
    window.dispatchEvent(new CustomEvent("auth-changed"));
  }, []);

  const openLogin = useCallback(() => setLoginModal(true), []);
  const closeLogin = useCallback(() => setLoginModal(false), []);

  const value = {
    user, isLoggedIn, isAdmin, ready,
    login: applyLogin, logout, refresh,
    loginModal, openLogin, closeLogin,
  };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  return useContext(AuthCtx);
}
