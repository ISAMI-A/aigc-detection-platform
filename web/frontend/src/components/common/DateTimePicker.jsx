// 自定义日期时间选择器（替代原生 datetime-local，弹层圆角/阴影/主题统一）
// 受控组件：value="YYYY-MM-DDTHH:mm"（可空），onChange(v)
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

function pad(n) { return String(n).padStart(2, "0"); }

export default function DateTimePicker({ value, onChange, title }) {
  const { t } = useTranslation();
  const ref = useRef(null);
  const [open, setOpen] = useState(false);
  const now = new Date();
  const [year, setYear] = useState(value ? +value.slice(0, 4) : now.getFullYear());
  const [month, setMonth] = useState(value ? +value.slice(5, 7) - 1 : now.getMonth());
  const [day, setDay] = useState(value ? +value.slice(8, 10) : now.getDate());
  const [hour, setHour] = useState(value ? +value.slice(11, 13) : now.getHours());
  const [minute, setMinute] = useState(value ? +value.slice(14, 16) : 0);

  // 点击外部关闭
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  function emit(y, m, d, hh, mm) {
    onChange(`${y}-${pad(m + 1)}-${pad(d)}T${pad(hh)}:${pad(mm)}`);
  }
  function goMonth(delta) {
    let m = month + delta, y = year;
    if (m < 0) { m = 11; y -= 1; }
    if (m > 11) { m = 0; y += 1; }
    setMonth(m); setYear(y);
  }
  function pick(d) { setDay(d); emit(year, month, d, hour, minute); }
  function onHour(v) { setHour(v); emit(year, month, day, v, minute); }
  function onMinute(v) { setMinute(v); emit(year, month, day, hour, v); }

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstWeekday = new Date(year, month, 1).getDay();
  const cells = [];
  for (let i = 0; i < firstWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const isSel = (d) => value && +value.slice(8, 10) === d && +value.slice(5, 7) - 1 === month && +value.slice(0, 4) === year;

  return (
    <div className="dtp-wrap" ref={ref}>
      <input className="dtp-input" readOnly value={value || ""} placeholder={title}
             onFocus={() => setOpen(true)} />
      {value && <span className="dtp-clear" title={t("common.clear")} onClick={() => onChange("")}>×</span>}
      {open && (
        <div className="dtp-pop">
          <div className="dtp-head">
            <button type="button" onClick={() => goMonth(-1)} aria-label="prev">‹</button>
            <span className="dtp-title">{t("admin.dtpTitle", { y: year, m: month + 1 })}</span>
            <button type="button" onClick={() => goMonth(1)} aria-label="next">›</button>
          </div>
          <div className="dtp-grid">
            {t("admin.dtpWeek", { returnObjects: true }).map((w) => (
              <div key={w} className="dtp-week">{w}</div>
            ))}
            {cells.map((d, i) => (
              d === null
                ? <div key={`e${i}`} className="dtp-cell empty" />
                : <div key={d} className={`dtp-cell${isSel(d) ? " sel" : ""}`} onClick={() => pick(d)}>{d}</div>
            ))}
          </div>
          <div className="dtp-time">
            <select value={hour} onChange={(e) => onHour(+e.target.value)}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{pad(h)}</option>)}
            </select>
            <span>:</span>
            <select value={minute} onChange={(e) => onMinute(+e.target.value)}>
              {Array.from({ length: 60 }, (_, m) => <option key={m} value={m}>{pad(m)}</option>)}
            </select>
            <button type="button" className="btn dtp-ok" onClick={() => setOpen(false)}>{t("common.ok")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
