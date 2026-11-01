// 系统管理页（批次5，admin 专属标签）：总览 / 用户管理 / 功能开关 / 系统公告 / 操作日志 / 人脸库 / 数据管理
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { adminApi } from "../../api/adminApi.js";
import { fetchLibrary, libraryAdd, libraryRename, libraryPhoto, libraryDelete } from "../../api/faceApi.js";
import PasswordInput from "../common/PasswordInput.jsx";
import DateTimePicker from "../common/DateTimePicker.jsx";

const SECTIONS = [
  ["overview", "admin.overview"],
  ["users", "admin.users"],
  ["features", "admin.features"],
  ["announcements", "admin.announcements"],
  ["logs", "admin.logs"],
  ["facelib", "admin.facelib"],
  ["data", "admin.data"],
];

export default function AdminPage() {
  const { t } = useTranslation();
  const [section, setSection] = useState("overview");
  return (
    <div className="admin">
      <div className="admin-side">
        {SECTIONS.map(([key, label]) => (
          <button key={key} className={`profile-menu-item ${section === key ? "active" : ""}`}
                  onClick={() => setSection(key)}>{t(label)}</button>
        ))}
      </div>
      <div className="admin-main">
        {section === "overview" && <Overview />}
        {section === "users" && <Users />}
        {section === "features" && <Features />}
        {section === "announcements" && <Announcements />}
        {section === "logs" && <Logs />}
        {section === "facelib" && <FaceLibrary />}
        {section === "data" && <Data />}
      </div>
    </div>
  );
}

/* 轻提示 */
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

/* 总览 */
function Overview() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  useEffect(() => { adminApi.overview().then(setData).catch(() => {}); }, []);
  if (!data) return <div className="admin-empty">{t("common.loading")}</div>;
  const items = [
    { label: t("admin.userTotal"), value: data.users },
    { label: t("admin.todayActive"), value: data.today_active },
    { label: t("admin.detectRecords"), value: data.detect.detect_uploads + data.detect.detect_records },
    { label: t("admin.verifyRecords"), value: data.smart.images + data.smart.pairs + data.smart.results },
    { label: t("admin.rsRecords"), value: data.rs.rs_images + data.rs.rs_records },
  ];
  return (
    <div className="admin-panel">
      <div className="admin-panel-title">{t("admin.overview")}</div>
      <div className="admin-stat-grid">
        {items.map((it) => (
          <div className="admin-stat" key={it.label}>
            <div className="admin-stat-value">{it.value}</div>
            <div className="admin-stat-label">{it.label}</div>
          </div>
        ))}
      </div>
      <div className="admin-panel-title admin-sub">{t("admin.featureStatus")}</div>
      <div className="admin-feature-chips">
        {Object.entries(data.features || {}).map(([k, v]) => (
          <span key={k} className={`admin-chip ${v ? "on" : "off"}`}>{k} · {v ? t("admin.on") : t("admin.off")}</span>
        ))}
      </div>
    </div>
  );
}

