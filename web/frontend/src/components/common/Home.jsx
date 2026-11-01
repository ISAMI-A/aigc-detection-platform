import { useState } from "react";
import { useTranslation } from "react-i18next";

// 功能清单（首页左侧列表 + 右侧解释共用）
// feature: 后端功能开关名；id 必须与 App.jsx TAB_META 键名一致（否则 openTab 找不到页）
const FEATURES = [
  {
    id: "detect", icon: "🖼", i18nKey: "home.detectTitle", feature: "detect",
    descKey: "home.detectDesc", detailKey: "home.detectDetail",
  },
  {
    id: "verify", icon: "📍", i18nKey: "home.verifyTitle", feature: "verify",
    descKey: "home.verifyDesc", detailKey: "home.verifyDetail",
  },
  {
    id: "facerec", icon: "👤", i18nKey: "home.faceTitle", feature: "face",
    descKey: "home.faceDesc", detailKey: "home.faceDetail",
  },
  {
    id: "rsverify", icon: "🛰", i18nKey: "home.rsTitle", feature: "rsverify",
    descKey: "home.rsDesc", detailKey: "home.rsDetail",
  },
];

export default function Home({ onTry, features = {}, isAdmin = false }) {
  const { t } = useTranslation();
  const [sel, setSel] = useState("detect");

  // 某项功能当前用户是否可见（普通用户受开关限，关闭隐藏；admin 恒可见）
  const canView = (f) => (features[f.feature] !== false || isAdmin);
  // 是否可进入（开关开启可进；admin 不受限）
  const canUse = (f) => (isAdmin || features[f.feature] !== false);

  const visible = FEATURES.filter(canView);
  const cur = visible.find((f) => f.id === sel) || visible[0];

  return (
    <div className="home-layout">
      {/* 左侧功能列表（可滚动） */}
      <div className="home-list">
        {visible.map((f) => (
          <div key={f.id}
               className={`home-item ${f.id === sel ? "active" : ""} ${canUse(f) ? "" : "disabled"}`}
               onClick={() => setSel(f.id)}>
            <span className="home-item-icon">{f.icon}</span>
            <div className="home-item-body">
              <div className="home-item-name">{t(f.i18nKey)}</div>
              <div className="home-item-desc">{t(f.descKey)}</div>
            </div>
            {!canUse(f) && <span className="home-item-tag">{t('common.comingSoon')}</span>}
          </div>
        ))}
        {visible.length === 0 && <div className="home-empty">{t('common.noFeature')}</div>}
      </div>

      {/* 右侧功能解释 */}
      {cur && (
        <div className="home-detail">
          <div className="home-detail-icon">{cur.icon}</div>
          <h2 className="home-detail-title">{t(cur.i18nKey)}</h2>
          <p className="home-detail-desc">{t(cur.detailKey)}</p>
          <button className="btn primary try-btn" disabled={!canUse(cur)}
                  onClick={() => onTry(cur.id)}>{t('common.tryNow')}</button>
          {!canUse(cur) && <div className="home-detail-tip">{t('common.notOnline')}</div>}
        </div>
      )}
    </div>
  );
}