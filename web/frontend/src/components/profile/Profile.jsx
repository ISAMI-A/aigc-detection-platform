// 个人资料页（批次4/4.1，顶部标签 profile，登录后才显示）
// 左侧菜单栏（头像+用户名+菜单）+ 右侧内容区：账号信息（默认）/ 修改密码 / 邮箱设置 / 人脸设置 / 数据导出
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authApi } from "../../api/authApi.js";
import { fetchProfileFace, saveProfileFace, deleteProfileFace } from "../../api/faceApi.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import PasswordInput from "../common/PasswordInput.jsx";

const PWD_RULE_RE = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,20}$/;

function fmtSize(bytes) {
  if (!bytes) return "0 MB";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// 注册时间展示：日期与详细时间分开（2026-08-11 / 11:16:42）
function fmtDateTime(ts) {
  if (!ts) return null;
  const [date, time] = String(ts).split("T");
  return { date, time: time ? time.slice(0, 8) : "" };
}

export default function Profile() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [section, setSection] = useState("account"); // account/pwd/email/face/export

  return (
    <div className="profile">
      {/* 左侧菜单栏 */}
      <div className="profile-side">
        <div className="profile-side-user">
          <div className="profile-avatar">{(auth.user?.username || "?").slice(0, 1).toUpperCase()}</div>
          <div className="profile-side-name">{auth.user?.username}</div>
        </div>
        <nav className="profile-menu">
          {[
            ["account", "profile.account"],
            ["pwd", "profile.changePwd"],
            ["email", "profile.emailSection"],
            ["face", "profile.face"],
            ["export", "profile.exportSection"],
          ].map(([key, label]) => (
            <button key={key} className={`profile-menu-item ${section === key ? "active" : ""}`}
                    onClick={() => setSection(key)}>{t(label)}</button>
          ))}
        </nav>
      </div>

      {/* 右侧内容区 */}
      <div className="profile-main">
        {section === "account" && <AccountSection />}
        {section === "pwd" && <PwdSection />}
        {section === "email" && <EmailSection />}
        {section === "face" && <FaceSection />}
        {section === "export" && <ExportSection />}
      </div>
    </div>
  );
}

/* 轻提示（成功/错误，3s 自动消失） */
function useToast() {
  const [msg, setMsg] = useState({ kind: "", text: "" });
  function toast(kind, text) {
    setMsg({ kind, text });
    setTimeout(() => setMsg({ kind: "", text: "" }), 3000);
  }
  const el = msg.text
    ? <div className={`toast ${msg.kind === "ok" ? "toast-success" : "toast-error"}`}>{msg.text}</div>
    : null;
  return { toast, el };
}

/* 账号信息（默认显示） */
function AccountSection() {
  const { t } = useTranslation();
  const user = useAuth().user || {};
  return (
    <div className="profile-panel">
      <div className="profile-panel-title">{t("profile.account")}</div>
      <div className="profile-row">
        <span className="profile-k">{t("auth.username")}</span>
        <span className="profile-v">{user.username || "-"}</span>
      </div>
      <div className="profile-row">
        <span className="profile-k">{t("profile.uid")}</span>
        <span className="profile-v">{user.uid || "-"}</span>
      </div>
      <div className="profile-row">
        <span className="profile-k">{t("auth.email")}</span>
        <span className="profile-v">
          {user.email || t("profile.noEmail")}
          {user.email && (
            <span className={`profile-badge ${user.email_verified ? "ok" : ""}`}>
              {user.email_verified ? t("profile.verified") : t("profile.unverified")}
            </span>
          )}
        </span>
      </div>
      <div className="profile-row">
        <span className="profile-k">{t("profile.role")}</span>
        <span className="profile-v">{user.role === "admin" ? t("profile.roleAdmin") : t("profile.roleUser")}</span>
      </div>
      <div className="profile-row">
        <span className="profile-k">{t("profile.createdAt")}</span>
        <span className="profile-v">
          {(() => {
            const dt = fmtDateTime(user.created_at);
            return dt
              ? <><span className="profile-date">{dt.date}</span>{dt.time && <span className="profile-date-time">{dt.time}</span>}</>
              : "-";
          })()}
        </span>
      </div>
    </div>
  );
}

