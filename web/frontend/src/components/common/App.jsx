import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Home from "./Home.jsx";
import Detect from "../detect/Detect.jsx";
import SystemSettings from "./SystemSettings.jsx";
import SmartVerify from "../verify/SmartVerify.jsx";
import RsVerify from "../rsverify/RsVerify.jsx";
import FaceRec from "../face/FaceRec.jsx";
import Profile from "../profile/Profile.jsx";
import AdminPage from "../admin/AdminPage.jsx";
import AuthModal from "./AuthModal.jsx";
import BellMenu from "./BellMenu.jsx";
import NotificationCenter from "./NotificationCenter.jsx";
import { useAuth } from "../../auth/AuthContext.jsx";
import { request, setToken } from "../../api/index.js";

// 用户菜单单色线条图标（颜文字风格，currentColor 跟随主题文字色）
function MenuIcon({ d, extra, size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {d.map((p, i) => <path key={i} d={p} />)}
      {extra}
    </svg>
  );
}
const ICON_USER = { d: ["M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"], extra: <circle cx="12" cy="7" r="4" /> };
// 单色喇叭（顶栏公告横幅用；lucide megaphone 线性，与全局线条图标风格一致）
function AnnounceIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m3 11 18-5v12L3 14v-3z" />
      <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
    </svg>
  );
}
const ICON_SATELLITE = {
  d: ["M13 7 9 3 5 7l4 4", "m17 11 4 4-4 4-4-4", "m8 12 4 4 6-6-4-4Z", "m16 8 3-3", "M9 21a6 6 0 0 0-6-6"],
};
const ICON_SETTINGS = { d: [
  "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z",
], extra: <circle cx="12" cy="12" r="3" /> };
const ICON_POWER = { d: ["M12 2v10", "M18.4 6.6a9 9 0 1 1-12.77.04"] };

// 功能页元信息（标签页 / 首页列表共用；feature=功能开关名，关闭时非 admin 隐藏）
const TAB_META = {
  home:   { title: "首页", comp: Home },
  detect: { title: "图像篡改检测", comp: Detect, feature: "detect" },
  verify: { title: "点位真实性核验", comp: SmartVerify, feature: "verify" },
  rsverify: { title: "遥感变化核验", comp: RsVerify, feature: "rsverify" },
  facerec: { title: "人脸识别", comp: FaceRec, feature: "face" },
  profile: { title: "个人资料", comp: Profile, needLogin: true },
  notify: { title: "通知中心", comp: NotificationCenter, needLogin: true },
  admin:   { title: "管理中心", comp: AdminPage, needAdmin: true },
};

// 标签页状态持久化：刷新后停留在当前标签页而不是跳回首页
const TAB_KEY = "ai-tabs-state";
const BANNER_KEY = "banner_login_dismissed";
function loadTabState() {
  try {
    const raw = JSON.parse(localStorage.getItem(TAB_KEY) || "");
    if (raw && Array.isArray(raw.tabs)) {
      // 只过滤掉已不存在的功能页并保证 home 在首位；权限（登录/管理员）标签完整保留，
      // 由渲染层按当前权限过滤（避免刷新时登录态未就绪导致标签被删后无法恢复）
      const tabs = raw.tabs
        .filter((t) => t && TAB_META[t.id])
        .map((t) => ({ id: t.id, title: TAB_META[t.id].title }));
      if (!tabs.some((t) => t.id === "home")) tabs.unshift({ id: "home", title: "首页" });
      const activeId = raw.activeId && tabs.some((t) => t.id === raw.activeId)
        ? raw.activeId : tabs[0].id;
      return { tabs, activeId };
    }
  } catch (_) {}
  return { tabs: [{ id: "home", title: "首页" }], activeId: "home" };
}