/* 用户管理 */
function Users() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [confirmDlg, setConfirmDlg] = useState(null); // {title, desc, onOk}
  const [pwdDlg, setPwdDlg] = useState(null);         // {id, username}
  const [pwdInput, setPwdInput] = useState("");
  const [addOpen, setAddOpen] = useState(false);      // 新建用户弹窗
  const [addForm, setAddForm] = useState({ username: "", password: "", confirm: "", email: "", role: "user" });
  const { toast, el } = useToast();
  const size = 10;

  async function load(p = page, s = search) {
    setBusy(true);
    try {
      setData(await adminApi.users({ page: p, size, search: s }));
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => { load(1, ""); }, []); // eslint-disable-line

  async function act(fn, okMsg) {
    try {
      await fn();
      toast("ok", okMsg);
      load();
    } catch (e) {
      toast("err", e.message);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / size)) : 1;

  return (
    <div className="admin-panel">
      <div className="admin-panel-title">{t("admin.users")}</div>
      {el}
      <div className="admin-toolbar">
        <input value={search} placeholder={t("admin.userSearch")}
               onChange={(e) => setSearch(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") { setPage(1); load(1, search); } }} />
        <button className="btn" disabled={busy} onClick={() => { setSearch(""); setPage(1); load(1, ""); }}>
          {t("admin.logReset")}
        </button>
        <button className="btn primary" disabled={busy} onClick={() => { setPage(1); load(1, search); }}>
          {t("admin.search")}
        </button>
        <span className="admin-fill" />
        <button className="btn primary" disabled={busy} onClick={() => { setAddForm({ username: "", password: "", confirm: "", email: "", role: "user" }); setAddOpen(true); }}>
          {t("admin.addUser")}
        </button>
      </div>
      {!data && <div className="admin-empty">{t("common.loading")}</div>}
      {data && (
        <>
          <div className="admin-table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th><th>{t("auth.username")}</th><th>{t("auth.email")}</th>
                <th>{t("profile.role")}</th><th>{t("admin.status")}</th>
                <th>{t("profile.createdAt")}</th><th>{t("admin.ops")}</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((u) => (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td>{u.username}</td>
                  <td>{u.email || "-"}</td>
                  <td className="admin-role">
                    <div className="admin-role-name">{u.username === "admin" ? t("profile.roleSuper")
                        : u.role === "admin" ? t("profile.roleAdmin") : t("profile.roleUser")}</div>
                    <div className="admin-role-ctrl">
                      <span className="admin-role-label">{t("admin.setAdminLabel")}</span>
                      <button type="button"
                              className={`switch ${u.role === "admin" ? "on" : ""}`}
                              title={u.username === "admin" ? t("admin.superLocked")
                                     : (u.role === "admin" ? t("admin.removeAdmin") : t("admin.setAdmin"))}
                              disabled={busy || u.username === "admin"}
                              onClick={() => act(() => adminApi.setRole(u.id, u.role === "admin" ? "user" : "admin"),
                                                  t("admin.roleOk"))}>
                        <span className="switch-knob" />
                      </button>
                    </div>
                  </td>
                  <td>
                    <span className={`admin-chip ${u.disabled ? "off" : "on"}`}>
                      {u.disabled ? t("admin.disabled") : t("admin.enabled")}
                    </span>
                  </td>
                  <td className="admin-log-time">{(() => {
                    const [d, tm] = String(u.created_at || "").split("T");
                    return <><span className="admin-log-date">{d}</span>{tm && <span className="admin-log-clock">{tm.slice(0, 8)}</span>}</>;
                  })()}</td>
                  <td className="admin-ops">
                    <button className="btn small" disabled={busy}
                            onClick={() => act(() => adminApi.toggleUser(u.id), u.disabled ? t("admin.unbanOk") : t("admin.disabledOk"))}>
                      {u.disabled ? t("admin.unban") : t("admin.disable")}
                    </button>
                    <button className="btn small" disabled={busy}
                            onClick={() => { setPwdDlg(u); setPwdInput(""); }}>{t("admin.resetPwd")}</button>
                    <button className="btn small danger" disabled={busy}
                            onClick={() => setConfirmDlg({
                              title: t("admin.delUserTitle"),
                              desc: t("admin.delUserConfirm", { name: u.username }),
                              onOk: () => act(() => adminApi.deleteUser(u.id), t("admin.delUserOk")),
                            })}>{t("admin.delete")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <div className="admin-pager">
            <button className="btn small" disabled={page <= 1} onClick={() => { setPage(page - 1); load(page - 1); }}>‹</button>
            <span>{t("admin.pageInfo", { page, total: totalPages })}</span>
            <button className="btn small" disabled={page >= totalPages} onClick={() => { setPage(page + 1); load(page + 1); }}>›</button>
          </div>
        </>
      )}

      {/* 删除确认弹窗（组件内，非浏览器 confirm） */}
      {confirmDlg && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setConfirmDlg(null); }}>
          <div className="modal admin-confirm">
            <div className="modal-head"><span className="modal-title">{confirmDlg.title}</span></div>
            <div className="admin-confirm-desc">{confirmDlg.desc}</div>
            <div className="admin-confirm-foot">
              <button className="btn" onClick={() => setConfirmDlg(null)}>{t("common.cancel")}</button>
              <button className="btn danger" onClick={() => { const ok = confirmDlg.onOk; setConfirmDlg(null); ok && ok(); }}>
                {t("common.confirm")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 重置密码弹窗（组件内输入，非浏览器 prompt） */}
      {pwdDlg && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setPwdDlg(null); }}>
          <div className="modal admin-confirm">
            <div className="modal-head"><span className="modal-title">{t("admin.resetPwdTitle", { name: pwdDlg.username })}</span></div>
            <PasswordInput value={pwdInput} className="admin-pwd-input"
                           placeholder={t("admin.resetPwdPlaceholder")}
                           onChange={setPwdInput} />
            <div className="admin-tips">{t("auth.passwordRule")}</div>
            <div className="admin-confirm-foot">
              <button className="btn" onClick={() => setPwdDlg(null)}>{t("common.cancel")}</button>
              <button className="btn primary" onClick={() => {
                if (!pwdInput) { toast("err", t("admin.resetPwdRequired")); return; }
                const id = pwdDlg.id;
                setPwdDlg(null);
                act(() => adminApi.resetPassword(id, pwdInput), t("admin.resetPwdOk"));
              }}>{t("common.confirm")}</button>
            </div>
          </div>
        </div>
      )}

      {/* 新建用户弹窗（admin 直接创建，创建后可直接登录） */}
      {addOpen && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setAddOpen(false); }}>
          <div className="modal admin-confirm">
            <div className="modal-head"><span className="modal-title">{t("admin.addUser")}</span></div>
            <div className="admin-add-form">
              <label className="admin-add-row">
                <span className="admin-add-k">{t("auth.username")}</span>
                <input value={addForm.username} autoFocus placeholder={t("admin.userNamePlaceholder")}
                       onChange={(e) => setAddForm({ ...addForm, username: e.target.value })} />
              </label>
              <label className="admin-add-row">
                <span className="admin-add-k">{t("auth.password")}</span>
                <PasswordInput value={addForm.password} onChange={(v) => setAddForm({ ...addForm, password: v })} />
              </label>
              <div className="admin-add-hint">{t("auth.passwordRule")}</div>
              <label className="admin-add-row">
                <span className="admin-add-k">{t("auth.confirmPassword")}</span>
                <PasswordInput value={addForm.confirm} onChange={(v) => setAddForm({ ...addForm, confirm: v })} />
              </label>
              <label className="admin-add-row">
                <span className="admin-add-k">{t("auth.emailOptional")}</span>
                <input value={addForm.email} placeholder={t("admin.emailPlaceholder")}
                       onChange={(e) => setAddForm({ ...addForm, email: e.target.value })} />
              </label>
              <label className="admin-add-row">
                <span className="admin-add-k">{t("profile.role")}</span>
                <select value={addForm.role}
                        onChange={(e) => setAddForm({ ...addForm, role: e.target.value })}>
                  <option value="user">{t("profile.roleUser")}</option>
                  <option value="admin">{t("profile.roleAdmin")}</option>
                </select>
              </label>
            </div>
            <div className="admin-confirm-foot">
              <button className="btn" onClick={() => setAddOpen(false)}>{t("common.cancel")}</button>
              <button className="btn primary" disabled={busy} onClick={async () => {
                if (!addForm.username.trim()) { toast("err", t("admin.userNameRequired")); return; }
                if (!addForm.password) { toast("err", t("admin.resetPwdRequired")); return; }
                if (addForm.password !== addForm.confirm) { toast("err", t("auth.pwdMismatch")); return; }
                setBusy(true);
                try {
                  await adminApi.createUser({
                    username: addForm.username.trim(), password: addForm.password,
                    email: addForm.email.trim(), role: addForm.role,
                  });
                  toast("ok", t("admin.userCreated"));
                  setAddOpen(false);
                  load(1, search);
                } catch (e) {
                  toast("err", e.message);
                } finally {
                  setBusy(false);
                }
              }}>{t("common.confirm")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* 功能开关 */
function Features() {
  const { t } = useTranslation();
  const [feats, setFeats] = useState(null);
  const { toast, el } = useToast();
  async function load() {
    try { setFeats((await adminApi.features()).features); } catch (e) { toast("err", e.message); }
  }
  useEffect(() => { load(); }, []); // eslint-disable-line
  const names = ["detect", "verify", "rsverify", "face"];
  const labels = { detect: t("home.detectTitle"), verify: t("home.verifyTitle"),
                   rsverify: t("home.rsTitle"), face: t("home.faceTitle") };
  return (
    <div className="admin-panel">
      <div className="admin-panel-title">{t("admin.features")}</div>
      {el}
      <div className="admin-feature-list">
        {names.map((n) => {
          const on = feats ? feats.find((f) => f.name === n)?.enabled : true;
          return (
            <div className="admin-feature-item" key={n}>
              <div>
                <div className="admin-feature-name">{labels[n] || n}</div>
                <div className="admin-feature-desc">
                  {on ? t("admin.featureOpen") : t("admin.featureClosed")}
                </div>
              </div>
              <button
                className={`switch ${on ? "on" : ""}`}
                disabled={!feats}
                onClick={async () => {
                  try {
                    await adminApi.setFeature(n, !on);
                    toast("ok", t("admin.featureSaved"));
                    load();
                  } catch (e) { toast("err", e.message); }
                }}>
                <span className="switch-knob" />
              </button>
            </div>
          );
        })}
      </div>
      <div className="admin-tips">{t("admin.featureHint")}</div>
    </div>
  );
}

/* 系统公告 */
function Announcements() {
  const { t } = useTranslation();
  const [list, setList] = useState([]);
  const [editing, setEditing] = useState(null); // null=不编辑; {id?, title, content, enabled}
  const { toast, el } = useToast();
  async function load() {
    try { setList((await adminApi.announcements()).items); } catch (e) { toast("err", e.message); }
  }
  useEffect(() => { load(); }, []); // eslint-disable-line
  // 公告变化 → 通知全局（App 热更新顶栏横幅）
  function notifyChanged() { window.dispatchEvent(new Event("announce-changed")); }
  async function save() {
    if (!editing || !editing.title.trim()) { toast("err", t("admin.annTitleRequired")); return; }
    try {
      if (editing.id) await adminApi.updateAnnouncement(editing.id, editing);
      else await adminApi.createAnnouncement(editing);
      toast("ok", t("admin.annSaved"));
      setEditing(null);
      load();
      notifyChanged();
    } catch (e) { toast("err", e.message); }
  }
  return (
    <div className="admin-panel">
      <div className="admin-panel-title">{t("admin.announcements")}</div>
      {el}
      <button className="btn primary admin-ann-add" onClick={() => setEditing({ title: "", content: "", enabled: true })}>
        {t("admin.annNew")}
      </button>
      {editing && (
        <div className="admin-ann-form">
          <input placeholder={t("admin.annTitle")} value={editing.title}
                 onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
          <textarea rows={3} placeholder={t("admin.annContent")} value={editing.content}
                    onChange={(e) => setEditing({ ...editing, content: e.target.value })} />
          <div className="admin-ann-foot">
            <span className="admin-fill" />
            <button className="btn admin-btn-fixed" onClick={() => setEditing(null)}>{t("common.cancel")}</button>
            <button className="btn primary admin-btn-fixed" onClick={save}>{t("common.confirm")}</button>
          </div>
        </div>
      )}
      <div className="admin-table-scroll">
      <table className="admin-table admin-ann-table">
        <thead><tr><th>ID</th><th>{t("admin.annTitle")}</th><th>{t("admin.annContent")}</th><th>{t("admin.ops")}</th></tr></thead>
        <tbody>
          {list.map((a) => (
            <tr key={a.id}>
              <td>{a.id}</td>
              <td>{a.title}</td>
              <td className="admin-ann-content">{a.content}</td>
              <td className="admin-ops">
                <button type="button" className={`switch ${a.enabled ? "on" : ""}`}
                        title={t("admin.annEnabled")}
                        onClick={async () => {
                          try { await adminApi.updateAnnouncement(a.id, { enabled: !a.enabled }); load(); notifyChanged(); }
                          catch (e) { toast("err", e.message); }
                        }}>
                  <span className="switch-knob" />
                </button>
                <button className="btn small" onClick={() => setEditing({ id: a.id, title: a.title, content: a.content, enabled: !!a.enabled })}>{t("admin.edit")}</button>
                <button className="btn small danger"
                        onClick={async () => {
                          try { await adminApi.deleteAnnouncement(a.id); toast("ok", t("admin.annDeleted")); load(); notifyChanged(); }
                          catch (e) { toast("err", e.message); }
                        }}>{t("admin.delete")}</button>
              </td>
            </tr>
          ))}
          {list.length === 0 && !editing && <tr><td colSpan={4} className="admin-empty">{t("admin.annEmpty")}</td></tr>}
        </tbody>
      </table>
      </div>
    </div>
  );
}

/* 操作日志 */
function Logs() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [action, setAction] = useState("");
  const [operator, setOperator] = useState("");
  const [fromTs, setFromTs] = useState("");
  const [toTs, setToTs] = useState("");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [jump, setJump] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const { toast, el } = useToast();

  async function load(p = page, s = size, a = action, o = operator, f = fromTs, tt = toTs) {
    try {
      setData(await adminApi.logs({ page: p, size: s, action: a, operator: o, from: f || undefined, to: tt || undefined }));
    } catch (e) { toast("err", e.message); }
  }
  useEffect(() => { load(1, 20, "", "", "", ""); }, []); // eslint-disable-line
  const totalPages = data ? Math.max(1, Math.ceil(data.total / size)) : 1;

  // 重置搜索条件（清空输入，回到第一页）
  function reset() {
    setAction(""); setOperator(""); setFromTs(""); setToTs(""); setJump(""); setPage(1);
    load(1, size, "", "", "", "");
  }

  // 时间列展示：日期与时间分两行（避免在 "8-" 后换行）
  function fmtLogTime(ts) {
    if (!ts) return { date: "", time: "" };
    const [d, tm] = String(ts).split("T");
    return { date: d, time: tm ? tm.slice(0, 8) : "" };
  }

  return (
    <div className="admin-panel">
      <div className="admin-panel-title">{t("admin.logs")}</div>
      {el}
      <div className="admin-toolbar">
        <input value={action} placeholder={t("admin.logAction")} onChange={(e) => setAction(e.target.value)} />
        <input value={operator} placeholder={t("admin.logOperator")} onChange={(e) => setOperator(e.target.value)} />
        <DateTimePicker value={fromTs} title={t("admin.logFrom")} onChange={setFromTs} />
        <DateTimePicker value={toTs} title={t("admin.logTo")} onChange={setToTs} />
      </div>
      <div className="admin-toolbar admin-toolbar2">
        <label className="admin-size-label">{t("admin.logPerPage")}</label>
        <select className="admin-size-select" value={size}
                onChange={(e) => { const s = +e.target.value; setSize(s); setPage(1); load(1, s, action, operator, fromTs, toTs); }}>
          {[10, 20, 50].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <span className="admin-fill" />
        <button className="btn" onClick={reset}>{t("admin.logReset")}</button>
        <button className="btn primary" onClick={() => { setPage(1); load(1, size, action, operator, fromTs, toTs); }}>{t("admin.search")}</button>
        <button className="btn danger" onClick={() => setConfirmClear(true)}>{t("admin.logClear")}</button>
      </div>
      {!data && <div className="admin-empty">{t("common.loading")}</div>}
      {data && (
        <>
          <div className="admin-table-scroll">
          <table className="admin-table">
            <thead><tr><th>{t("admin.logTime")}</th><th>{t("admin.logOperator")}</th><th>{t("admin.logAction")}</th><th>{t("admin.logTarget")}</th><th>{t("admin.logResult")}</th><th>IP</th></tr></thead>
            <tbody>
              {data.items.map((l) => {
                const dt = fmtLogTime(l.created_at);
                return (
                  <tr key={l.id}>
                    <td className="admin-log-time"><span className="admin-log-date">{dt.date}</span><span className="admin-log-clock">{dt.time}</span></td>
                    <td>{l.operator_name}</td>
                    <td>{l.action}</td>
                    <td className="admin-ann-content">{l.target}</td>
                    <td><span className={`admin-chip ${l.result === "ok" ? "on" : "off"}`}>{l.result}</span></td>
                    <td>{l.ip || "-"}</td>
                  </tr>
                );
              })}
              {data.items.length === 0 && <tr><td colSpan={6} className="admin-empty">{t("admin.logEmpty")}</td></tr>}
            </tbody>
          </table>
          </div>
          <div className="admin-pager">
            <button className="btn small" disabled={page <= 1} onClick={() => { setPage(page - 1); load(page - 1); }}>‹</button>
            <span>{t("admin.pageInfo", { page, total: totalPages })}</span>
            <button className="btn small" disabled={page >= totalPages} onClick={() => { setPage(page + 1); load(page + 1); }}>›</button>
            <span className="admin-range-sep">·</span>
            <input className="admin-jump" value={jump} placeholder={t("admin.logJump")}
                   onChange={(e) => setJump(e.target.value)}
                   onKeyDown={(e) => {
                     if (e.key !== "Enter") return;
                     const p = Math.max(1, Math.min(totalPages, parseInt(jump, 10) || 1));
                     setPage(p); setJump("");
                     load(p);
                   }} />
            <button className="btn small" onClick={() => {
              const p = Math.max(1, Math.min(totalPages, parseInt(jump, 10) || 1));
              setPage(p); setJump(""); load(p);
            }}>{t("admin.logGo")}</button>
          </div>
        </>
      )}

      {/* 清空日志确认弹窗（组件内，非浏览器 confirm） */}
      {confirmClear && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setConfirmClear(false); }}>
          <div className="modal admin-confirm">
            <div className="modal-head"><span className="modal-title">{t("admin.logClearTitle")}</span></div>
            <div className="admin-confirm-desc">{t("admin.logClearConfirm")}</div>
            <div className="admin-confirm-foot">
              <button className="btn" onClick={() => setConfirmClear(false)}>{t("common.cancel")}</button>
              <button className="btn danger" onClick={async () => {
                setConfirmClear(false);
                try {
                  await adminApi.clearLogs();
                  toast("ok", t("admin.logCleared"));
                  setPage(1);
                  load(1, size, "", "", "", "");
                } catch (e) { toast("err", e.message); }
              }}>{t("common.confirm")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* 数据管理（批次5.2）：统计 + 清空游客/用户/全部数据（危险操作需输入确认文案） */
function Data() {
  const { t } = useTranslation();
  const [stats, setStats] = useState(null);
  const [dlg, setDlg] = useState(null);   // {kind, title, desc, btn}
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const { toast, el } = useToast();

  async function load() {
    try { setStats(await adminApi.dataStats()); } catch (e) { toast("err", e.message); }
  }
  useEffect(() => { load(); }, []); // eslint-disable-line

  async function doClear(kind) {
    setBusy(true);
    setDlg(null);
    try {
      if (kind === "files") await adminApi.clearFiles();
      else if (kind === "config") await adminApi.clearConfig();
      else await adminApi.clearAll();
      toast("ok", t("admin.dataCleared"));
      load();
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  const sysNames = { detect: t("home.detectTitle"), smart: t("home.verifyTitle"), rs: t("home.rsTitle"), face: t("home.faceTitle") };
  const sys = (stats && stats.systems) || {};

  return (
    <div className="admin-panel">
      <div className="admin-panel-title">{t("admin.data")}</div>
      {el}
      {!stats && <div className="admin-empty">{t("common.loading")}</div>}
      {stats && (
        <>
          <div className="admin-data-stats">
            <div className="admin-stat">
              <div className="admin-stat-value">{stats.users}</div>
              <div className="admin-stat-label">{t("admin.userTotal")}</div>
            </div>
            {Object.entries(sys).map(([key, s]) => (
              <div className="admin-stat" key={key}>
                <div className="admin-stat-value">{s.user + s.guest}</div>
                <div className="admin-stat-label">
                  <div className="admin-stat-name">{sysNames[key]}</div>
                  <div className="admin-stat-sub">
                    <span>{t("admin.dataUsers")} {s.user}</span>
                    <span>{t("admin.dataGuests")} {s.guest}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="admin-panel-title admin-sub">{t("admin.dataOps")}</div>
          <div className="admin-data-ops">
            <button className="btn" disabled={busy}
                    onClick={() => { setTyped(""); setDlg({ kind: "files", title: t("admin.dataClearFiles"), desc: t("admin.dataClearFilesDesc"), btn: t("admin.dataTypedConfirm") }); }}>
              {t("admin.dataClearFiles")}
            </button>
            <button className="btn" disabled={busy}
                    onClick={() => { setTyped(""); setDlg({ kind: "config", title: t("admin.dataClearConfig"), desc: t("admin.dataClearConfigDesc"), btn: t("admin.dataTypedConfirm") }); }}>
              {t("admin.dataClearConfig")}
            </button>
            <button className="btn danger" disabled={busy}
                    onClick={() => { setTyped(""); setDlg({ kind: "all", title: t("admin.dataClearAll"), desc: t("admin.dataClearAllDesc"), btn: t("admin.dataTypedConfirm") }); }}>
              {t("admin.dataClearAll")}
            </button>
          </div>
          <div className="admin-tips">{t("admin.dataHint")}</div>
        </>
      )}

      {/* 危险操作确认弹窗：必须输入"确认清空"文案 */}
      {dlg && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setDlg(null); }}>
          <div className="modal admin-confirm">
            <div className="modal-head"><span className="modal-title">{dlg.title}</span></div>
            <div className="admin-confirm-desc">{dlg.desc}</div>
            <input className="admin-pwd-input" value={typed} placeholder={t("admin.dataTypedPlaceholder")}
                   onChange={(e) => setTyped(e.target.value)} />
            <div className="admin-confirm-foot">
              <button className="btn" onClick={() => setDlg(null)}>{t("common.cancel")}</button>
              <button className="btn danger" disabled={typed !== t("admin.dataTypedConfirm")}
                      onClick={() => doClear(dlg.kind)}>{t("admin.dataClearGo")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* 人脸库管理（全局 faces.db）：分页/模糊搜索/新增/改名/换照片/批量删除/图片放大 */
function FaceLibrary() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(new Set());
  const [lightbox, setLightbox] = useState(null);        // 放大查看 {src, name}
  const [addDlg, setAddDlg] = useState(null);            // {file, name} 新增弹窗
  const [renameDlg, setRenameDlg] = useState(null);      // {record_id, name}
  const [photoDlg, setPhotoDlg] = useState(null);        // {record_id, file} 换照片
  const [conflictDlg, setConflictDlg] = useState(null);  // {name, conflict, file}
  const [confirmDel, setConfirmDel] = useState(null);    // {ids} 删除确认
  const { toast, el } = useToast();
  const size = 10;
  const addInput = useRef(null);
  const addPhotoInput = useRef(null);
  const photoInput = useRef(null);

  async function load(p = page, s = search) {
    setBusy(true);
    try {
      const d = await fetchLibrary(s, p, size);
      setData(d);
      setChecked(new Set());
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => { load(1, ""); }, []); // eslint-disable-line

  const totalPages = data ? Math.max(1, Math.ceil(data.total / size)) : 1;
  const items = (data && data.items) || [];

  function toggleAll(e) {
    setChecked(e.target.checked ? new Set(items.map((it) => it.id)) : new Set());
  }
  function toggleOne(id) {
    setChecked((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }

  // 新增人员（查重 → need_confirm / 直接入库）
  async function submitAdd() {
    const name = (addDlg.name || "").trim();
    if (!name) { toast("err", t("face.nameRequired")); return; }
    setBusy(true);
    try {
      const d = await libraryAdd(addDlg.file, name);
      if (d && d.need_confirm) {
        setAddDlg(null);
        setConflictDlg({ name, conflict: d.conflict, file: addDlg.file });
        return;
      }
      setAddDlg(null);
      toast("ok", t("face.saved"));
      load(1, search);
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function resolveConflict(mode) {
    const { name, file } = conflictDlg;
    setConflictDlg(null);
    setBusy(true);
    try {
      await libraryAdd(file, name, mode);
      toast("ok", mode === "overwrite" ? t("face.overwritten") : t("face.addedNew"));
      load(1, search);
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitRename() {
    const name = (renameDlg.name || "").trim();
    if (!name) { toast("err", t("face.nameRequired")); return; }
    setBusy(true);
    try {
      await libraryRename(renameDlg.record_id, name);
      setRenameDlg(null);
      toast("ok", t("face.renamed"));
      load();
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitPhoto() {
    setBusy(true);
    try {
      await libraryPhoto(photoDlg.record_id, photoDlg.file);
      setPhotoDlg(null);
      toast("ok", t("face.photoUpdated"));
      load();
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function doDelete() {
    const ids = [...confirmDel.ids];
    setConfirmDel(null);
    setBusy(true);
    try {
      await libraryDelete(ids);
      toast("ok", t("face.deleted", { n: ids.length }));
      load();
    } catch (e) {
      toast("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-panel">
      <div className="admin-panel-title">{t("admin.facelib")}
        {data && <span className="dim" style={{ marginLeft: 10, fontSize: 12 }}>
          {t("admin.facelibStat", { records: data.total, persons: data.persons })}
        </span>}
      </div>
      {el}
      <div className="admin-toolbar">
        <input className="admin-search" value={search} placeholder={t("admin.facelibSearch")}
               onChange={(e) => setSearch(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") { setPage(1); load(1, search); } }} />
        <button className="btn small" disabled={busy} onClick={() => { setPage(1); load(1, search); }}>
          {t("admin.search")}
        </button>
        <button className="btn primary small" disabled={busy}
                onClick={() => addInput.current && addInput.current.click()}>
          + {t("admin.facelibAdd")}
        </button>
        <button className="btn danger small" disabled={busy || !checked.size}
                onClick={() => setConfirmDel({ ids: [...checked] })}>
          {t("admin.facelibDeleteSelected", { n: checked.size })}
        </button>
      </div>
      <input ref={addInput} type="file" accept="image/*" style={{ display: "none" }}
             onChange={(e) => {
               const f = e.target.files && e.target.files[0];
               e.target.value = "";
               if (f) setAddDlg({ file: f, name: "" });
             }} />
      <input ref={photoInput} type="file" accept="image/*" style={{ display: "none" }}
             onChange={(e) => {
               const f = e.target.files && e.target.files[0];
               e.target.value = "";
               if (f && photoDlg) setPhotoDlg({ ...photoDlg, file: f });
             }} />

      <div className="table-wrap admin-table">
        <table>
          <thead>
            <tr>
              <th style={{ width: 32 }}><input type="checkbox" onChange={toggleAll}
                  checked={items.length > 0 && items.every((it) => checked.has(it.id))} /></th>
              <th className="th-center" style={{ width: 64 }}>{t("face.libThumb")}</th>
              <th>{t("face.name")}</th>
              <th style={{ width: 130 }}>{t("face.personId")}</th>
              <th style={{ width: 90 }}>{t("face.source")}</th>
              <th style={{ width: 90 }}>{t("face.createdBy")}</th>
              <th style={{ width: 70 }}>{t("face.bound")}</th>
              <th style={{ width: 140 }}>{t("face.time")}</th>
              <th className="th-center" style={{ width: 150 }}>{t("face.action")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} className={checked.has(it.id) ? "row-checked" : ""}
                  onDoubleClick={(e) => {
                    const td = e.target.closest("td");
                    if (td && (td.classList.contains("check-cell") || td.classList.contains("cell-ops"))) return;
                    toggleOne(it.id);
                  }}>
                <td className="check-cell" onClick={(e) => { e.stopPropagation(); toggleOne(it.id); }}>
                  <input type="checkbox" checked={checked.has(it.id)} readOnly />
                </td>
                <td>
                  {it.thumb
                    ? <img src={it.thumb} alt="" className="thumb face-thumb"
                           style={{ cursor: "zoom-in" }}
                           onClick={() => setLightbox({ src: it.thumb, name: it.name })} />
                    : <div className="thumb thumb-ph">-</div>}
                </td>
                <td className="cell-name">{it.name}</td>
                <td className="dim cell-name">{it.person_id}</td>
                <td>{it.source || "-"}</td>
                <td className="dim">{it.created_by || "-"}</td>
                <td>{it.bound ? <span className="jud-text jud-yes">{t("admin.yes")}</span>
                  : <span className="dim">-</span>}</td>
                <td className="dim">{it.created_at}</td>
                <td className="cell-ops">
                  <button className="btn small" onClick={() => setRenameDlg({ record_id: it.id, name: it.name })}>
                    {t("admin.facelibRename")}
                  </button>
                  <button className="btn small"
                          onClick={() => { setPhotoDlg({ record_id: it.id, name: it.name, file: null }); }}>
                    {t("admin.facelibPhoto")}
                  </button>
                  <button className="btn small danger"
                          onClick={() => setConfirmDel({ ids: [it.id] })}>{t("common.delete")}</button>
                </td>
              </tr>
            ))}
            {!items.length && !busy && <tr><td colSpan={9} className="empty">{t("admin.facelibEmpty")}</td></tr>}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      <div className="admin-pager">
        <button className="btn small" disabled={page <= 1 || busy}
                onClick={() => { const p = page - 1; setPage(p); load(p, search); }}>‹</button>
        <span className="admin-pager-info">{page} / {totalPages}</span>
        <button className="btn small" disabled={page >= totalPages || busy}
                onClick={() => { const p = page + 1; setPage(p); load(p, search); }}>›</button>
      </div>

      {/* 图片放大查看 */}
      {lightbox && (
        <div className="modal-mask" onClick={() => setLightbox(null)}>
          <div className="face-lightbox" onClick={(e) => e.stopPropagation()}>
            <img src={lightbox.src} alt="" />
            <div className="face-lightbox-name">{lightbox.name}</div>
            <button className="btn small" onClick={() => setLightbox(null)}>✕</button>
          </div>
        </div>
      )}

      {/* 新增弹窗（照片 + 姓名） */}
      {addDlg && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setAddDlg(null); }}>
          <div className="modal face-manual-modal">
            <div className="modal-head">
              <span className="modal-title">{t("admin.facelibAdd")}</span>
              <button className="btn small" onClick={() => setAddDlg(null)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="detail-row"><span>{t("face.photo")}</span>
                <div className="face-add-photo">
                  {addDlg.preview
                    ? <img src={addDlg.preview} alt="" className="thumb face-thumb" />
                    : <div className="thumb thumb-ph">-</div>}
                  <button className="btn small"
                          onClick={() => addPhotoInput.current && addPhotoInput.current.click()}>
                    {t("face.pickPhoto")}
                  </button>
                  <input ref={addPhotoInput} type="file" accept="image/*" style={{ display: "none" }}
                         onChange={(e) => {
                           const f = e.target.files && e.target.files[0];
                           e.target.value = "";
                           if (f) setAddDlg({ ...addDlg, file: f, preview: URL.createObjectURL(f) });
                         }} />
                </div>
              </div>
              <div className="detail-row"><span>{t("face.inputName")}</span>
                <input className="note-input" autoFocus value={addDlg.name}
                       placeholder={t("face.namePlaceholder")}
                       onChange={(e) => setAddDlg({ ...addDlg, name: e.target.value })}
                       onKeyDown={(e) => { if (e.key === "Enter") submitAdd(); }} /></div>
            </div>
            <div className="modal-foot">
              <button className="btn" onClick={() => setAddDlg(null)}>{t("common.cancel")}</button>
              <button className="btn primary" disabled={busy || !addDlg.file} onClick={submitAdd}>
                {t("admin.facelibAdd")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 改名弹窗 */}
      {renameDlg && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setRenameDlg(null); }}>
          <div className="modal face-manual-modal">
            <div className="modal-head">
              <span className="modal-title">{t("admin.facelibRename")}</span>
              <button className="btn small" onClick={() => setRenameDlg(null)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="dim face-manual-tip">{t("admin.facelibRenameTip")}</div>
              <div className="detail-row"><span>{t("face.newName")}</span>
                <input className="note-input" autoFocus value={renameDlg.name}
                       onChange={(e) => setRenameDlg({ ...renameDlg, name: e.target.value })}
                       onKeyDown={(e) => { if (e.key === "Enter") submitRename(); }} /></div>
            </div>
            <div className="modal-foot">
              <button className="btn" onClick={() => setRenameDlg(null)}>{t("common.cancel")}</button>
              <button className="btn primary" disabled={busy} onClick={submitRename}>{t("common.confirm")}</button>
            </div>
          </div>
        </div>
      )}

      {/* 换照片弹窗 */}
      {photoDlg && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setPhotoDlg(null); }}>
          <div className="modal face-manual-modal">
            <div className="modal-head">
              <span className="modal-title">{t("admin.facelibPhoto")}</span>
              <button className="btn small" onClick={() => setPhotoDlg(null)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="detail-row"><span>{t("face.name")}</span><b>{photoDlg.name}</b></div>
              <div className="detail-row"><span>{t("face.newPhoto")}</span>
                <button className="btn small" disabled={busy}
                        onClick={() => photoInput.current && photoInput.current.click()}>
                  {photoDlg.file ? photoDlg.file.name : t("face.pickPhoto")}
                </button></div>
            </div>
            <div className="modal-foot">
              <button className="btn" onClick={() => setPhotoDlg(null)}>{t("common.cancel")}</button>
              <button className="btn primary" disabled={busy || !photoDlg.file} onClick={submitPhoto}>
                {t("common.confirm")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 查重冲突弹窗 */}
      {conflictDlg && (
        <div className="modal-mask" onClick={() => setConflictDlg(null)}>
          <div className="modal face-manual-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{t("face.conflictTitle")}</span>
              <button className="btn small" onClick={() => setConflictDlg(null)}>✕</button>
            </div>
            <div className="detail-info">
              <div className="face-conflict-body">
                <div className="face-conflict-text"
                     dangerouslySetInnerHTML={{ __html: t("face.conflictBody", {
                       name: conflictDlg.name, old: conflictDlg.conflict.name,
                       sim: Math.round((conflictDlg.conflict.similarity || 0) * 100),
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

      {/* 删除确认 */}
      {confirmDel && (
        <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setConfirmDel(null); }}>
          <div className="modal admin-confirm">
            <div className="modal-head"><span className="modal-title">{t("common.confirm")}</span></div>
            <div className="admin-confirm-desc">{t("admin.facelibDeleteConfirm", { n: confirmDel.ids.length })}</div>
            <div className="admin-confirm-foot">
              <button className="btn" onClick={() => setConfirmDel(null)}>{t("common.cancel")}</button>
              <button className="btn danger" onClick={doDelete}>{t("common.delete")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
