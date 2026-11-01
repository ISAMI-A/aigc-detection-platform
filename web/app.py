"""
AI 检测平台 · Web 主入口
========================================
组装三个功能子模块：
  - detect.py            图像篡改检测（TruFor V2.4，挂载 /api）
  - smart_verify/        点位真实性核验（SuperPoint+LightGlue，挂载 /smart）
  - rs_verify/           遥感变化核验（Remote_sensing 子进程，挂载 /rsverify）

启动：
    .venv\\Scripts\\python.exe web/app.py          # 默认 http://127.0.0.1:8000
    可用环境变量 WEB_HOST / WEB_PORT 覆盖监听地址与端口
"""
import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api_envelope import install as install_envelope
from auth import router as auth_router
from admin import router as admin_router, public_router as announcement_router
from chat import router as chat_router
from detect import router as detect_router
from smart_verify.app import smart_app
from rs_verify.app import rs_app
from face.app import face_app
from model_manager import manager
from feature_gate import FeatureGateMiddleware

app = FastAPI(title="AIGC 检测平台", version="0.4.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# 功能开关后端拦截（批次5）：开关关闭时非 admin 返回 1009
app.add_middleware(FeatureGateMiddleware)

# 统一接口响应格式 {code, msg, data}（流式/图片/导出保持原样；子应用已各自注册异常处理）
install_envelope(app)

# 登录体系：/api/auth/*
app.include_router(auth_router)

# 系统管理（admin）：/api/admin/* + 公告公开接口 /api/announcements
app.include_router(admin_router)
app.include_router(announcement_router)

# 通知中心 · 聊天/好友/公告：/api/chat/*（仅登录用户）
app.include_router(chat_router)

# 图像篡改检测：/api/*
app.include_router(detect_router)

# 点位真实性核验：/smart/*（独立 SQLite/存储目录，与检测系统互不干扰）
app.mount("/smart", smart_app)

# 遥感变化核验：/rsverify/*（Remote_sensing 子进程，独立 SQLite/存储目录）
app.mount("/rsverify", rs_app)

# 人脸识别：/face/*（FaceRecognition 模块进程内直调，独立 SQLite/存储目录；
# 人脸库 faces.db 在模块内全局共享）
app.mount("/face", face_app)


@app.get("/api/models")
def api_models():
    """统一模型管理器的占用状态（多系统模型集中调度，供系统设置展示）"""
    return manager.stats()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app,
                host=os.getenv("WEB_HOST", "127.0.0.1"),
                port=int(os.getenv("WEB_PORT", "8000")))
