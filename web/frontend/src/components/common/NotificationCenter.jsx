// 通知中心页（顶部标签 notify，登录才显示）
// 左侧：微信式消息列表（公告项 + 好友会话项）+ 搜索/添加好友/好友列表；右键置顶/删除/标记未读
// 右侧：聊天窗（7:3 = 消息区:输入框，菜单栏 zip/图片/表情）/ 公告页（无输入框）/ 好友申请面板
// 5s 轮询接收新消息（未读红圈 1→99+）；本地 localStorage 保留选中会话（刷新后停留）
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { chatApi, chatFileUrl, CHAT_REFRESH } from "../../api/chatApi.js";
import { useAuth } from "../../auth/AuthContext.jsx";

const MAX_BADGE = 99;

// 单色线条图标（currentColor 跟随主题文字色，非彩色 emoji）
function UserPlusIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="8.5" cy="7" r="4" />
      <line x1="20" y1="8" x2="20" y2="14" />
      <line x1="23" y1="11" x2="17" y2="11" />
    </svg>
  );
}
function UsersIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}
// 单色用户审批（lucide user-check 线性，好友申请用；与全局线条图标风格一致）
function UserCheckIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="8.5" cy="7" r="4" />
      <polyline points="17 11 19 13 22 10" />
    </svg>
  );
}
// 单色放大镜（lucide search 线性）
function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}
// 单色气泡（lucide message-circle 线性，替换占位表情）
function MessageCircle() {
  return (
    <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  );
}
// 单色回形针（lucide paperclip 线性，文件/zip 用）
function PaperclipIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}
// 单色图片（lucide image 线性）
function ImageIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
    </svg>
  );
}
// 单色笑脸（lucide smile 线性）
function SmileIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <path d="M8 14s1.5 2 4 2 4-2 4-2" />
      <line x1="9" y1="9" x2="9.01" y2="9" />
      <line x1="15" y1="9" x2="15.01" y2="9" />
    </svg>
  );
}
function TrashIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </svg>
  );
}
// 单色喇叭（lucide megaphone 线性，currentColor 跟随主题）
function AnnIcon({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m3 11 18-5v12L3 14v-3z" />
      <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
    </svg>
  );
}
const EMOJIS = ["😀","😁","😂","🤣","😊","😍","😘","😎","🤗","🙂","😉","😅","🥰","😢","😭","😡","👍","👎","👏","🙏","💪","🤝","🎉","❤️","🔥","💯","🤔","😴","👋","✌️","🤞","⭐","✅","🚀"];

function useToast() {
  const [msg, setMsg] = useState({ kind: "", text: "" });
  function toast(kind, text) {
    setMsg({ kind, text });
    setTimeout(() => setMsg({ kind: "", text: "" }), 3000);
  }
  const el = msg.text
    ? <div className={`notify-toast ${msg.kind === "ok" ? "ok" : "err"}`}>{msg.text}</div>
    : null;
  return { toast, el };
}