/* 修改密码 */
function PwdSection() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [pwd, setPwd] = useState({ old: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const { toast, el } = useToast();

  async function submit() {
    if (!PWD_RULE_RE.test(pwd.next)) { toast("err", t("auth.passwordRule")); return; }
    if (pwd.next !== pwd.confirm) { toast("err", t("auth.pwdMismatch")); return; }
    setBusy(true);
    try {
      await authApi.changePassword({ old_password: pwd.old, new_password: pwd.next });
      await auth.logout(); // 改密后全部 token 失效 → 清登录态回退游客
      toast("ok", t("profile.pwdChanged"));
      setPwd({ old: "", next: "", confirm: "" });
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="profile-panel">
      <div className="profile-panel-title">{t("profile.changePwd")}</div>
      {el}
      <div className="profile-field">
        <label>{t("auth.oldPassword")}</label>
        <PasswordInput value={pwd.old} onChange={(v) => setPwd({ ...pwd, old: v })} />
      </div>
      <div className="profile-field">
        <label>{t("auth.newPassword")}</label>
        <PasswordInput value={pwd.next} onChange={(v) => setPwd({ ...pwd, next: v })} />
      </div>
      <div className="profile-field">
        <label>{t("auth.confirmPassword")}</label>
        <PasswordInput value={pwd.confirm} onChange={(v) => setPwd({ ...pwd, confirm: v })} />
      </div>
      <div className="profile-tips">{t("auth.passwordRule")}</div>
      <button className="btn primary" disabled={busy} onClick={submit}>{t("profile.savePwd")}</button>
    </div>
  );
}

/* 邮箱设置：无邮箱→绑定表单；有邮箱→信息视图 + 更换（先验证旧邮箱再输新邮箱） */
function EmailSection() {
  const { t } = useTranslation();
  const auth = useAuth();
  const userEmail = auth.user?.email || "";
  const [step, setStep] = useState(userEmail ? "info" : "form"); // form=绑定 / info=已绑定 / old=验旧 / new=输新邮箱
  const [mail, setMail] = useState({ email: "", code: "" });
  const [oldCode, setOldCode] = useState("");
  const [countdown, setCountdown] = useState(0);
  const [busy, setBusy] = useState(false);
  const { toast, el } = useToast();

  // 绑定/更换成功后 userEmail 变化 → 回到已绑定信息视图
  useEffect(() => {
    setStep(userEmail ? "info" : "form");
    setMail({ email: "", code: "" });
    setOldCode("");
  }, [userEmail]);

  // 获取验证码：验证旧邮箱阶段发到旧邮箱，其余发到新邮箱输入框
  async function sendCode() {
    const target = step === "old" ? userEmail : mail.email.trim();
    if (!/^\S+@\S+\.\S+$/.test(target)) { toast("err", t("auth.emailInvalid")); return; }
    setBusy(true);
    try {
      await authApi.sendCode({ email: target, purpose: "bind" });
      toast("ok", t("auth.codeSent"));
      let n = 60;
      setCountdown(n);
      const iv = setInterval(() => {
        n -= 1;
        setCountdown(n);
        if (n <= 0) { clearInterval(iv); setCountdown(0); }
      }, 1000);
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  // 更换第一步：验证旧邮箱验证码
  async function verifyOld() {
    if (!oldCode.trim()) { toast("err", t("auth.codeRequired")); return; }
    setBusy(true);
    try {
      await authApi.verifyOldEmail({ code: oldCode.trim() });
      toast("ok", t("profile.oldEmailVerified"));
      setOldCode("");
      setStep("new");
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  // 绑定新邮箱 / 更换保存
  async function bind() {
    if (!/^\S+@\S+\.\S+$/.test(mail.email.trim())) { toast("err", t("auth.emailInvalid")); return; }
    if (!mail.code.trim()) { toast("err", t("auth.codeRequired")); return; }
    setBusy(true);
    try {
      await authApi.bindEmail({ email: mail.email.trim(), code: mail.code.trim() });
      toast("ok", t("profile.emailBound"));
      setMail({ email: "", code: "" });
      auth.refresh(); // userEmail 更新 → useEffect 回 info
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  // 已绑定：显示当前邮箱 + 更换入口
  if (step === "info") {
    return (
      <div className="profile-panel">
        <div className="profile-panel-title">{t("profile.emailSection")}</div>
        {el}
        <div className="profile-field">
          <label>{t("profile.currentEmail")}</label>
          <div className="profile-email-line">{userEmail}</div>
        </div>
        <div className="profile-tips">{t("profile.emailTip")}</div>
        <button className="btn primary" disabled={busy} onClick={() => setStep("old")}>
          {t("profile.changeEmail")}
        </button>
      </div>
    );
  }

  // 更换第一步：验证旧邮箱
  if (step === "old") {
    return (
      <div className="profile-panel">
        <div className="profile-panel-title">{t("profile.changeEmail")}</div>
        {el}
        <div className="profile-field">
          <label>{t("profile.oldEmail")}</label>
          <div className="profile-email-line">{userEmail}</div>
        </div>
        <div className="profile-field">
          <label>{t("profile.oldEmailCode")}</label>
          <div className="profile-code-row">
            <input value={oldCode} placeholder={t("profile.oldEmailCodePlaceholder")}
                   onChange={(e) => setOldCode(e.target.value)} />
            <button className="btn" disabled={busy || countdown > 0} onClick={sendCode}>
              {countdown > 0 ? `${countdown}s` : t("auth.sendCode")}
            </button>
          </div>
        </div>
        <div className="profile-btns">
          <button className="btn" disabled={busy} onClick={() => setStep("info")}>{t("common.cancel")}</button>
          <button className="btn primary" disabled={busy} onClick={verifyOld}>{t("profile.verifyAndNext")}</button>
        </div>
      </div>
    );
  }

  // 绑定表单 / 更换第二步：输入新邮箱
  return (
    <div className="profile-panel">
      <div className="profile-panel-title">{step === "new" ? t("profile.changeEmail") : t("profile.bindEmail")}</div>
      {el}
      {step === "form" && <div className="profile-tips">{t("profile.emailNotBoundHint")}</div>}
      <div className="profile-field">
        <label>{t("auth.email")}</label>
        <div className="profile-code-row">
          <input value={mail.email} placeholder={t("profile.emailPlaceholder")}
                 onChange={(e) => setMail({ ...mail, email: e.target.value })} />
          <button className="btn" disabled={busy || countdown > 0} onClick={sendCode}>
            {countdown > 0 ? `${countdown}s` : t("auth.sendCode")}
          </button>
        </div>
      </div>
      <div className="profile-field">
        <label>{t("auth.code")}</label>
        <input value={mail.code} onChange={(e) => setMail({ ...mail, code: e.target.value })} />
      </div>
      <div className="profile-btns">
        {step === "new" && (
          <button className="btn" disabled={busy} onClick={() => setStep("info")}>{t("common.cancel")}</button>
        )}
        <button className="btn primary" disabled={busy} onClick={bind}>
          {step === "new" ? t("profile.confirmChange") : t("profile.saveEmail")}
        </button>
      </div>
    </div>
  );
}

/* 人脸设置（远期占位） */
function FaceSection() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [state, setState] = useState(null);      // {bound, name, samples, count}
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(null); // {name, conflict, file}
  const [enroll, setEnroll] = useState(null);     // {file, name} 姓名输入弹窗
  const [confirmRemove, setConfirmRemove] = useState(false);
  const fileInput = useRef(null);
  const { toast, el } = useToast();

  useEffect(() => {
    let alive = true;
    fetchProfileFace().then((d) => alive && setState(d)).catch(() => {});
    return () => { alive = false; };
  }, []);

  async function refresh() {
    try { setState(await fetchProfileFace()); } catch (_) {}
  }

  // 选照片 → 弹姓名输入弹窗（默认=用户名/已录入名，可改）
  function pickPhoto(e) {
    const f = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!f) return;
    setEnroll({ file: f, name: state?.bound ? state.name : (auth.user?.username || "") });
  }

  // 确认姓名 → 查重 → need_confirm 弹窗或直接入库
  async function submitEnroll() {
    const name = (enroll.name || "").trim();
    if (!name) { toast("err", t("face.nameRequired")); return; }
    setBusy(true);
    try {
      const d = await saveProfileFace(enroll.file, name);
      setEnroll(null);
      if (d && d.need_confirm) {
        setConflict({ name, conflict: d.conflict, file: enroll.file });
        return;
      }
      toast("ok", t("profile.faceSaved"));
      await refresh();
    } catch (err) {
      toast("err", err.message);
    } finally {
      setBusy(false);
    }
  }

  // 冲突确认：overwrite=改名+补样本 / new=独立新人员
  async function resolveConflict(mode) {
    const { name, file } = conflict;
    setConflict(null);
    setBusy(true);
    try {
      await saveProfileFace(file, name, mode);
      toast("ok", mode === "overwrite" ? t("face.overwritten") : t("face.addedNew"));
      await refresh();
    } catch (err) {
      toast("err", err.message);
    } finally {
      setBusy(false);
    }
  }

  // 删除录入（解绑 + 删除库样本）
  async function removeFace() {
    setConfirmRemove(false);
    setBusy(true);
    try {
      await deleteProfileFace();
      toast("ok", t("profile.faceRemoved"));
      await refresh();
    } catch (err) {
      toast("err", err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="profile-panel">
      <div className="profile-panel-title">{t("profile.face")}</div>
      <div className="profile-face-tip">{t("profile.faceTip")}</div>

      {state?.bound ? (
        <div className="profile-face-bound">
          <div className="profile-face-samples">
            {(state.samples || []).map((s) => (
              <img key={s.id} src={s.thumb} alt="" className="profile-face-sample" />
            ))}
          </div>
          <div className="profile-row">
            <span className="profile-k">{t("face.name")}</span>
            <span className="profile-v">{state.name}</span>
          </div>
          <div className="profile-row">
            <span className="profile-k">{t("profile.faceSamples")}</span>
            <span className="profile-v">{state.count}</span>
          </div>
          <div className="profile-face-ops">
            <input ref={fileInput} type="file" accept="image/*" style={{ display: "none" }} onChange={pickPhoto} />
            <button className="btn" disabled={busy} onClick={() => fileInput.current && fileInput.current.click()}>
              {t("profile.faceUpdate")}
            </button>
            <button className="btn danger" disabled={busy} onClick={() => setConfirmRemove(true)}>{t("profile.faceRemove")}</button>
          </div>
        </div>
      ) : (
        <div className="profile-face-empty">
          <div className="dim">{t("profile.faceNotEnrolled")}</div>
          <input ref={fileInput} type="file" accept="image/*" style={{ display: "none" }} onChange={pickPhoto} />
          <button className="btn primary" disabled={busy} onClick={() => fileInput.current && fileInput.current.click()}>
            {t("profile.enrollFace")}
          </button>
        </div>
      )}

      {/* 姓名输入弹窗（录入/更新共用） */}
      {enroll && (
        <div className="modal-mask" onClick={() => setEnroll(null)}>
          <div className="modal face-manual-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{t("profile.faceNameTitle")}</span>
              <button className="btn small" onClick={() => setEnroll(null)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="detail-row"><span>{t("face.inputName")}</span>
                <input className="note-input" autoFocus value={enroll.name}
                       placeholder={t("face.namePlaceholder")}
                       onChange={(e) => setEnroll({ ...enroll, name: e.target.value })}
                       onKeyDown={(e) => { if (e.key === "Enter") submitEnroll(); }} /></div>
              <div className="dim face-manual-tip">{t("profile.faceNameTip")}</div>
            </div>
            <div className="modal-foot">
              <button className="btn" onClick={() => setEnroll(null)}>{t("common.cancel")}</button>
              <button className="btn primary" disabled={busy} onClick={submitEnroll}>{t("profile.enrollFace")}</button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认弹窗 */}
      {confirmRemove && (
        <div className="modal-mask" onClick={() => setConfirmRemove(false)}>
          <div className="modal face-manual-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{t("profile.faceRemove")}</span>
              <button className="btn small" onClick={() => setConfirmRemove(false)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="face-conflict-text">{t("profile.faceRemoveConfirm")}</div>
            </div>
            <div className="modal-foot">
              <button className="btn" onClick={() => setConfirmRemove(false)}>{t("common.cancel")}</button>
              <button className="btn danger" onClick={removeFace}>{t("common.confirm")}</button>
            </div>
          </div>
        </div>
      )}

      {/* 冲突确认弹窗 */}
      {conflict && (
        <div className="modal-mask" onClick={() => setConflict(null)}>
          <div className="modal face-manual-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{t("face.conflictTitle")}</span>
              <button className="btn small" onClick={() => setConflict(null)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="face-conflict-body">
                <div className="face-conflict-text"
                     dangerouslySetInnerHTML={{ __html: t("face.conflictBody", {
                       name: conflict.name, old: conflict.conflict.name,
                       sim: Math.round((conflict.conflict.similarity || 0) * 100),
                     }) }} />
                <div className="face-conflict-opts">
                  <button className="btn primary" onClick={() => resolveConflict("overwrite")}>
                    {t("face.conflictOverwrite")}<div className="dim">{t("face.conflictOverwriteDesc")}</div>
                  </button>
                  <button className="btn" onClick={() => resolveConflict("new")}>
                    {t("face.conflictNew")}<div className="dim">{t("face.conflictNewDesc")}</div>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
      {el}
    </div>
  );
}

/* 数据导出：当前用户三系统数据大小 + 导出 */
function ExportSection() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [stats, setStats] = useState(null);
  const [busy, setBusy] = useState(false);
  const { toast, el } = useToast();

  useEffect(() => {
    let alive = true;
    authApi.exportData().then((d) => alive && setStats(d)).catch(() => {});
    return () => { alive = false; };
  }, []);

  // 后端 _stats 返回嵌套 {表名:{count,bytes}} → 聚合成单系统 {count,bytes}
  const sum = (o) => Object.values(o || {}).reduce(
    (a, x) => ({ count: a.count + (x.count || 0), bytes: a.bytes + (x.bytes || 0) }),
    { count: 0, bytes: 0 });

  const rows = stats
    ? [
        { key: "detect", name: t("home.detectTitle"), s: sum(stats.detect) },
        { key: "verify", name: t("home.verifyTitle"), s: sum(stats.smart) },
        { key: "rs", name: t("home.rsTitle"), s: sum(stats.rs) },
        { key: "face", name: t("home.faceTitle"), s: sum(stats.face) },
      ]
    : [];

  async function doBackup() {
    setBusy(true);
    try {
      const blob = await authApi.backup();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `backup-${auth.user?.username || "user"}-${new Date().toISOString().slice(0, 10)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      toast("ok", t("profile.backedUp"));
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  // 导入备份（zip）
  async function doRestore(file) {
    if (!file) return;
    setBusy(true);
    try {
      await authApi.restore(file);
      toast("ok", t("profile.restored"));
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="profile-panel">
      <div className="profile-panel-title">{t("profile.exportSection")}</div>
      {el}
      <div className="profile-stats">
        {!stats && <div className="profile-stats-empty">{t("common.loading")}</div>}
        {rows.map((r) => (
          <div className="profile-stats-row" key={r.key}>
            <span className="profile-stats-name">{r.name}</span>
            <span>{t("profile.statsRow", { count: r.s.count, size: fmtSize(r.s.bytes) })}</span>
          </div>
        ))}
        {stats && (
          <div className="profile-stats-total">
            {t("profile.statsTotal", {
              size: fmtSize(rows.reduce((a, r) => a + (r.s.bytes || 0), 0)),
            })}
          </div>
        )}
      </div>
      <div className="profile-backup-ops">
        <button className="btn primary" disabled={busy} onClick={doBackup}>{t("profile.backup")}</button>
        <label className="btn" onClick={(e) => { e.currentTarget.querySelector("input").value = ""; }}>
          {t("profile.restore")}
          <input type="file" accept=".zip" style={{ display: "none" }}
                 onChange={(e) => doRestore(e.target.files && e.target.files[0])} />
        </label>
      </div>
      <div className="profile-backup-hint">{t("profile.backupHint")}</div>
    </div>
  );
}
