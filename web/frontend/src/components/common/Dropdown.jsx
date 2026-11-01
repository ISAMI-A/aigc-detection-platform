import { useEffect, useRef, useState } from "react";

// 自定义下拉框：展开面板完全可控（圆角/阴影/悬停高亮/外部点击关闭）
// options 支持字符串数组 或 [{label, value}]；value=当前值；onChange=选中回调
export default function Dropdown({ value, options, onChange, className = "", style }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // 点击面板外部时关闭
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const list = options.map((o) => (typeof o === "string" ? { label: o, value: o } : o));
  const cur = list.find((o) => o.value === value) || list[0];

  return (
    <div className={`dd ${open ? "open" : ""} ${className}`} style={style} ref={ref}>
      <div className="dd-head" onClick={() => setOpen((v) => !v)}>
        <span className="dd-value">{cur ? cur.label : ""}</span>
        <span className="dd-arrow">▾</span>
      </div>
      {open && (
        <div className="dd-menu">
          {list.map((o) => (
            <div key={o.value} className={`dd-item ${o.value === value ? "active" : ""}`}
                 onClick={() => { onChange(o.value); setOpen(false); }}>
              {o.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
