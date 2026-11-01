import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { smartApi } from "../../api/smartApi.js";
import { imgUrl } from "../../api/index.js";

// 双图对比详情弹窗：
// - 原图 + Canvas 标注（区域框/特征点，基于 RANSAC 内点）
// - 指标面板（判定/置信度/匹配数/内点/方法）
// - 人工修正（下拉选择/备注失焦即自动静默保存，覆盖机器结果；列表同步黄色"人工"标签）
export default function ImageCompare({ pair, onClose, onJudgmentSaved }) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const [fixSame, setFixSame] = useState(null);
  const [fixNote, setFixNote] = useState("");
  const [dropOpen, setDropOpen] = useState(false);
  const [dropRect, setDropRect] = useState(null); // 菜单 fixed 定位坐标（不撑开弹窗高度）
  const ts = useRef(Date.now());
  const img1Ref = useRef(null);
  const img2Ref = useRef(null);
  const canvas1Ref = useRef(null);
  const canvas2Ref = useRef(null);
  const dropRef = useRef(null);
  const dropBtnRef = useRef(null);

  useEffect(() => {
    let alive = true;
    smartApi.detail(pair.result_id)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
        setFixSame(d.manual_override ? d.manual_is_same : null);
        setFixNote(d.manual_note || "");
      })
      .catch((e) => { if (alive) onJudgmentSaved && onJudgmentSaved(t('imageCompare.loadFail', { msg: e.message })); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pair.result_id]);

  // 图片加载完成后绘制标注覆盖层（区域框 + 特征点）
  function drawOverlay(idx) {
    const canvas = idx === 1 ? canvas1Ref.current : canvas2Ref.current;
    const img = idx === 1 ? img1Ref.current : img2Ref.current;
    const ann = detail && detail.annotations;
    if (!canvas || !img || !ann || !img.naturalWidth) return;
    canvas.width = img.clientWidth || img.naturalWidth;
    canvas.height = img.clientHeight || img.naturalHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const scaleX = canvas.width / img.naturalWidth;
    const scaleY = canvas.height / img.naturalHeight;

    const regions = idx === 1 ? ann.img1_regions : ann.img2_regions;
    const keypoints = idx === 1 ? ann.img1_keypoints : ann.img2_keypoints;
    if (!regions?.length && !keypoints?.length) return;

    // 区域框（绿色半透明 + 边框 + 点数）
    regions.forEach((r) => {
      const x = r.x * scaleX, y = r.y * scaleY, w = r.w * scaleX, h = r.h * scaleY;
      ctx.fillStyle = "rgba(0, 255, 136, 0.15)";
      ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = "#00ff88";
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = "#00ff88";
      ctx.font = "bold 12px sans-serif";
      ctx.fillText(t('imageCompare.points', { n: r.point_count }), x + 4, y + 14);
    });
    // 特征点（红色圆点）
    if (keypoints?.length) {
      ctx.fillStyle = "#ff4444";
      keypoints.forEach(([x, y]) => {
        ctx.beginPath();
        ctx.arc(x * scaleX, y * scaleY, 2.5, 0, Math.PI * 2);
        ctx.fill();
      });
    }
  }

  // 点击下拉外部关闭菜单；滚动时关闭（fixed 菜单不跟随滚动）
  useEffect(() => {
    if (!dropOpen) return;
    function onDocClick(e) {
      if (dropRef.current && !dropRef.current.contains(e.target)) setDropOpen(false);
    }
    function onScroll() { setDropOpen(false); }
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [dropOpen]);

  // 展开/收起下拉：展开时按按钮位置计算 fixed 菜单坐标
  function toggleDrop() {
    if (dropOpen) { setDropOpen(false); return; }
    const btn = dropBtnRef.current;
    if (btn) {
      const r = btn.getBoundingClientRect();
      setDropRect({ top: r.bottom + 4, left: r.left, width: r.width });
    }
    setDropOpen(true);
  }

  // 自动保存人工修正（静默：成功不弹提示，仅刷新详情与列表）
  async function autoSaveFix(nextSame = fixSame, nextNote = fixNote) {
    if (!detail || !detail.result_id) return;
    try {
      // fixSame 为 null 时表示"取消人工修正"（后端恢复机器结果）
      await smartApi.manualFix(detail.result_id, nextSame, nextNote);
      const d = await smartApi.detail(pair.result_id);
      setDetail(d);
      setFixSame(d.manual_override ? d.manual_is_same : null);
      setFixNote(d.manual_note || "");
      onJudgmentSaved && onJudgmentSaved();
    } catch (e) {
      onJudgmentSaved && onJudgmentSaved(t('imageCompare.saveFail', { msg: e.message }));
    }
  }

  // 下拉选择：更新并立即保存
  function handleSelect(val) {
    setDropOpen(false);
    const v = val === "" ? null : val === "true";
    if (v === fixSame) return;
    setFixSame(v);
    autoSaveFix(v, fixNote);
  }

  if (!detail) return null;

  const isSameText = detail.manual_override
    ? (detail.manual_is_same ? t('resultTable.yesFixed') : t('resultTable.noFixed'))
    : (detail.is_same ? t('resultTable.yes') : t('resultTable.no'));
  const isSameTag = detail.manual_override
    ? (detail.manual_is_same ? "tag-success" : "tag-danger")
    : (detail.is_same ? "tag-success" : "tag-danger");
  const fmt = (v, d = 4) => (v !== null && v !== undefined ? Number(v).toFixed(d) : "-");

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal smart-compare-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{t('imageCompare.title')}</span>
          <button className="btn small" onClick={onClose}>✕</button>
        </div>

        {loading ? (
          <div className="loading-wrapper">{t('imageCompare.loading')}</div>
        ) : (
          <div className="compare-wrapper">
            <div className="image-box">
              <div className="img-title">{t('imageCompare.rectifyImage', { name: detail.left_filename })}</div>
              <div className="img-wrap">
                <img ref={img1Ref} src={`${imgUrl(detail.left_image_url)}&t=${ts.current}`} alt="整改图"
                     crossOrigin="anonymous" onLoad={() => drawOverlay(1)} />
                <canvas ref={canvas1Ref} className="overlay" />
              </div>
            </div>

            <div className="metrics-panel">
              <div className="metric-card">
                <div className="metric-item">
                  <span className="label">{t('imageCompare.judgment')}</span>
                  <span className={`smart-tag ${isSameTag}`}>{isSameText}</span>
                </div>
                <div className="metric-item"><span className="label">{t('imageCompare.confidence')}</span><strong>{fmt(detail.confidence)}</strong></div>
                <div className="metric-item"><span className="label">{t('imageCompare.totalMatches')}</span><strong>{detail.total_matches ?? "-"}</strong></div>
                <div className="metric-item"><span className="label">{t('imageCompare.ransacInliers')}</span><strong>{detail.ransac_inliers ?? "-"}</strong></div>
                <div className="metric-item"><span className="label">{t('imageCompare.inlierRatio')}</span><strong>{fmt(detail.inlier_ratio)}</strong></div>
                <div className="metric-item"><span className="label">{t('imageCompare.method')}</span><strong>{detail.method ?? "-"}</strong></div>
                {detail.manual_note && <div className="metric-item"><span className="label">{t('imageCompare.note')}</span><span>{detail.manual_note}</span></div>}
              </div>

              {/* 人工修正（下拉选择即自动保存，覆盖机器结果，列表显示黄色"人工"标签） */}
              <div className="metric-card">
                <div className="card-sub-title">{t('imageCompare.fixTitle')}</div>
                <div className="metric-item">
                  <div className="smart-dropdown" ref={dropRef}>
                    <button type="button" className="smart-dropdown-btn" ref={dropBtnRef}
                            onClick={toggleDrop}>
                      <span>{fixSame === null ? t('imageCompare.noFix') : fixSame ? t('imageCompare.fixYes') : t('imageCompare.fixNo')}</span>
                      <span className={`caret${dropOpen ? " up" : ""}`}>▾</span>
                    </button>
                    {dropOpen && (
                      <div className="smart-dropdown-menu" style={dropRect}>
                        <div className={`smart-dropdown-item${fixSame === null ? " active" : ""}`}
                             onClick={() => handleSelect("")}>{t('imageCompare.noFix')}</div>
                        <div className={`smart-dropdown-item${fixSame === true ? " active" : ""}`}
                             onClick={() => handleSelect("true")}>{t('imageCompare.fixYes')}</div>
                        <div className={`smart-dropdown-item${fixSame === false ? " active" : ""}`}
                             onClick={() => handleSelect("false")}>{t('imageCompare.fixNo')}</div>
                      </div>
                    )}
                  </div>
                </div>
                <div className="metric-item">
                  <input className="input smart-note" placeholder={t('imageCompare.notePlaceholder')} value={fixNote}
                         onChange={(e) => setFixNote(e.target.value)}
                         onBlur={() => autoSaveFix()} />
                </div>
              </div>
            </div>

            <div className="image-box">
              <div className="img-title">{t('imageCompare.inspectImage', { name: detail.right_filename })}</div>
              <div className="img-wrap">
                <img ref={img2Ref} src={`${imgUrl(detail.right_image_url)}&t=${ts.current}`} alt="暗访图"
                     crossOrigin="anonymous" onLoad={() => drawOverlay(2)} />
                <canvas ref={canvas2Ref} className="overlay" />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
