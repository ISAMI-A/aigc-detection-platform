import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchParams } from "../../api/detectApi.js";
import Dropdown from "../common/Dropdown.jsx";

// 检测参数设置弹窗（仅对本功能生效）：
// - 预设档位（默认/均衡/严格/宽松）
// - 高级设置（折叠展开，逐参数微调，悬停 ? 显示用途说明）
export default function SettingsModal({ params, onChange, onClose }) {
  const { t } = useTranslation();
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [meta, setMeta] = useState({ presets: {}, desc: {} });

  useEffect(() => {
    fetchParams().then((d) => setMeta(d)).catch(() => {});
  }, []);

  const presets = meta.presets || {};
  const desc = meta.desc || {};
  // 高级参数顺序（与 run.py 配置区一致）
  const advancedKeys = [
    "threshold", "threshold_high", "threshold_med", "fuse_peak", "fuse_area",
    "conf_threshold", "comp_ratio", "comp_n_spots",
    "geom_rect", "geom_solid", "geom_min_area", "geom_loc_thr", "geom_line_ratio",
    "suspect_loc_thr", "suspect_up_thr", "edge_band", "edge_touch_ratio", "edge_band_ratio",
  ];

  function setParam(key, value) {
    onChange({ ...params, [key]: value });
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t('detect.settingsTitle')}</span>
          <button className="btn small" onClick={onClose}>✕</button>
        </div>

        {/* 预设档位 */}
        <div className="settings-section">
          <div className="settings-label">{t('detect.presetLabel')}</div>
          <Dropdown value={params.preset || ""}
                    options={[{ label: t('detect.presetDefault'), value: "" },
                              ...Object.entries(presets).map(([k, v]) => ({ label: `${k}：${v.desc}`, value: k }))]}
                    onChange={(v) => setParam("preset", v)} />
        </div>

        {/* 高级设置 */}
        <div className="settings-section">
          <div className="advanced-toggle" onClick={() => setShowAdvanced(!showAdvanced)}>
            <span className={`arrow ${showAdvanced ? "open" : ""}`}>▸</span> {t('detect.advancedSettings')}
          </div>
          {showAdvanced && (
            <div className="advanced-body">
              {advancedKeys.map((k) => (
                <div className="param-row" key={k}>
                  <label title={desc[k] || ""}>{k}<span className="q" title={desc[k] || ""}>?</span></label>
                  <input className="input" type="number" step="any"
                         value={params[k] ?? ""}
                         onChange={(e) => setParam(k, e.target.value === "" ? "" : Number(e.target.value))} />
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="settings-foot">
          {t('detect.settingsHint')}
        </div>
      </div>
    </div>
  );
}