export default function App() {
  const { t } = useTranslation();
  const auth = useAuth();
  const isLoggedIn = auth.isLoggedIn;
  const isAdmin = auth.isAdmin;
  const [tabs, setTabs] = useState(() => loadTabState().tabs);
  const [activeId, setActiveId] = useState(() => loadTabState().activeId);
  const [dragIdx, setDragIdx] = useState(null);   // 拖拽中的标签索引
  const [hoverIdx, setHoverIdx] = useState(null); // 拖拽悬停的目标标签索引
  const [dropSide, setDropSide] = useState(null); // 落位方向：before=目标前 / after=目标后
  const [userMenu, setUserMenu] = useState(false);
  const [showSysSettings, setShowSysSettings] = useState(false);
  const [epoch, setEpoch] = useState(0);          // 登录态变化后刷新当前页数据
  const [bannerOff, setBannerOff] = useState(() => {
    try { return localStorage.getItem(BANNER_KEY) === "1"; } catch (_) { return false; }
  });
  const [announce, setAnnounce] = useState(null); // 系统公告（登录用户展示最新一条）
  const [hasAnnounce, setHasAnnounce] = useState(false); // 是否存在启用公告（游客提示登录后查看）
  // 公告关闭仅本次会话生效（不持久化）：关闭一次后再返回（刷新/重新打开）公告会重新出现
  const [annOff, setAnnOff] = useState(false);
  const [features, setFeatures] = useState({});   // 功能开关状态（公开接口拉取，控制入口隐藏）
  const [toast, setToast] = useState(null);       // 全局轻提示（登出回游客等场景）

  // 全局轻提示（3s 自动消失，遵守"不用浏览器 alert"约定）
  function showToast(text, kind = "warn") {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 3000);
  }

  // 功能开关状态（admin 不受限制，但全局拉取用于入口过滤）
  useEffect(() => {
    let alive = true;
    request("/api/features").then((d) => {
      if (alive && d && typeof d === "object") setFeatures(d);
    }).catch(() => {});
    return () => { alive = false; };
  }, []);

  // 公告：登录用户展示最新启用公告（顶栏横幅，可关闭）；游客仅感知"是否有公告"（提示登录后查看）
  const [announceVer, setAnnounceVer] = useState(0); // 公告变更计数（admin 保存/删除后热更新）
  useEffect(() => {
    let alive = true;
    request("/api/announcements").then((d) => {
      const items = (d && d.items) || [];
      if (!alive) return;
      if (isLoggedIn) {
        setAnnounce(!annOff && items.length ? items[0] : null);
        setHasAnnounce(false);
      } else {
        setHasAnnounce(items.length > 0);
        setAnnounce(null);
      }
    }).catch(() => {});
    return () => { alive = false; };
  }, [isLoggedIn, annOff, announceVer]);

  // admin 在系统管理页保存/删除公告后派发 announce-changed → 热更新横幅
  useEffect(() => {
    const onAnnounceChanged = () => { setAnnOff(false); setAnnounceVer((v) => v + 1); };
    window.addEventListener("announce-changed", onAnnounceChanged);
    return () => window.removeEventListener("announce-changed", onAnnounceChanged);
  }, []);

  function dismissAnnounce() {
    setAnnOff(true);
    setAnnounce(null);
  }

  // 标签页变化时写入 localStorage
  useEffect(() => {
    localStorage.setItem(TAB_KEY, JSON.stringify({ tabs, activeId }));
  }, [tabs, activeId]);

  // 登录态变化（登录/登出/改密）：刷新当前页数据（key 变化重挂载）
  useEffect(() => {
    const onAuth = () => setEpoch((e) => e + 1);
    window.addEventListener("auth-changed", onAuth);
    return () => window.removeEventListener("auth-changed", onAuth);
  }, []);

  // 游客点击需登录功能（如个人资料）→ 弹登录框
  useEffect(() => {
    const onRequire = () => auth.openLogin();
    window.addEventListener("require-login", onRequire);
    return () => window.removeEventListener("require-login", onRequire);
  }, [auth]);

  // token 失效（401）→ 清理登录态回退游客
  useEffect(() => {
    const onExpired = async () => {
      setToken("");
      await auth.refresh();
      window.dispatchEvent(new CustomEvent("auth-changed"));
    };
    window.addEventListener("auth-expired", onExpired);
    return () => window.removeEventListener("auth-expired", onExpired);
  }, [auth]);

  // 未登录/非 admin 的标签由渲染层过滤（不删除标签，登录态恢复后自动重新显示）
  const visibleTabs = tabs.filter((t) =>
    (!TAB_META[t.id].needLogin || isLoggedIn) &&
    (!TAB_META[t.id].needAdmin || isAdmin) &&
    (!TAB_META[t.id].feature || features[TAB_META[t.id].feature] !== false || isAdmin));
  const effectiveActiveId = visibleTabs.some((t) => t.id === activeId) ? activeId : "home";

  // 打开标签：已存在则激活，否则新建；需登录/需管理员/功能关闭未满足时引导
  function openTab(id) {
    const meta = TAB_META[id];
    if (!meta) return;
    if (meta.needLogin && !isLoggedIn) { auth.openLogin(); return; }
    if (meta.needAdmin && !isAdmin) { auth.openLogin(); return; }
    if (meta.feature && features[meta.feature] === false && !isAdmin) return; // 功能关闭（admin 不受限）
    setTabs((prev) => (prev.some((t) => t.id === id) ? prev : [...prev, { id, title: meta.title }]));
    setActiveId(id);
  }
  // 关闭标签：激活相邻标签；首页不可关闭
  function closeTab(id) {
    if (id === "home") return;
    setTabs((prev) => {
      const idx = prev.findIndex((t) => t.id === id);
      const next = prev.filter((t) => t.id !== id);
      if (activeId === id) {
        const neighbor = next[Math.max(0, Math.min(idx, next.length - 1))];
        setActiveId(neighbor ? neighbor.id : "home");
      }
      return next;
    });
  }
  // 拖拽调整标签顺序：side=before 放到目标前 / after 放到目标后
  function moveTab(from, to, side) {
    setTabs((prev) => {
      const next = [...prev];
      const [m] = next.splice(from, 1);
      let pos = to + (side === "after" ? 1 : 0);
      if (from < pos) pos -= 1; // 移除项位于目标前时，目标索引左移一位
      pos = Math.max(0, Math.min(pos, next.length));
      next.splice(pos, 0, m);
      return next;
    });
  }

  function dismissBanner() {
    setBannerOff(true);
    try { localStorage.setItem(BANNER_KEY, "1"); } catch (_) {}
  }

  function openProfile() {
    setUserMenu(false);
    if (isLoggedIn) openTab("profile");
    else auth.openLogin();
  }

  // 打开通知中心；peer=0 进公告、>0 进对应会话，mode 如 requests 进好友申请
  function openNotify(peer, mode) {
    if (!isLoggedIn) { auth.openLogin(); return; }
    openTab("notify");
    window.dispatchEvent(new CustomEvent("notify-open",
      { detail: { peer: peer === undefined ? null : peer, mode: mode || "" } }));
  }

  const ActiveComp = TAB_META[effectiveActiveId]?.comp || Home;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">AI 检测平台</div>
        {/* 标签页导航：可点击切换、可关闭、可拖拽排序 */}
        <nav className="tabbar">
          {visibleTabs.map((t, i) => (
            <div key={t.id}
                 className={`tab-item ${t.id === effectiveActiveId ? "active" : ""} ${
                   dragIdx !== null && hoverIdx === i && dragIdx !== i
                     ? `drop-line-${dropSide || "before"}` : ""
                 }`}
                 draggable
                 onDragStart={() => setDragIdx(i)}
                 onDragOver={(e) => {
                   e.preventDefault();
                   // 按鼠标在标签上的左右半区决定落位方向（前/后）
                   const rect = e.currentTarget.getBoundingClientRect();
                   setDropSide(e.clientX - rect.left <= rect.width / 2 ? "before" : "after");
                   setHoverIdx(i);
                 }}
                 onDragLeave={() => setHoverIdx((h) => (h === i ? null : h))}
                 onDragEnd={() => { setDragIdx(null); setHoverIdx(null); setDropSide(null); }}
                 onDrop={(e) => {
                   e.preventDefault();
                   if (dragIdx !== null) moveTab(dragIdx, i, dropSide || "before");
                   setDragIdx(null); setHoverIdx(null); setDropSide(null);
                 }}
                 onClick={() => setActiveId(t.id)}>
              <span className="tab-title">{t.title}</span>
              {t.id !== "home" && (
                <span className="tab-close" title="关闭标签"
                      onClick={(e) => { e.stopPropagation(); closeTab(t.id); }}>×</span>
              )}
            </div>
          ))}
        </nav>
        {/* 用户区：登录后小铃铛(通知中心) + 账号信息；游客显示"客 未登录"下拉 */}
        <div className="user-area">
          <BellMenu onOpen={openNotify} />
          <button className="user-btn" onClick={() => setUserMenu(!userMenu)}>
            <span className="avatar">{isLoggedIn ? (auth.user?.username || "?").slice(0, 1).toUpperCase() : "客"}</span>
            <span className="username">
              {isLoggedIn ? auth.user?.username : t("profile.guest")}
              {isLoggedIn && auth.isAdmin && <span className="admin-tag">ADMIN</span>}
            </span>
            <span className={`arrow ${userMenu ? "open" : ""}`}>▾</span>
          </button>
          {userMenu && (
            <div className="user-menu">
              <div className="menu-item" onClick={openProfile}><MenuIcon {...ICON_USER} />{t("profile.title")}</div>
              {isAdmin && (
                <div className="menu-item" onClick={() => { setUserMenu(false); openTab("admin"); }}><MenuIcon {...ICON_SATELLITE} />{t("admin.title")}</div>
              )}
              <div className="menu-item" onClick={() => { setUserMenu(false); setShowSysSettings(true); }}><MenuIcon {...ICON_SETTINGS} />系统设置</div>
              {isLoggedIn && (
                <>
                  <div className="menu-sep" />
                  <div className="menu-item danger"
                       onClick={() => { setUserMenu(false); auth.logout(); showToast(t("auth.loggedOut")); }}>
                    <MenuIcon {...ICON_POWER} />{t("profile.logout")}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </header>

      {/* 游客引导横幅（可关闭，刷新不重现） */}
      {!isLoggedIn && !bannerOff && (
        <div className="guest-banner">
          <span>{t("auth.bannerLogin")}</span>
          <button className="guest-banner-login" onClick={auth.openLogin}>{t("auth.login")}</button>
          <span className="guest-banner-close" onClick={dismissBanner} title={t("common.close")}>×</span>
        </div>
      )}

      {/* 系统公告横幅（登录用户展示最新启用公告，可关闭） */}
      {announce && (
        <div className="announce-banner" title={announce.content}>
          <span className="announce-bell"><AnnounceIcon size={13} /></span>
          <span className="announce-text">{announce.title}</span>
          <span className="guest-banner-close" onClick={dismissAnnounce} title={t("common.close")}>×</span>
        </div>
      )}

      {/* 游客：存在公告时提示登录后查看 */}
      {!isLoggedIn && hasAnnounce && (
        <div className="announce-banner guest" onClick={auth.openLogin} title={t("auth.announceGuest")}>
          <span className="announce-bell"><AnnounceIcon size={13} /></span>
          <span className="announce-text">{t("auth.announceGuest")}</span>
        </div>
      )}

      {/* 全局轻提示（登出回游客等） */}
      {toast && <div className={`toast toast-${toast.kind} global-toast`}>{toast.text}</div>}

      {/* 页面切换动画：key 变化触发淡入（含登录态刷新 epoch） */}
      <main className="content">
        <ActiveComp key={`${effectiveActiveId}-${epoch}`} onTry={openTab} features={features} isAdmin={isAdmin} />
      </main>

      {showSysSettings && <SystemSettings onClose={() => setShowSysSettings(false)} />}
      {auth.loginModal && <AuthModal />}
    </div>
  );
}
