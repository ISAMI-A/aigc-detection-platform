// 人脸登录面板（AuthModal 人脸 tab 内容）
// - 默认：选择本地照片识别登录
// - 下方按钮：打开摄像头实时检测匹配（getUserMedia，约 1.5s/帧自动识别，命中即登录）
// - 摄像头不可用（非安全上下文/无设备）时提示降级为照片上传
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { loginByFace, loginByFaceFrame } from "../../api/faceApi.js";

export default function FaceLoginPanel({ onSuccess, onError }) {
  const { t } = useTranslation();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [camOn, setCamOn] = useState(false);
  const [camErr, setCamErr] = useState("");
  const fileInput = useRef(null);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const busyRef = useRef(false);

  // 组件卸载：关摄像头/停定时器
  useEffect(() => () => stopCam(), []);

  function stopCam() {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((tr) => tr.stop());
      streamRef.current = null;
    }
    setCamOn(false);
    busyRef.current = false;
    setBusy(false);
  }

  // 统一登录收尾：matched 数据 → onSuccess({token,user})（AuthModal 内走 must_change_password 检查）
  async function finishLogin(d) {
    if (!d || !d.matched) {
      setMsg((d && d.reason) || t("auth.faceNotMatched"));
      return false;
    }
    await onSuccess(() => Promise.resolve({ token: d.token, user: d.user }));
    return true;
  }

  // 照片登录
  async function pickPhoto(e) {
    const f = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!f) return;
    setBusy(true); setMsg(t("auth.faceRecognizing"));
    try {
      const d = await loginByFace(f);
      await finishLogin(d);
    } catch (err) {
      setMsg(err.message || t("auth.faceFail"));
    } finally {
      setBusy(false);
    }
  }

  // 打开摄像头（自动间隔截帧识别，命中即登录）
  async function openCam() {
    setCamErr(""); setMsg("");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCamErr(t("auth.faceCamUnsupported"));
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      });
      streamRef.current = stream;
      setCamOn(true);
      // video 元素挂载后播放
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
      }, 50);
      // 定时截帧识别（1.5s 一帧；命中即停止）
      timerRef.current = setInterval(async () => {
        if (busyRef.current || !videoRef.current) return;
        const v = videoRef.current;
        if (!v.videoWidth) return;
        busyRef.current = true;
        setBusy(true);
        try {
          const c = document.createElement("canvas");
          c.width = v.videoWidth;
          c.height = v.videoHeight;
          c.getContext("2d").drawImage(v, 0, 0);
          const d = await loginByFaceFrame(c.toDataURL("image/jpeg", 0.9));
          if (d && d.matched) {
            stopCam();
            await finishLogin(d);
            return;
          }
          setMsg((d && d.reason) || t("auth.faceSearching"));
        } catch (_) {
          // 单帧失败静默重试
        } finally {
          busyRef.current = false;
          setBusy(false);
        }
      }, 1500);
    } catch (_) {
      setCamErr(t("auth.faceCamDenied"));
    }
  }

  return (
    <div className="face-login-panel">
      <div className="face-login-tip">{t("auth.faceLoginTip")}</div>
      {camOn && (
        <div className="face-login-video-wrap">
          <video ref={videoRef} playsInline muted className="face-login-video" />
          <div className="face-login-scanline" />
        </div>
      )}
      {msg && <div className="auth-err face-login-msg">{msg}</div>}
      {camErr && <div className="auth-err">{camErr}</div>}
      <input ref={fileInput} type="file" accept="image/*" style={{ display: "none" }} onChange={pickPhoto} />
      <div className="face-login-btns">
        <button className="btn primary" disabled={busy}
                onClick={() => fileInput.current && fileInput.current.click()}>
          {t("auth.facePickPhoto")}
        </button>
        <button className="btn" disabled={busy}
                onClick={() => (camOn ? stopCam() : openCam())}>
          {camOn ? t("auth.faceCamClose") : t("auth.faceCamOpen")}
        </button>
      </div>
      {busy && <div className="dim face-login-busy">{t("auth.faceRecognizing")}</div>}
    </div>
  );
}
