// 登录/注册弹窗（批次4）：三种登录方式（账号密码 / 邮箱验证码 / 人脸[远期占位]）
// 模式：login（登录） / register（注册） / forgot（忘记密码） / changePass（强制改密）
// - 登录成功且 must_change_password=1 → 不关闭，自动切改密模式
// - 注册：用户名+密码必选；邮箱可选（填邮箱需验证码）
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authApi } from "../../api/authApi.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import PasswordInput from "./PasswordInput.jsx";
import FaceLoginPanel from "./FaceLoginPanel.jsx";

const PWD_RULE_RE = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,20}$/;

export default function AuthModal() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [mode, setMode] = useState("login");        // login/register/forgot/changePass
  const [loginMode, setLoginMode] = useState("password"); // password/email/face
  const [form, setForm] = useState({});
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [agree, setAgree] = useState(true);
  const [countdown, setCountdown] = useState(0);
  const timerRef = useRef(null);

  useEffect(() => () => clearInterval(timerRef.current), []);

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })); setErr(""); }

  // 发送验证码（purpose 按模式映射）
  async function sendCode() {
    const email = (form.email || "").trim();
    if (!/^\S+@\S+\.\S+$/.test(email)) { setErr(t("auth.emailInvalid")); return; }
    const purpose = mode === "register" ? "register"
      : mode === "forgot" ? "reset" : mode === "changePass" ? "bind" : "login";
    setBusy(true); setErr("");
    try {
      await authApi.sendCode({ email, purpose });
      setErr(t("auth.codeSent"));
      let n = 60;
      setCountdown(n);
      timerRef.current = setInterval(() => {
        n -= 1;
        setCountdown(n);
        if (n <= 0) { clearInterval(timerRef.current); setCountdown(0); }
      }, 1000);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  // 校验新密码
  function checkPwd(pw, confirm) {
    if (!PWD_RULE_RE.test(pw)) return t("auth.passwordRule");
    if (pw !== confirm) return t("auth.pwdMismatch");
    return "";
  }

  // 登录：fn 返回 {token,user}
  async function doLogin(fn) {
    setBusy(true); setErr("");
    try {
      const user = await auth.login(fn);
      if (user.must_change_password === 1) {
        setErr(t("auth.mustChangePassword"));
        setForm({});
        setMode("changePass");
        return;
      }
      auth.closeLogin();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setErr("");
    if (mode === "login") {
      if (loginMode === "password") {
        if (!form.username || !form.password) { setErr(t("auth.fillRequired")); return; }
        return doLogin(() => authApi.login({ username: form.username.trim(), password: form.password }));
      }
      if (loginMode === "email") {
        if (!form.email || !form.code) { setErr(t("auth.fillRequired")); return; }
        return doLogin(() => authApi.loginEmail({ email: form.email.trim(), code: form.code.trim() }));
      }
      return; // face 模式由 FaceLoginPanel 自行处理（不走 submit）
    }
    if (mode === "register") {
      if (!agree) { setErr(t("auth.agreeRequired")); return; }
      if (!form.username || !form.password || !form.confirm) { setErr(t("auth.fillRequired")); return; }
      const pwdErr = checkPwd(form.password, form.confirm);
      if (pwdErr) { setErr(pwdErr); return; }
      if (form.email && !/^\S+@\S+\.\S+$/.test(form.email)) { setErr(t("auth.emailInvalid")); return; }
      if (form.email && !form.code) { setErr(t("auth.codeRequired")); return; }
      setBusy(true);
      try {
        const user = await auth.login(() => authApi.register({
          username: form.username.trim(), password: form.password,
          email: form.email ? form.email.trim() : undefined,
          code: form.code ? form.code.trim() : undefined,
        }));
        if (user.must_change_password === 1) {
          setErr(t("auth.mustChangePassword"));
          setForm({});
          setMode("changePass");
          return;
        }
        auth.closeLogin();
      } catch (e) {
        setErr(e.message);
      } finally {
        setBusy(false);
      }
      return;
    }
    if (mode === "forgot") {
      if (!form.email || !form.code || !form.newPassword || !form.confirm) { setErr(t("auth.fillRequired")); return; }
      const pwdErr = checkPwd(form.newPassword, form.confirm);
      if (pwdErr) { setErr(pwdErr); return; }
      setBusy(true);
      try {
        await authApi.forgot({ email: form.email.trim(), code: form.code.trim(), new_password: form.newPassword });
        setNotice(t("auth.resetOk"));
        setForm({});
        setMode("login");
      } catch (e) {
        setErr(e.message);
      } finally {
        setBusy(false);
      }
      return;
    }
    if (mode === "changePass") {
      if (!form.oldPassword || !form.newPassword || !form.confirm) { setErr(t("auth.fillRequired")); return; }
      const pwdErr = checkPwd(form.newPassword, form.confirm);
      if (pwdErr) { setErr(pwdErr); return; }
      setBusy(true);
      try {
        await authApi.changePassword({ old_password: form.oldPassword, new_password: form.newPassword });
        // 改密后全部 token 失效 → 清登录态回退游客，需重新登录
        await auth.logout();
        setNotice(t("auth.changePwdOk"));
        setForm({});
        setMode("login");
      } catch (e) {
        setErr(e.message);
      } finally {
        setBusy(false);
      }
    }
  }

  function switchMode(m) {
    setMode(m);
    setForm({});
    setErr("");
    setNotice("");
  }

  const isLogin = mode === "login";
  const codeBtnDisabled = busy || countdown > 0 || !/^\S+@\S+\.\S+$/.test((form.email || "").trim());

  return (
    <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) auth.closeLogin(); }}>
      <div className="modal auth-modal">
        <div className="modal-head">
          <span className="modal-title">
            {mode === "register" ? t("auth.register") : mode === "forgot" ? t("auth.forgotTitle")
              : mode === "changePass" ? t("auth.changePwdTitle") : t("auth.login")}
          </span>
          <span className="modal-close" onClick={auth.closeLogin}>×</span>
        </div>

        {/* 登录/注册 顶部切换 */}
        {(isLogin || mode === "register") && (
          <div className="auth-tabs">
            <button className={`auth-tab ${isLogin ? "active" : ""}`}
                    onClick={() => switchMode("login")}>{t("auth.login")}</button>
            <button className={`auth-tab ${mode === "register" ? "active" : ""}`}
                    onClick={() => switchMode("register")}>{t("auth.register")}</button>
          </div>
        )}

        {/* 登录方式 tab（仅登录模式） */}
        {isLogin && (
          <div className="auth-login-modes">
            <button className={loginMode === "password" ? "active" : ""}
                    onClick={() => setLoginMode("password")}>{t("auth.loginByPassword")}</button>
            <button className={loginMode === "email" ? "active" : ""}
                    onClick={() => setLoginMode("email")}>{t("auth.loginByEmail")}</button>
            <button className={loginMode === "face" ? "active" : ""}
                    onClick={() => setLoginMode("face")}>{t("auth.loginByFace")}</button>
          </div>
        )}

        <div className="auth-form">
          {isLogin && loginMode === "password" && (
            <>
              <label className="auth-label">{t("auth.username")}</label>
              <input className="auth-input" value={form.username || ""}
                     onChange={(e) => set("username", e.target.value)} autoFocus />
              <label className="auth-label">{t("auth.password")}</label>
              <PasswordInput value={form.password || ""}
                             onChange={(v) => set("password", v)}
                             onKeyDown={(e) => e.key === "Enter" && submit()} />
              <div className="auth-forgot" onClick={() => switchMode("forgot")}>{t("auth.forgot")}</div>
            </>
          )}

          {isLogin && loginMode === "email" && (
            <>
              <label className="auth-label">{t("auth.email")}</label>
              <input className="auth-input" value={form.email || ""}
                     onChange={(e) => set("email", e.target.value)} />
              <label className="auth-label">{t("auth.code")}</label>
              <div className="auth-code-row">
                <input className="auth-input" value={form.code || ""}
                       onChange={(e) => set("code", e.target.value)}
                       onKeyDown={(e) => e.key === "Enter" && submit()} />
                <button className="btn auth-code-btn" disabled={codeBtnDisabled} onClick={sendCode}>
                  {countdown > 0 ? `${countdown}s` : t("auth.sendCode")}
                </button>
              </div>
            </>
          )}

          {isLogin && loginMode === "face" && (
            <FaceLoginPanel
              onSuccess={async (fn) => {
                // 与 doLogin 同收尾：must_change_password → 切改密；否则关闭弹窗
                setBusy(true);
                try {
                  const user = await auth.login(fn);
                  if (user.must_change_password === 1) {
                    setErr(t("auth.mustChangePassword"));
                    setForm({});
                    setMode("changePass");
                    return;
                  }
                  auth.closeLogin();
                } catch (e) {
                  setErr(e.message);
                } finally {
                  setBusy(false);
                }
              }} />
          )}

          {mode === "register" && (
            <>
              <label className="auth-label">{t("auth.username")}</label>
              <input className="auth-input" value={form.username || ""}
                     onChange={(e) => set("username", e.target.value)} />
              <label className="auth-label">{t("auth.password")}</label>
              <PasswordInput value={form.password || ""} onChange={(v) => set("password", v)} />
              <label className="auth-label">{t("auth.confirmPassword")}</label>
              <PasswordInput value={form.confirm || ""} onChange={(v) => set("confirm", v)} />
              <label className="auth-label">{t("auth.emailOptional")}</label>
              <div className="auth-code-row">
                <input className="auth-input" value={form.email || ""}
                       onChange={(e) => set("email", e.target.value)} />
                {form.email && (
                  <button className="btn auth-code-btn" disabled={codeBtnDisabled} onClick={sendCode}>
                    {countdown > 0 ? `${countdown}s` : t("auth.sendCode")}
                  </button>
                )}
              </div>
              {form.email && (
                <>
                  <label className="auth-label">{t("auth.code")}</label>
                  <input className="auth-input" value={form.code || ""}
                         onChange={(e) => set("code", e.target.value)} />
                </>
              )}
              <div className="auth-tips">{t("auth.registerTips")}</div>
              <label className="auth-agree">
                <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
                <span>{t("auth.agree")}{t("auth.agreement")}{t("auth.privacy")}</span>
              </label>
            </>
          )}

          {mode === "forgot" && (
            <>
              <label className="auth-label">{t("auth.email")}</label>
              <div className="auth-code-row">
                <input className="auth-input" value={form.email || ""}
                       onChange={(e) => set("email", e.target.value)} />
                <button className="btn auth-code-btn" disabled={codeBtnDisabled} onClick={sendCode}>
                  {countdown > 0 ? `${countdown}s` : t("auth.sendCode")}
                </button>
              </div>
              <label className="auth-label">{t("auth.code")}</label>
              <input className="auth-input" value={form.code || ""}
                     onChange={(e) => set("code", e.target.value)} />
              <label className="auth-label">{t("auth.newPassword")}</label>
              <PasswordInput value={form.newPassword || ""} onChange={(v) => set("newPassword", v)} />
              <label className="auth-label">{t("auth.confirmPassword")}</label>
              <PasswordInput value={form.confirm || ""} onChange={(v) => set("confirm", v)}
                             onKeyDown={(e) => e.key === "Enter" && submit()} />
              <div className="auth-tips">{t("auth.passwordRule")}</div>
            </>
          )}

          {mode === "changePass" && (
            <>
              <label className="auth-label">{t("auth.oldPassword")}</label>
              <PasswordInput value={form.oldPassword || ""} onChange={(v) => set("oldPassword", v)} />
              <label className="auth-label">{t("auth.newPassword")}</label>
              <PasswordInput value={form.newPassword || ""} onChange={(v) => set("newPassword", v)} />
              <label className="auth-label">{t("auth.confirmPassword")}</label>
              <PasswordInput value={form.confirm || ""} onChange={(v) => set("confirm", v)}
                             onKeyDown={(e) => e.key === "Enter" && submit()} />
              <div className="auth-tips">{t("auth.passwordRule")}</div>
            </>
          )}

          {err && <div className="auth-err">{err}</div>}
          {notice && <div className="auth-ok">{notice}</div>}

          {!(isLogin && loginMode === "face") && (
            <button className="btn primary auth-submit" disabled={busy} onClick={submit}>
              {busy ? t("common.loading") :
                mode === "register" ? t("auth.register") : mode === "forgot" ? t("auth.resetSubmit")
                  : mode === "changePass" ? t("auth.changePwdSubmit") : t("auth.login")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