function badge(n) { return n >= MAX_BADGE ? "99+" : (n > 0 ? n : null); }
function avatarText(name) { return (name || "?").slice(0, 1).toUpperCase(); }
function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return String(ts).slice(11, 16);
  const pad = (n) => String(n).padStart(2, "0");
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const now = new Date();
  const day0 = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day0(now) - day0(d)) / 86400000);
  if (days === 0) return hm;                                  // 当天只显时间
  if (days === 1) return `昨天 ${hm}`;                        // 昨天
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`; // 更早：MM-DD HH:MM
}

export default function NotificationCenter() {
  const { t } = useTranslation();
  const auth = useAuth();
  const meId = auth.user?.id;
  const [convs, setConvs] = useState([]);        // 左侧列表 [{peer_id,name,uid,is_pinned,unread,last_msg,last_msg_at}]
  const [pending, setPending] = useState(0);     // 好友申请数
  const [q, setQ] = useState("");                // 左侧搜索
  const [activePeer, setActivePeer] = useState(null); // null未选 / 0公告 / -1申请 / >0好友
  const [msgs, setMsgs] = useState([]);          // 当前会话消息（升序）
  const [notices, setNotices] = useState([]);    // 公告会话内容
  const [hasMore, setHasMore] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [friendOpen, setFriendOpen] = useState(false);
  const [reqOpen, setReqOpen] = useState(false); // 好友申请（右侧请求面板同时作为入口）
  const [peerMeta, setPeerMeta] = useState({ name: "", uid: "" }); // 消息接口返回的对方资料（头部兜底：新建会话不在列表时仍能显示）
  const { toast, el: toastEl } = useToast();
  const inputRef = useRef(null);
  const [confirmBox, setConfirmBox] = useState(null); // 组件内确认弹窗（B8：破坏性操作禁浏览器 confirm）
  // 会话列表宽度（可拖拽调节，持久化；最小 200px 保留头像可见，最大 480px）
  const panelRef = useRef(null);
  const [panelW, setPanelW] = useState(() => {
    try {
      const v = parseInt(localStorage.getItem("notify_panel_w"), 10);
      return v >= 200 && v <= 480 ? v : 300;
    } catch (_) { return 300; }
  });
  useEffect(() => {
    if (panelRef.current) panelRef.current.style.width = `${panelW}px`;
  }, [panelW]);
  function startResize(e) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = panelRef.current ? panelRef.current.offsetWidth : 300;
    const onMove = (ev) => {
      setPanelW(Math.min(480, Math.max(200, startW + (ev.clientX - startX))));
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      try {
        localStorage.setItem("notify_panel_w",
          String(panelRef.current ? panelRef.current.offsetWidth : 300));
      } catch (_) {}
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  // 保存选中会话（刷新停留）
  useEffect(() => {
    if (activePeer !== null) localStorage.setItem("notify_active_peer", String(activePeer));
  }, [activePeer]);

  const refreshConvs = useCallback(async () => {
    // 兜底：左侧列表永远保留"系统公告"入口（即便无任何会话/公告/接口异常也不显示"暂无会话"）
    const annRow = { peer_id: 0, peer_name: t("notify.systemAnnounce"), peer_uid: "",
                     is_pinned: true, unread: 0, last_msg_at: "", last_msg: null };
    try {
      const d = await chatApi.conversations();
      const list = (d.items || []).slice();
      setPending(d.pending_requests || 0);
      if (!list.some((it) => it.peer_id === 0)) list.unshift(annRow);
      setConvs(list);
      return list;
    } catch (_) {
      // 接口异常/离线：系统公告栏仍保留，避免左侧列表空白
      setPending(0);
      setConvs([annRow]);
      return [annRow];
    }
  }, [t]);

  // 挂载：拉会话列表 + 恢复上次选中（仅当上次会话仍存在于列表才恢复，避免清空/删除后右侧残留聊天窗）
  useEffect(() => {
    (async () => {
      const list = await refreshConvs();
      let peer = null;
      try { peer = parseInt(localStorage.getItem("notify_active_peer"), 10); } catch (_) {}
      if (!Number.isNaN(peer) && peer >= 0 &&
          (peer === 0 || peer === -1 || list.some((c) => c.peer_id === peer))) {
        setActivePeer(peer);
      }
    })();
    // eslint-disable-next-line
  }, []);

  // 外部跳转（铃铛/App）：选中指定会话或进入申请面板
  useEffect(() => {
    const onOpen = (e) => {
      const { peer, mode } = e.detail || {};
      if (mode === "requests") setActivePeer(-1);
      else {
        const n = normPeer(peer);
        if (n !== null) setActivePeer(n);
      }
    };
    window.addEventListener("notify-open", onOpen);
    return () => window.removeEventListener("notify-open", onOpen);
  }, []);

  // 选中会话后加载消息并轮询；未选中则仅刷新会话列表
  useEffect(() => {
    const n = normPeer(activePeer);
    if (n === null || n < 0) {
      setPeerMeta({ name: "", uid: "" });
      if (n === null) refreshConvs();
      return;
    }
    setPeerMeta({ name: "", uid: "" });
    loadMessages(n);
    const iv = setInterval(() => pollActive(n), 5000);
    return () => clearInterval(iv);
    // eslint-disable-next-line
  }, [activePeer]);

  // 全局轮询：无论是否选中会话，每 5s 刷新会话列表（未读/申请数），新消息无需手动刷新页面
  useEffect(() => {
    const iv = setInterval(() => { refreshConvs(); }, 5000);
    return () => clearInterval(iv);
  }, [refreshConvs]);

  // 收到小铃铛广播（新消息/新申请）时即时刷新列表与当前会话，无需等 5s 轮询
  useEffect(() => {
    const onRefresh = () => {
      refreshConvs();
      const n = normPeer(activePeer);
      if (n > 0) loadMessages(n); // 拉当前会话消息（loadMessages 不广播，避免循环）
    };
    window.addEventListener(CHAT_REFRESH, onRefresh);
    return () => window.removeEventListener(CHAT_REFRESH, onRefresh);
    // eslint-disable-next-line
  }, [activePeer, refreshConvs]);

  // 归一化 peer：仅接受整数会话 id（0=公告/-1=申请/>0=好友），防止状态被污染成对象后拼进 URL（[object Object] 500）
  function normPeer(peer) {
    const n = Number(peer);
    return Number.isInteger(n) ? n : null;
  }

  async function loadMessages(peer) {
    try {
      const n = normPeer(peer);
      if (n === null) return;
      if (n === 0) {
        const d = await chatApi.notices();
        setNotices(d.items || []);
        if (d.items.length) await chatApi.markNoticesRead(d.items[d.items.length - 1].id);
        refreshConvs();
        return;
      }
      const d = await chatApi.messages(n);
      setMsgs(d.items || []);
      setHasMore((d.items || []).length >= 20);
      if (d.peer_name || d.peer_uid) setPeerMeta({ name: d.peer_name || "", uid: d.peer_uid || "" });
      refreshConvs();
    } catch (_) { /* 离线 */ }
  }

  async function pollActive(peer) {
    const n = normPeer(peer);
    if (n === 0) { refreshConvs(); return; }
    if (n === null) return;
    try {
      const d = await chatApi.messages(n);
      setMsgs((prev) => mergeMsgs(prev, d.items || []));
      setHasMore((d.items || []).length >= 20);
      refreshConvs();
      window.dispatchEvent(new Event(CHAT_REFRESH)); // 已读联动小铃铛未读，避免红点不同步
    } catch (_) { /* 离线 */ }
  }

  function mergeMsgs(prev, next) {
    const map = new Map();
    [...prev, ...next].forEach((m) => map.set(m.id, m));
    return Array.from(map.values()).sort((a, b) => a.id - b.id);
  }

  async function loadEarlier() {
    const n = normPeer(activePeer);
    if (n <= 0 || !msgs.length) return;
    const oldest = msgs[0].id;
    const d = await chatApi.messages(n, { before_id: oldest });
    setMsgs((prev) => mergeMsgs(prev, d.items || []));
    setHasMore((d.items || []).length >= 20);
  }

  // ---------- 好友 ==========
  async function doAddFriend(uid) {
    try {
      await chatApi.sendRequest(uid);
      toast("ok", t("notify.reqSent"));
      setAddOpen(false);
      window.dispatchEvent(new Event(CHAT_REFRESH)); // 对方铃铛 pending 及时更新
    } catch (e) { toast("err", e.message); }
  }
  async function doHandleReq(id, action) {
    try {
      await chatApi.handleRequest(id, action);
      setReqOpen(true); // 刷新右侧申请面板
      refreshConvs();   // 更新好友申请红点计数（处理后立即消失，无需刷新页面）
      window.dispatchEvent(new Event(CHAT_REFRESH)); // 同步小铃铛 pending 数
    } catch (e) { toast("err", e.message); }
  }
  async function doDeleteFriend(fid, name) {
    setConfirmBox({ title: t("notify.delFriendTitle"),
      text: t("notify.delFriendConfirm", { name }), danger: true,
      onOk: async () => {
        try { await chatApi.deleteFriend(fid); toast("ok", t("notify.delFriendDone")); refreshConvs(); }
        catch (e) { toast("err", e.message); }
      } });
  }
  async function openChatWith(fid) {
    setFriendOpen(false);
    setActivePeer(fid);
  }

  // ---------- 会话右键（置顶 / 删除聊天 / 标记未读） ----------
  async function doPin(item) {
    try { await chatApi.setPin(item.peer_id, !item.is_pinned); refreshConvs(); }
    catch (e) { toast("err", e.message); }
  }
  async function doDeleteConv(item) {
    setConfirmBox({ title: t("notify.delChatTitle"),
      text: t("notify.delChatConfirm", { name: item.peer_name }), danger: true,
      onOk: async () => {
        try { await chatApi.deleteConversation(item.peer_id); if (activePeer === item.peer_id) setActivePeer(null); refreshConvs(); }
        catch (e) { toast("err", e.message); }
      } });
  }
  async function doMarkUnread(item) {
    try { await chatApi.markUnread(item.peer_id); refreshConvs(); }
    catch (e) { toast("err", e.message); }
  }

  // ---------- 发送 ----------
  async function sendText() {
    const peer = activePeer;
    if (peer <= 0 || !inputRef.current) return;
    const content = inputRef.current.value.trim();
    if (!content) return;
    try {
      await chatApi.send(peer, "text", content);
      inputRef.current.value = "";
      await pollActive(peer);
      window.dispatchEvent(new Event(CHAT_REFRESH));
    } catch (e) { toast("err", e.message); }
  }
  // 两段式发送·第 2 步：把输入框里排队的待发附件正式发出
  async function sendPendingFiles(ids) {
    const peer = activePeer;
    if (peer <= 0 || !ids.length) return;
    await chatApi.sendPending(peer, ids);
    await pollActive(peer);
    refreshConvs();
    window.dispatchEvent(new Event(CHAT_REFRESH));
  }
  function appendEmoji(e) {
    if (!inputRef.current) return;
    inputRef.current.value += e;
    inputRef.current.focus();
  }

  // 独立一键清理聊天记录
  async function doClearChat() {
    const s = await chatApi.stats().catch(() => null);
    const mb = s ? s.mb : 0;
    setConfirmBox({ title: t("notify.clearChatTitle"),
      text: t("notify.clearChatConfirm", { mb: mb.toFixed(2) }), danger: true,
      onOk: async () => {
        try {
          await chatApi.clear();
          setActivePeer(null);
          localStorage.removeItem("notify_active_peer"); // 清空后刷新页面不再恢复残留会话
          setMsgs([]); setNotices([]);
          setReqOpen(false); setAddOpen(false); setFriendOpen(false);
          refreshConvs();
          window.dispatchEvent(new Event(CHAT_REFRESH));
          toast("ok", t("notify.clearChatDone"));
        } catch (e) { toast("err", e.message); }
      } });
  }

  const filtered = q.trim()
    ? convs.filter((c) =>
        (c.peer_name || "").toLowerCase().includes(q.trim().toLowerCase()) ||
        (c.peer_uid || "").includes(q.trim()))
    : convs;

  const activeItem = convs.find((c) => c.peer_id === activePeer);

  return (
    <div className="notify-layout">
      {toastEl}
      {/* ============ 左侧列表 ============ */}
      <aside className="notify-panel" ref={panelRef}>
        <div className="notify-toolbar">
          <div className="notify-search-wrap">
            <span className="notify-search-ico"><SearchIcon /></span>
            <input className="notify-search" value={q} placeholder={t("notify.searchPlaceholder")}
                   onChange={(e) => setQ(e.target.value)} />
          </div>
          <button className="notify-tool-btn" title={t("notify.addFriend")} onClick={() => setAddOpen(true)}><UserPlusIcon /></button>
          <button className="notify-tool-btn" title={t("notify.friendList")} onClick={() => setFriendOpen(true)}><UsersIcon /></button>
          <button className={`notify-tool-btn notify-req-btn${activePeer === -1 ? " active" : ""}`}
                  title={t("notify.friendRequests")} onClick={() => setActivePeer(-1)}>
            <UserCheckIcon />
            {badge(pending) && <span className="notify-req-badge">{badge(pending)}</span>}
          </button>
        </div>
        <div className="notify-list">
          {filtered.map((it) => (
            <NotifyRow key={it.peer_id} it={it} active={it.peer_id === activePeer}
                       onSelect={() => setActivePeer(it.peer_id)}
                       onPin={() => doPin(it)} onDel={() => doDeleteConv(it)} onUnread={() => doMarkUnread(it)} />
          ))}
          {!filtered.length && <div className="notify-empty">{t("notify.emptyList")}</div>}
        </div>
        <button className="notify-clear-btn" onClick={doClearChat} title={t("notify.clearChatHint")}>
          <TrashIcon /> {t("notify.clearChat")}
        </button>
      </aside>

      {/* 拖拽手柄：调节会话列表与聊天框宽度（最小 200px 保留头像，最大 480px） */}
      <div className="notify-resizer" onMouseDown={startResize} />

      {/* ============ 右侧内容 ============ */}
      <section className="notify-main">
        {activePeer === null && (
          <div className="notify-placeholder">
            <span className="notify-bubble-empty"><MessageCircle /></span>
            <span>{t("notify.selectChat")}</span>
          </div>
        )}
        {activePeer === 0 && (
          <NoticesPanel notices={notices} />
        )}
        {activePeer === -1 && (
          <RequestsPanel reqOpen={reqOpen} setReqOpen={setReqOpen}
                         onHandle={doHandleReq} />
        )}
        {activePeer > 0 && (
          <ChatWindow peer={activePeer} name={activeItem?.peer_name || peerMeta?.name || ""} uid={activeItem?.peer_uid || peerMeta?.uid || ""}
                      msgs={msgs} meId={meId} hasMore={hasMore} onEarlier={loadEarlier}
                      sendText={sendText} sendPendingFiles={sendPendingFiles} appendEmoji={appendEmoji}
                      inputRef={inputRef} toast={toast} />
        )}
      </section>

      {addOpen && <AddFriendModal onClose={() => setAddOpen(false)} onAdd={doAddFriend} toast={toast} />}
      {friendOpen && <FriendListModal meId={meId} onClose={() => setFriendOpen(false)}
                        onChat={openChatWith} onDelete={doDeleteFriend} />}

      {/* 组件内确认弹窗（B8：破坏性操作不用浏览器 confirm） */}
      {confirmBox && (
        <div className="modal-mask" onClick={() => setConfirmBox(null)}>
          <div className="modal notify-modal notify-confirm" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">{confirmBox.title || t("common.confirm")}</span>
              <button className="btn small" onClick={() => setConfirmBox(null)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="notify-confirm-text">{confirmBox.text}</div>
              <div className="notify-confirm-ops">
                <button className="btn small" onClick={() => setConfirmBox(null)}>{t("common.cancel")}</button>
                <button className="btn small danger" onClick={() => { const fn = confirmBox.onOk; setConfirmBox(null); fn && fn(); }}>{t("common.confirm")}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* 左侧一行（含右键菜单） */
function NotifyRow({ it, active, onSelect, onPin, onDel, onUnread }) {
  const { t } = useTranslation();
  const [menu, setMenu] = useState(false);
  const isAnn = it.peer_id === 0;
  return (
    <div className={`notify-row${active ? " active" : ""}`}
         onClick={onSelect}
         onContextMenu={(e) => { if (!isAnn) { e.preventDefault(); setMenu(true); } }}>
      <span className={`notify-avatar${isAnn ? " ann" : ""}`}>{isAnn ? <AnnIcon size={22} /> : avatarText(it.peer_name)}</span>
      <span className="notify-row-main">
        <span className="notify-row-name">
          <span className="notify-row-name-text">{it.peer_name}</span>
          {!isAnn && it.peer_uid && <span className="notify-row-uid">ID:{it.peer_uid}</span>}
          {!!it.is_pinned && <span className="notify-pin">置顶</span>}
        </span>
        <span className="notify-row-summary">{it.last_msg?.content || ""}</span>
      </span>
      {badge(it.unread) && <span className="notify-row-badge">{badge(it.unread)}</span>}
      {menu && !isAnn && (
        <>
          <div className="notify-cmenu-mask" onClick={() => setMenu(false)} onContextMenu={(e) => { e.preventDefault(); setMenu(false); }} />
          <div className="notify-cmenu">
            <div className="notify-cmenu-item" onClick={() => { setMenu(false); onPin(); }}>{t("notify.pin")}{it.is_pinned ? "✓" : ""}</div>
            <div className="notify-cmenu-item" onClick={() => { setMenu(false); onUnread(); }}>{t("notify.markUnread")}</div>
            <div className="notify-cmenu-item danger" onClick={() => { setMenu(false); onDel(); }}>{t("notify.deleteChat")}</div>
          </div>
        </>
      )}
    </div>
  );
}

/* 公告页（注册至今全部公告，无输入框） */
function NoticesPanel({ notices }) {
  const { t } = useTranslation();
  return (
    <div className="notify-chat">
      <div className="notify-chat-head">
        <span className="notify-avatar big ann"><AnnIcon size={24} /></span>
        <span className="notify-chat-head-name">{t("notify.systemAnnounce")}</span>
      </div>
      <div className="notify-msgs notify-ann">
        {!notices.length && <div className="notify-empty">{t("notify.noAnnounce")}</div>}
        {notices.map((a) => (
          <div className="ann-item" key={a.id}>
            <div className="ann-row">
              <span className="ann-avatar"><AnnIcon size={22} /></span>
              <div className="ann-bubble">
                <div className="ann-title">{a.title}</div>
                {a.content && <div className="ann-content">{a.content}</div>}
              </div>
            </div>
            <div className="ann-time">{a.created_at || ""}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* 好友申请处理面板 */
function RequestsPanel({ reqOpen, setReqOpen, onHandle }) {
  const { t } = useTranslation();
  const [list, setList] = useState([]);
  const [busy, setBusy] = useState({});
  // 面板仅在 activePeer===-1 时渲染，挂载即代表激活，必须立即拉取（不受 reqOpen 内部开关限制）
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  useEffect(() => { if (reqOpen) load(); }, [reqOpen]);
  async function load() {
    try { const d = await chatApi.requests(); setList(d.items || []); } catch (_) {}
  }
  async function handle(id, action) {
    setBusy((b) => ({ ...b, [id]: true }));
    try { await chatApi.handleRequest(id, action); load(); } catch (e) { /* toast handled up */ }
    finally { setBusy((b) => { const n = { ...b }; delete n[id]; return n; }); }
  }
  return (
    <div className="notify-chat">
      <div className="notify-chat-head">
        <span className="notify-chat-head-name">{t("notify.friendRequests")}</span>
      </div>
      <div className="notify-msgs">
        {!list.length && <div className="notify-empty">{t("notify.noRequests")}</div>}
        {list.filter((r) => r.dir !== "out").length > 0 && (
          <div className="req-group-title">{t("notify.receivedReqs")}</div>
        )}
        {list.filter((r) => r.dir !== "out").map((r) => {
          const done = r.status && r.status !== "pending";
          return (
          <div className="req-item" key={r.id}>
            <span className="notify-avatar">{avatarText(r.username)}</span>
            <span className="req-info">
              <span className="req-name">{r.username}</span>
              <span className="req-uid">ID:{r.uid}</span>
            </span>
            <span className="req-ops">
              {done ? (
                <span className="req-status">{r.status === "accepted" ? t("notify.accepted") : t("notify.declined")}</span>
              ) : (
                <>
                  <button className="btn small primary" disabled={busy[r.id]}
                          onClick={() => handle(r.id, "accept")}>{t("notify.accept")}</button>
                  <button className="btn small" disabled={busy[r.id]}
                          onClick={() => handle(r.id, "decline")}>{t("notify.decline")}</button>
                </>
              )}
            </span>
          </div>
          );
        })}
        {list.filter((r) => r.dir === "out").length > 0 && (
          <div className="req-group-title">{t("notify.sentReqs")}</div>
        )}
        {list.filter((r) => r.dir === "out").map((r) => (
          <div className="req-item" key={r.id}>
            <span className="notify-avatar">{avatarText(r.username)}</span>
            <span className="req-info">
              <span className="req-name">{r.username}</span>
              <span className="req-uid">ID:{r.uid}</span>
            </span>
            <span className="req-ops">
              <span className={`req-status${r.status === "pending" ? " req-wait" : ""}`}>
                {r.status === "pending" ? t("notify.waiting")
                  : r.status === "accepted" ? t("notify.added") : t("notify.failed")}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* 聊天窗：7:3 = 消息区 : 输入区，中间菜单栏（zip/图片/表情） */
function ChatWindow({ peer, name, uid, msgs, meId, hasMore, onEarlier, sendText, sendPendingFiles, appendEmoji, inputRef, toast }) {
  const { t } = useTranslation();
  const [bigImg, setBigImg] = useState(null); // 放大查看的图片 url
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [pending, setPending] = useState([]);   // 待发附件 [{id,msg_type,file_name,file_size,preview}]
  const [selIdx, setSelIdx] = useState(-1);
  const fileRef = useRef(null);
  const imgRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "auto" }); }, [msgs.length, peer]);

  // 切换会话时丢弃未发出的待发附件并释放本地预览
  useEffect(() => {
    setPending((prev) => { prev.forEach((p) => p.preview && URL.revokeObjectURL(p.preview)); return []; });
    setSelIdx(-1);
  }, [peer]);

  // 两段式发送·第 1 步：选择后仅上传到本人待发区排队，不立即发出
  async function stage(file) {
    if (!peer) return;
    try {
      const d = await chatApi.uploadPending(file);
      const preview = d.msg_type === "image" ? URL.createObjectURL(file) : null;
      setPending((prev) => [...prev, { id: d.id, msg_type: d.msg_type, file_name: d.file_name, file_size: d.file_size, preview }]);
    } catch (e) { toast("err", e.message); }
  }
  // 删除某个待发附件：撤销本地预览 + 同步删除后端落盘文件（各删各的，不影响对方）
  async function removePending(idx) {
    const p = pending[idx];
    if (!p) return;
    setPending((prev) => prev.filter((_, i) => i !== idx));
    setSelIdx(-1);
    if (p.preview) URL.revokeObjectURL(p.preview);
    try { await chatApi.deletePending(p.id); } catch (_) {}
  }
  // 点"发送"：先发待发附件，再发文本框内容
  async function handleSend() {
    const ids = pending.map((p) => p.id);
    if (ids.length) {
      try {
        await sendPendingFiles(ids);
        const prev = pending;
        setPending([]); setSelIdx(-1);
        prev.forEach((p) => p.preview && URL.revokeObjectURL(p.preview));
      } catch (e) { toast("err", e.message); return; }
    }
    if (sendText) await sendText();
  }

  return (
    <div className="notify-chat">
      <div className="notify-chat-head">
        <span className="notify-avatar big">{avatarText(name)}</span>
        <span className="notify-chat-head-name">{name}</span>
        <span className="notify-chat-head-uid">{uid ? `ID:${uid}` : ""}</span>
      </div>

      {/* 消息区（7 份） */}
      <div className="notify-msgs">
        {hasMore && <button className="notify-more" onClick={onEarlier}>{t("notify.loadEarlier")}</button>}
        {msgs.map((m) => (
          <MessageBubble key={m.id} m={m} meId={meId}
                         onZoom={(url) => setBigImg(url)} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* 输入区（3 份）— 顶部功能菜单栏（文件/图片/表情） */}
      <div className="notify-input">
        <div className="notify-toolbar-bar">
          <button className="tool-btn" title={t("notify.sendZip")} onClick={() => fileRef.current?.click()}><PaperclipIcon /></button>
          <button className="tool-btn" title={t("notify.sendImage")} onClick={() => imgRef.current?.click()}><ImageIcon /></button>
          <button className="tool-btn" title={t("notify.sendEmoji")} onClick={() => setEmojiOpen((v) => !v)}><SmileIcon /></button>
          {emojiOpen && (
            <>
              <div className="emoji-mask" onClick={() => setEmojiOpen(false)} />
              <div className="emoji-panel">
                {EMOJIS.map((e) => <span key={e} className="emoji-item" onClick={() => { appendEmoji(e); }}>{e}</span>)}
              </div>
            </>
          )}
        </div>
        <div className="notify-input-row">
          {/* 输入外壳：待发附件条 + 文本框嵌入同一个输入框内（选中附件后可用 Delete/Backspace 删除） */}
          <div className="notify-chatbox">
            {pending.length > 0 && (
              <div className="notify-pending">
                {pending.map((p, i) => (
                  <div key={p.id}
                       className={`pending-item${i === selIdx ? " sel" : ""}`}
                       tabIndex={0}
                       title={p.file_name}
                       onClick={(e) => { e.stopPropagation(); e.currentTarget.focus(); setSelIdx(i); }}
                       onKeyDown={(e) => {
                         if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); e.stopPropagation(); removePending(i); }
                         else if (e.key === "Escape") { e.preventDefault(); setSelIdx(-1); e.currentTarget.blur(); }
                       }}>
                    {p.msg_type === "image"
                      ? (p.preview
                          ? <img src={p.preview} alt="" className="pending-thumb" title={p.file_name} />
                          : <ImageIcon />)
                      : (<>
                          <span className="pending-z">Z</span>
                          <span className="pending-name">{p.file_name}</span>
                        </>)}
                    <span className="pending-x" title={t("notify.removePending")}
                          onClick={(e) => { e.stopPropagation(); removePending(i); }}>×</span>
                  </div>
                ))}
              </div>
            )}
            <textarea ref={inputRef} className="notify-textarea" placeholder={t("notify.inputPlaceholder")}
                      onClick={() => setSelIdx(-1)}
                      onKeyDown={(e) => {
                        // 键盘删除待发附件：有选中附件时删选中项；空输入框按 Backspace 删最后一个
                        if ((e.key === "Backspace" || e.key === "Delete") && pending.length) {
                          let target = -1;
                          if (selIdx >= 0) target = selIdx;
                          else if (e.key === "Backspace" && !e.target.value) target = pending.length - 1;
                          if (target >= 0) { e.preventDefault(); removePending(target); return; }
                        }
                        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
                      }} />
          </div>
          <button className="btn primary notify-send" onClick={handleSend}>{t("notify.send")}</button>
        </div>
      </div>

      {/* 隐藏文件/图片选择（选中后先排队不立即发） */}
      <input ref={fileRef} type="file" accept=".zip" style={{ display: "none" }}
             onChange={(e) => { const f = e.target.files && e.target.files[0]; if (f) stage(f); e.target.value = ""; }} />
      <input ref={imgRef} type="file" accept="image/*" style={{ display: "none" }}
             onChange={(e) => { const f = e.target.files && e.target.files[0]; if (f) stage(f); e.target.value = ""; }} />

      {/* 图片放大查看 / 下载 */}
      {bigImg && (
        <div className="img-zoom-mask" onClick={() => setBigImg(null)}>
          <div className="img-zoom" onClick={(e) => e.stopPropagation()}>
            <img src={bigImg} alt="" className="img-zoom-main" />
            <div className="img-zoom-ops">
              <a className="btn small" href={bigImg} download target="_blank" rel="noreferrer">{t("notify.download")}</a>
              <button className="btn small" onClick={() => setBigImg(null)}>{t("common.close")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* 单条消息气泡 */
function MessageBubble({ m, meId, onZoom }) {
  const auth = useAuth();
  const own = m.sender_id === meId;
  const url = m.msg_type === "image" || m.msg_type === "zip" ? chatFileUrl(m.id) : "";
  return (
    <div className={`chat-msg ${own ? "own" : ""}`}>
      <span className="chat-avatar">{own ? avatarText(auth.user?.username || "我") : "👤"}</span>
      <div className="chat-body">
        <div className="chat-bubble">
          {(m.msg_type === "text" || m.msg_type === "emoji") && (
            <span className="chat-text">{m.content}</span>
          )}
          {m.msg_type === "image" && (
            <img src={url} alt="" className="chat-img" onClick={() => onZoom(url)}
                 onError={(e) => { e.currentTarget.style.display = "none"; }} />
          )}
          {m.msg_type === "zip" && (
            <div className="zip-card">
              <div className="zip-left">Z</div>
              <div className="zip-right">
                <div className="zip-name" title={m.file_name}>{m.file_name}</div>
                <div className="zip-dl">
                  <a href={url} download={m.file_name} onClick={(e) => e.stopPropagation()}>
                    {m.file_size ? `${(m.file_size / 1024 / 1024).toFixed(1)}MB · ` : ""}{/* */}⬇ 下载
                  </a>
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="chat-time">{fmtTime(m.created_at)}</div>
      </div>
    </div>
  );
}

/* 添加好友弹窗 */
function AddFriendModal({ onClose, onAdd, toast }) {
  const { t } = useTranslation();
  const [kw, setKw] = useState("");
  const [result, setResult] = useState([]);
  const [state, setState] = useState("idle"); // idle/searching/hit/empty
  async function search() {
    const q = kw.trim();
    if (!q) return;
    setState("searching");
    try {
      const d = await chatApi.search(q);
      setResult(d.items || []);
      setState(d.items.length ? "hit" : "empty");
    } catch (e) { toast("err", e.message); setState("idle"); }
  }
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal notify-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t("notify.addFriend")}</span>
          <button className="btn small" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="add-friend-search">
            <input value={kw} placeholder={t("notify.searchUserPlaceholder")}
                   onChange={(e) => setKw(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
            <button className="btn primary" disabled={state === "searching"} onClick={search}>
              {t("notify.search")}
            </button>
          </div>
          <div className="add-friend-hint">{t("notify.searchHint")}</div>
          {state === "searching" && <div className="notify-empty">{t("common.loading")}</div>}
          {state === "empty" && <div className="notify-empty">{t("notify.noUser")}</div>}
          {state === "hit" && (
            <div className="add-friend-list">
              {result.map((u) => (
                <div className="add-friend-item" key={u.id}>
                  <span className="notify-avatar">{avatarText(u.username)}</span>
                  <span className="req-info">
                    <span className="req-name">{u.username}</span>
                    <span className="req-uid">ID:{u.uid}</span>
                  </span>
                  <button className="btn small primary" onClick={() => onAdd(u.id)}>{t("notify.addBtn")}</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* 好友列表弹窗 */
function FriendListModal({ meId, onClose, onChat, onDelete }) {
  const { t } = useTranslation();
  const [list, setList] = useState([]);
  useEffect(() => { chatApi.friends().then((d) => setList(d.items || [])).catch(() => {}); }, []);
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal notify-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t("notify.friendList")}</span>
          <button className="btn small" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {!list.length && <div className="notify-empty">{t("notify.noFriends")}</div>}
          {list.map((u) => (
            <div className="friend-item" key={u.id}>
              <span className="notify-avatar">{avatarText(u.username)}</span>
              <span className="req-info">
                <span className="req-name">{u.username}</span>
                <span className="req-uid">ID:{u.uid}</span>
              </span>
              <span className="req-ops">
                <button className="btn small primary" onClick={() => onChat(u.id)}>{t("notify.msgBtn")}</button>
                <button className="btn small danger" onClick={() => onDelete(u.id, u.username)}>{t("notify.deleteBtn")}</button>
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}