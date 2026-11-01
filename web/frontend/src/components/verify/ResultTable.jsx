import { useState } from "react";
import { useTranslation } from "react-i18next";
import { imgUrl } from "../../api/index.js";

// 核验结果表格：
// - 缩略图列（整改图/暗访图）
// - 判定列：人工复核判断优先显示"是(人工)/否(人工)"黄色标签
// - 双击行 = 切换勾选（再次双击取消；双击勾选范围不含勾选列与操作列）；勾选列复选框可直接点击
// onVerify(pairId) / onSelect(row) / onDelete(pairId) / onSelectionChange(rows)
export default function ResultTable({ data, onVerify, onSelect, onDelete, onSelectionChange }) {
  const { t } = useTranslation();
  const [checked, setChecked] = useState({});

  // 判定展示：人工复核判断（黄色）优先 > 人工修正（黄色） > 机器结果
  function displayIsSame(row) {
    if (row.human_judgment !== null && row.human_judgment !== undefined) {
      return row.human_judgment ? t('resultTable.yesHuman') : t('resultTable.noHuman');
    }
    if (row.status === "missing") return t('resultTable.missing');
    if (row.status === "error") return t('resultTable.error');
    if (row.manual_override) return row.is_same ? t('resultTable.yesHuman') : t('resultTable.noHuman');
    if (row.is_same === true) return t('resultTable.yes');
    if (row.is_same === false) return t('resultTable.no');
    return t('resultTable.pending');
  }
  function tagClass(row) {
    if (row.human_judgment !== null && row.human_judgment !== undefined) return "tag-human";
    if (row.status === "missing") return "tag-info";
    if (row.status === "error") return "tag-danger";
    if (row.manual_override) return "tag-human";
    if (row.is_same === true) return "tag-success";
    if (row.is_same === false) return "tag-danger";
    return "tag-warning";
  }

  function toggle(id) {
    const next = { ...checked, [id]: !checked[id] };
    setChecked(next);
    const selected = data.filter((r) => next[r.pair_id]);
    onSelectionChange && onSelectionChange(selected);
  }
  function toggleAll(e) {
    const on = e.target.checked;
    const next = {};
    data.forEach((r) => { next[r.pair_id] = on; });
    setChecked(next);
    onSelectionChange && onSelectionChange(on ? [...data] : []);
  }
  const allOn = data.length > 0 && data.every((r) => checked[r.pair_id]);

  // 缩略图（相对路径，经 vite proxy；URL 已带 ?dev=，imgUrl 追加 token，用 &t= 拼时间戳防 SQLite 复用 id 显示旧图）
  function thumb(url) {
    if (!url) return null;
    return `${imgUrl(url)}&t=${Date.now()}`;
  }

  return (
    <div className="table-wrap smart-table-wrap">
      <table className="smart-table">
        <thead>
          <tr>
            <th style={{ width: 34 }} className="check-cell"><input type="checkbox" checked={allOn} onChange={toggleAll} /></th>
            <th style={{ width: 120 }}>{t('resultTable.image')}</th>
            <th style={{ width: 76 }}>UUID</th>
            <th style={{ width: 96 }}>{t('resultTable.location')}</th>
            <th style={{ width: 44 }}>{t('resultTable.index')}</th>
            <th className="th-center" style={{ width: 104 }}>{t('resultTable.judgment')}</th>
            <th className="th-center" style={{ width: 66 }}>{t('resultTable.confidence')}</th>
            <th className="th-center" style={{ width: 52 }}>{t('resultTable.inliers')}</th>
            <th className="th-center" style={{ width: 70 }}>{t('resultTable.inlierRatio')}</th>
            <th style={{ width: 216 }} className="th-center">{t('resultTable.action')}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.pair_id}
                className={checked[row.pair_id] ? "row-checked" : ""}
                onDoubleClick={(e) => {
                  // 双击行勾选/取消（排除勾选列与操作列，避免与勾选交互冲突）
                  const td = e.target.closest("td");
                  if (td && (td.classList.contains("check-cell") || td.classList.contains("cell-ops"))) return;
                  toggle(row.pair_id);
                }}>
              {/* 勾选列：复选框本身可点击，双击该列不触发行勾选 */}
              <td className="check-cell">
                <input type="checkbox" checked={!!checked[row.pair_id]}
                       onChange={() => toggle(row.pair_id)} />
              </td>
              <td className="thumb-cell">
                {thumb(row.left_image_url) && (
                  <span className="thumb-zoom" style={{ "--zoom-src": `url("${thumb(row.left_image_url)}")` }}>
                    <img src={thumb(row.left_image_url)} alt={t('resultTable.rectify')} title={row.left_filename}
                         onClick={(e) => e.stopPropagation()} />
                  </span>
                )}
                {thumb(row.right_image_url) && (
                  <span className="thumb-zoom" style={{ "--zoom-src": `url("${thumb(row.right_image_url)}")` }}>
                    <img src={thumb(row.right_image_url)} alt={t('resultTable.inspect')} title={row.right_filename}
                         onClick={(e) => e.stopPropagation()} />
                  </span>
                )}
              </td>
              <td title={row.uuid || ""}>{row.uuid ? row.uuid.slice(0, 8) + "..." : "-"}</td>
              <td title={row.location_name || ""}>{row.location_name || "-"}</td>
              <td className="th-center">{row.pair_index}</td>
              <td className="th-center">
                <span className={`smart-tag ${tagClass(row)}`}>{displayIsSame(row)}</span>
              </td>
              <td className="th-center">{row.confidence ?? "-"}</td>
              <td className="th-center">{row.inliers ?? "-"}</td>
              <td className="th-center">{row.inlier_ratio ?? "-"}</td>
              <td className="cell-ops" onClick={(e) => e.stopPropagation()}>
                {(row.status === "pending" || row.status === "error" || row.status === "running") && (
                  <button className="btn small btn-view" onClick={() => onVerify(row.pair_id)}>{t('resultTable.verify')}</button>
                )}
                {row.status === "done" && (
                  <>
                    <button className="btn small btn-view" onClick={() => onSelect(row)}>{t('resultTable.view')}</button>
                    <button className="btn small btn-recheck" onClick={() => onVerify(row.pair_id)}>{t('resultTable.reVerify')}</button>
                  </>
                )}
                <button className="btn small btn-del" onClick={() => onDelete(row.pair_id)}>{t('resultTable.delete')}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
