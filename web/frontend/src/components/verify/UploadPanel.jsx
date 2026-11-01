import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { smartApi } from "../../api/smartApi.js";

// 上传面板：拖拽/点击上传 + 缩略图列表 + 拖拽排序 + 勾选（选择比对：多选 + 点击顺序编号 1,2,3...）
// 勾选交互：双击项勾选/取消（排除勾选框列与删除列）；勾选框列复选框可直接点击
// 状态联动：files 变化即通过 onFilesChanged 上报父组件（保证按钮可用态即时更新）
// 通知：重复文件等提示通过 onNotify(msg) 交给父组件 toast，不用浏览器弹窗
// 可配置：imageUrlFn 自定义已上传图片 URL（默认 smartApi.imageUrl）；
//         onLocalCache(name, blob) 可选，新增本地文件时回调（供父组件持久化缓存，刷新不丢）
const UploadPanel = forwardRef(function UploadPanel(
  {
    title, showCheckbox, onFilesChanged, onDeleteImage, onNotify, onClearFiles,
    imageUrlFn, onLocalCache, onLocalDelete, onUploadFile,
  }, ref) {
  const { t } = useTranslation();
  const [files, setFiles] = useState([]);
  const inputRef = useRef(null);
  // 拖拽排序状态
  const dragStartIdx = useRef(-1);
  const [dragActive, setDragActive] = useState(false);
  const [dropIdx, setDropIdx] = useState(-1);
  const [dropPos, setDropPos] = useState("before");

  const imgUrl = imageUrlFn || smartApi.imageUrl;

  // files 变化统一上报父组件（effect 阶段执行，避免渲染期 setState 警告）
  useEffect(() => {
    onFilesChanged && onFilesChanged(files);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  // 切换为非勾选模式（顺序匹配等）时清除全部选中/编号状态，避免高亮残留
  useEffect(() => {
    if (!showCheckbox) {
      setFiles((old) => (old.some((f) => f.selected || f.selOrder)
        ? old.map((f) => ({ ...f, selected: false, selOrder: 0 })) : old));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCheckbox]);

  function push(f) {
    setFiles((old) => [...old, f]);
  }

  // 处理新增文件（input change / drop）：先做重名检查（含已上传到服务器的图片）
  // 如果传了 onUploadFile，选文件后立即上传到后端（上传即落盘，刷新可恢复）
  async function addRawFiles(fileList) {
    const arr = [...fileList].filter((f) => /\.(png|jpe?g|webp|bmp|tiff?)$/i.test(f.name || ""));
    for (const raw of arr) {
      if (files.some((f) => f.name === raw.name)) {
        onNotify && onNotify(t('verify.uploadExisting', { name: raw.name }));
        continue;
      }
      push({
        id: undefined, raw, name: raw.name,
        thumbUrl: URL.createObjectURL(raw),
        selected: false, selOrder: 0, uploaded: false,
      });
      if (onLocalCache) onLocalCache({ name: raw.name, blob: raw });
      // 上传即落盘：选文件后立即上传到后端
      if (onUploadFile) {
        try {
          const res = await onUploadFile(raw, raw.name);
          if (res && res.id) {
            setFiles((old) => old.map((f) =>
              f.name === raw.name && !f.id
                ? { ...f, id: res.id, uploaded: true,
                    thumbUrl: `${imgUrl(res.id)}&t=${Date.now()}` }
                : f
            ));
          }
        } catch (e) {
          onNotify && onNotify(`上传失败: ${e.message}`);
          setFiles((old) => old.filter((f) => f.name !== raw.name));
        }
      }
    }
  }

  function onDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer && e.dataTransfer.files) addRawFiles(e.dataTransfer.files);
  }

  // 勾选切换（选择比对模式）：选中分配递增顺序编号，取消清除编号
  function toggleSelect(idx) {
    if (!showCheckbox) return;
    setFiles((old) => {
      const maxOrder = old.reduce((m, f) => Math.max(m, f.selOrder || 0), 0);
      return old.map((f, i) => {
        if (i !== idx) return f;
        const willSel = !f.selected;
        return { ...f, selected: willSel, selOrder: willSel ? maxOrder + 1 : 0 };
      });
    });
  }

  // ===== 拖拽排序（HTML5 DnD：必须 preventDefault 才能触发 drop） =====
  function handleDragStart(idx, e) {
    dragStartIdx.current = idx;
    setDragActive(true);
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(idx));  // 必须设置数据，否则部分浏览器不进入拖拽
    }
  }
  function handleItemDragOver(idx, e) {
    e.preventDefault();  // 关键：不阻止默认则 drop 不触发
    e.stopPropagation();
    if (dragStartIdx.current === -1 || dragStartIdx.current === idx) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const y = e.clientY - rect.top;
    setDropIdx(idx);
    setDropPos(y < rect.height / 2 ? "before" : "after");
  }
  function handleDrop(idx, e) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const fromIdx = dragStartIdx.current;
    dragStartIdx.current = -1; setDropIdx(-1);
    if (fromIdx === -1 || fromIdx === idx) return;
    let target = dropPos === "after" ? idx + 1 : idx;
    if (fromIdx < target) target -= 1;
    setFiles((old) => {
      const next = [...old];
      const [item] = next.splice(fromIdx, 1);
      next.splice(target, 0, item);
      return next;
    });
  }

  // ===== 删除 =====
  function handleDeleteImage(idx) {
    const file = files[idx];
    if (file.id) {
      onDeleteImage && onDeleteImage(file.id);
    } else {
      if (file.thumbUrl.startsWith("blob:")) URL.revokeObjectURL(file.thumbUrl);
      if (onLocalDelete) onLocalDelete(file.name);
      setFiles((old) => old.filter((_, i) => i !== idx));
    }
  }

  // ===== 一键清空 / 清除选中 =====
  // 父组件未传 onClearFiles 时（如遥感页无服务器文件），本地文件直接清理（含 blob URL 与本地缓存）
  function handleClear() {
    const sel = files.filter((f) => f.selected);
    const list = sel.length > 0 ? sel : files;   // 有勾选清选中，无勾选清全部
    if (list.length === 0) return;
    if (onClearFiles) { onClearFiles(list); return; }
    const names = new Set((list || []).map((f) => f.name));
    (list || []).forEach((f) => {
      if (f.thumbUrl.startsWith("blob:")) URL.revokeObjectURL(f.thumbUrl);
      if (onLocalDelete) onLocalDelete(f.name);
    });
    setFiles((old) => old.filter((f) => !names.has(f.name)));
  }

  // ===== 暴露给父组件 =====
  useImperativeHandle(ref, () => ({
    getFiles: () => files,
    // 整体替换文件列表（遥感页"一键交换"用：两侧面板互换成对方的列表）
    replaceFiles(list) {
      setFiles(Array.isArray(list) ? list : []);
    },
    // 按文件列表移除面板条目（服务器删除由父组件负责，这里只清理面板与 blob）
    removeFiles(list) {
      const names = new Set((list || []).map((f) => f.name));
      files.forEach((f) => {
        if (names.has(f.name) && f.thumbUrl.startsWith("blob:")) URL.revokeObjectURL(f.thumbUrl);
      });
      setFiles((old) => old.filter((f) => !names.has(f.name)));
    },
    markUploaded(records) {
      const nameToId = {};
      (records || []).forEach((r) => { nameToId[r.filename] = r.id; });
      const next = files.map((f) => (nameToId[f.name] !== undefined
        ? { ...f, id: nameToId[f.name], uploaded: true,
            thumbUrl: `${imgUrl(nameToId[f.name])}&t=${Date.now()}` }
        : f));
      setFiles(next);
    },
    removeFileById(imageId) {
      const next = files.filter((f) => f.id !== imageId);
      if (next.length !== files.length) setFiles(next);
    },
    restoreImages(records) {
      const next = [...files];
      (records || []).forEach((r) => {
        if (next.some((f) => f.id === r.id)) return; // 避免重复添加
        next.push({
          id: r.id, raw: null, name: r.filename, selected: false, selOrder: 0,
          uploaded: true, thumbUrl: `${imgUrl(r.id)}&t=${Date.now()}`,
        });
      });
      setFiles(next);
    },
    // 恢复本地缓存文件（IndexedDB 等），刷新后列表与缩略图不丢失
    restoreLocal(records) {
      const next = [...files];
      (records || []).forEach((r) => {
        if (next.some((f) => f.name === r.name)) return;
        next.push({
          id: undefined, raw: r.blob, name: r.name, selected: false, selOrder: 0,
          uploaded: false, thumbUrl: URL.createObjectURL(r.blob),
        });
      });
      setFiles(next);
    },
    reset() {
      files.forEach((f) => { if (f.thumbUrl.startsWith("blob:")) URL.revokeObjectURL(f.thumbUrl); });
      setFiles([]);
    },
  }), [files]);

  return (
    <div className="smart-panel upload-panel">
      <div className="panel-header">
        <h3>{title}</h3>
        <div className="panel-actions">
          {/* 选择比对模式：有勾选时按钮/计数显示"清除选中/已选 N"，否则与普通模式一致 */}
          {showCheckbox && files.some((f) => f.selected) ? (
            <>
              <button className="btn tiny" onClick={handleClear}>
                {t('upload.clearSelected', { n: files.filter((f) => f.selected).length })}
              </button>
              <span className="file-count">{t('upload.selected', { n: files.filter((f) => f.selected).length })}</span>
            </>
          ) : (
            <>
              <button className="btn tiny" onClick={handleClear}>{t('upload.clearAll')}</button>
              <span className="file-count">{t('upload.total', { n: files.length })}</span>
            </>
          )}
        </div>
      </div>

      {/* 上传区（拖拽/点击） */}
      <div className="smart-dropzone"
           onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
           onDragLeave={() => setDragActive(false)}
           onDrop={onDrop}
           onClick={() => inputRef.current && inputRef.current.click()}>
        <div className="smart-drop-icon">⬆</div>
        <div className="smart-drop-text">{t('upload.dragHint')}</div>
        <div className="smart-drop-tip">{t('upload.formatHint')}</div>
        <input ref={inputRef} type="file" multiple accept=".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff" style={{ display: "none" }}
               onChange={(e) => { addRawFiles(e.target.files); e.target.value = ""; }} />
      </div>

      {/* 缩略图列表（可拖拽排序 / 双击勾选 / 顺序编号） */}
      {files.length > 0 && (
        <div className="thumb-scroll">
          {files.map((file, idx) => (
            <div key={file.id || `local-${idx}`} className="thumb-item-wrapper">
              {/* 拖拽指示线：绝对定位不占布局高度，避免拖动时窗口抖动 */}
              {dragActive && dropIdx === idx && <div className={`drop-line ${dropPos}`} />}
              <div className={`thumb-item ${file.selected ? "selected" : ""} ${dragStartIdx.current === idx ? "dragging" : ""}`}
                   draggable
                   title={file.name}
                   onDragStart={(e) => handleDragStart(idx, e)}
                   onDragOver={(e) => handleItemDragOver(idx, e)}
                   onDragEnd={() => { dragStartIdx.current = -1; setDropIdx(-1); setDragActive(false); }}
                   onDrop={(e) => handleDrop(idx, e)}
                   onDoubleClick={(e) => {
                     // 双击项勾选/取消（排除勾选框列与删除列，避免与勾选交互冲突）
                     if (e.target.closest(".check-mark") || e.target.closest(".thumb-delete")) return;
                     toggleSelect(idx);
                   }}>
                <div className="drag-handle">⠿</div>
                <div className="thumb-img-wrap">
                  <img src={file.thumbUrl} alt={file.name} className="thumb-img" draggable={false} />
                </div>
                <div className="thumb-filename">{file.name}</div>
                {showCheckbox && file.selOrder > 0 && (
                  <span className="thumb-order">{file.selOrder}</span>
                )}
                {showCheckbox && (
                  <div className="check-mark" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={!!file.selected} onChange={() => toggleSelect(idx)} />
                  </div>
                )}
                <div className="thumb-delete" title={t('upload.delete')} onClick={(e) => { e.stopPropagation(); handleDeleteImage(idx); }}>✕</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

export default UploadPanel;
