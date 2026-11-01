// 密码输入框（含显示/隐藏切换，默认隐藏；切换按钮为眼睛图标）
import { useState } from "react";
import { useTranslation } from "react-i18next";

function EyeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}

export default function PasswordInput({ value, onChange, placeholder, className, autoComplete, disabled, onKeyDown }) {
  const { t } = useTranslation();
  const [show, setShow] = useState(false);
  return (
    <div className="pwd-wrap">
      <input
        type={show ? "text" : "password"}
        className={`${className || "auth-input"} pwd-input`}
        value={value}
        placeholder={placeholder}
        autoComplete={autoComplete}
        disabled={disabled}
        onKeyDown={onKeyDown}
        onChange={(e) => onChange(e.target.value)}
      />
      <button type="button" className="pwd-toggle" disabled={disabled}
              onClick={() => setShow(!show)}
              title={show ? t("auth.hidePwd") : t("auth.showPwd")}>
        {show ? <EyeOffIcon /> : <EyeIcon />}
      </button>
    </div>
  );
}
