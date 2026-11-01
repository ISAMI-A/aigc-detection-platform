// 通知中心 · 小铃铛入口（顶栏用户区左侧）
// - hover 展开浮层菜单：顶部最新公告 + 用户消息（最近会话/好友申请）+ 底部"通知中心"按钮
// - click 进入通知中心页面（onOpen）
// - 登录用户 5s 轮询 /api/chat/summary：未读红点（公告未读 + 会话未读 + 待处理申请，99+ 封顶）
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { chatApi, CHAT_REFRESH } from "../../api/chatApi.js";
import { request } from "../../api/index.js";
import { useAuth } from "../../auth/AuthContext.jsx";

const MAX = 99;

// 单色线条铃铛（currentColor 跟随主题文字色，非彩色 emoji）
function BellSvg() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}

// 单色线条喇叭（lucide megaphone 线性，与通知中心公告图标一致）
function AnnSvg({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m3 11 18-5v12L3 14v-3z" />
      <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
    </svg>
  );
}

export default function BellMenu({ onOpen }) {
  const { t } = useTranslation();
  const auth = useAuth();
  const [show, setShow] = useState(false);
  const [sum, setSum] = useState(null);
  const [guestAnn, setGuestAnn] = useState(null); // 游客态最新公开公告（游客看不到登录态摘要，改用公开公告接口）
  const closeTimer = useRef(null);
  // 延迟关闭：鼠标从按钮移到下方弹窗的间隙不被判定为"离开"，避免弹窗一下滑就消失
  const scheduleClose = () => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setShow(false), 180);
  };
  const keepOpen = () => clearTimeout(closeTimer.current);
  useEffect(() => () => clearTimeout(closeTimer.current), []);

  // 统一刷新：供 5s 轮询 / 点击打开 / 全局 chat-refresh 复用，保证与通知中心未读同步
  const loadSum = useCallback(async () => {
    if (!auth.isLoggedIn) { setSum(null); return; }
    try {
      const d = await chatApi.summary();
      setSum((prev) => {
        const prevTotal = (prev?.total_unread || 0) + (prev?.pending || 0);
        const newTotal = (d.total_unread || 0) + (d.pending || 0);
        // 未读/申请增加时广播，通知中心即时刷新（减少/已读不广播，避免两端循环）
        if (newTotal > prevTotal) window.dispatchEvent(new Event(CHAT_REFRESH));
        return d;
      });
    } catch (_) { /* 游客/离线忽略 */ }
  }, [auth.isLoggedIn]);

  useEffect(() => {
    loadSum();
    const iv = setInterval(loadSum, 5000);
    window.addEventListener(CHAT_REFRESH, loadSum);
    return () => { clearInterval(iv); window.removeEventListener(CHAT_REFRESH, loadSum); };
  }, [loadSum]);

  // 游客态拉取公开公告（公告接口无需登录），让游客也能看到最新公告
  useEffect(() => {
    if (auth.isLoggedIn) { setGuestAnn(null); return; }
    let alive = true;
    request("/api/announcements").then((d) => {
      const items = (d && d.items) || [];
      if (alive) setGuestAnn(items.length ? items[0] : null);
    }).catch(() => {});
    return () => { alive = false; };
  }, [auth.isLoggedIn]);

  const rawUnread = (sum?.total_unread || 0) + (sum?.pending || 0);
  const unread = auth.isLoggedIn ? Math.min(MAX, rawUnread) : 0;
  const recent = (sum?.recent) || [];

  return (
    <div className="bell-wrap"
         onMouseEnter={() => { keepOpen(); setShow(true); loadSum(); }}
         onMouseLeave={scheduleClose}>
      <button className={`bell-btn${unread > 0 ? " has-unread" : ""}`}
              title={t("notify.title")} onClick={onOpen}>
        <span className="bell-icon"><BellSvg /></span>
        {unread > 0 && <span className="bell-dot">{unread >= MAX ? "99+" : unread}</span>}
      </button>

      {show && (
        <div className="bell-menu" onMouseEnter={keepOpen} onMouseLeave={scheduleClose}>
          {!auth.isLoggedIn ? (
            <>
              {/* 游客也能看最新系统公告（公开接口） */}
              <div className="bell-head">{t("notify.latestAnnounce")}</div>
              {guestAnn ? (
                <div className="bell-ann">
                  <div className="bell-ann-title">
                    <span className="bell-ann-tag"><AnnSvg size={14} /></span>{guestAnn.title}
                  </div>
                  <div className="bell-ann-content">{guestAnn.content || ""}</div>
                </div>
              ) : (
                <div className="bell-empty">{t("notify.noAnnounce")}</div>
              )}
              <div className="bell-login">
                <div className="bell-login-text">{t("notify.loginHint")}</div>
                <button className="btn primary small" onClick={onOpen}>{t("notify.goLogin")}</button>
              </div>
            </>
          ) : (
            <>
              {/* 顶部：最新系统公告 */}
              <div className="bell-head">{t("notify.latestAnnounce")}</div>
              {sum?.latest_announce ? (
                <div className="bell-ann" onClick={() => onOpen(0)}>
                  <div className="bell-ann-title">
                    <span className="bell-ann-tag"><AnnSvg size={14} /></span>{sum.latest_announce.title}
                    {sum.notices_unread && <span className="bell-ann-new">NEW</span>}
                  </div>
                  <div className="bell-ann-content">{sum.latest_announce.content || ""}</div>
                </div>
              ) : (
                <div className="bell-empty">{t("notify.noAnnounce")}</div>
              )}

              {/* 中间：用户消息（最近会话 + 好友申请） */}
              <div className="bell-head">{t("notify.userMsgs")}</div>
              <div className="bell-list">
                {sum?.pending > 0 && (
                  <div className="bell-item bell-req" onClick={() => onOpen(undefined, "requests")}>
                    <span className="bell-item-avatar">🤝</span>
                    <span className="bell-item-name">{t("notify.friendRequests")}</span>
                    <span className="bell-item-unread">{sum.pending}</span>
                  </div>
                )}
                {recent.length === 0 && sum?.pending === 0 && (
                  <div className="bell-empty">{t("notify.empty")}</div>
                )}
                {recent.map((it, i) => (
                  <div className={`bell-item${it.unread ? " unread" : ""}`}
                       key={`${it.peer_id}-${i}`} onClick={() => onOpen(it.peer_id)}>
                    <span className="bell-item-avatar">{it.peer_id === 0 ? <AnnSvg size={15} /> : (it.name || "?").slice(0, 1).toUpperCase()}</span>
                    <span className="bell-item-main">
                      <span className="bell-item-name">{it.name}</span>
                      <span className="bell-item-summary">{it.summary || ""}</span>
                    </span>
                    {it.unread > 0 && <span className="bell-item-unread">{it.unread >= MAX ? "99+" : it.unread}</span>}
                  </div>
                ))}
              </div>

              {/* 底部：进入通知中心 */}
              <button className="bell-foot" onClick={() => onOpen()}>{t("notify.enter")}</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}