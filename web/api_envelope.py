"""统一接口响应格式：{code, msg, data}

- 中间件（纯 ASGI）：JSON 响应统一包装为 {code:0, msg:"", data: body}
  - 非 JSON 响应（NDJSON 流式 / 图片 / Excel 下载）透传不包装
  - 已包装的响应（异常处理或业务侧主动返回 {code,msg,data}）跳过，幂等
  - 注：不用 BaseHTTPMiddleware——新版 Starlette 会把下游响应包装成
    _StreamingResponse 并缓冲，导致无法读取 body / 误判跳过（批次1 踩坑）
- 异常处理：HTTPException → {code, msg, data:null}
  - detail 传 dict（如 {"code": 1002, "msg": "用户名已存在"}）时可带业务码；否则 code=HTTP 状态码

用法：
- 主应用（app.py）：install(app) —— 中间件 + 异常处理
- 子应用（smart/rs 挂载子应用）：install_errors(app) —— 只注册异常处理，
  避免父应用中间件已包装后子应用再包一层（双重包装）
"""
import json
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _EnvelopeMiddleware:
    """纯 ASGI 中间件：JSON 响应包装为 {code:0, msg:'', data: body}；流式/二进制透传。"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        passthrough = False
        status = 200
        headers = []
        chunks = []

        async def send_wrapper(message: Message) -> None:
            nonlocal passthrough, status, headers
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = message["headers"]
                ct = ""
                for k, v in headers:
                    if k == b"content-type":
                        ct = v.decode()
                        break
                if not ct.startswith("application/json"):
                    passthrough = True  # 流式/图片/下载：直接透传
                    await send(message)
            elif message["type"] == "http.response.body":
                if passthrough:
                    await send(message)
                    return
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    await self._finish(send, status, headers, chunks)

        await self.app(scope, receive, send_wrapper)

    async def _finish(self, send, status, headers, chunks):
        raw = b"".join(chunks)
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if isinstance(data, dict) and "code" in data and "msg" in data and "data" in data:
            body = raw  # 已包装（异常处理或业务侧主动返回）
        else:
            body = json.dumps({"code": 0, "msg": "", "data": data}, ensure_ascii=False).encode()
        new_headers = [(k, v) for k, v in headers
                       if k not in (b"content-length", b"content-type")] + [(b"content-type", b"application/json")]
        await send({"type": "http.response.start", "status": status, "headers": new_headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})


def api_exception_handler(request: Request, exc: HTTPException):
    """HTTPException → {code, msg, data:null}；detail 传 dict 时可带业务码（如 1002 等）"""
    detail = exc.detail
    if isinstance(detail, dict) and "msg" in detail:
        code = detail.get("code", exc.status_code)
        msg = detail["msg"]
    else:
        code = exc.status_code
        msg = str(detail) if detail is not None else ""
    return JSONResponse(status_code=exc.status_code,
                        content={"code": code, "msg": msg, "data": None})


def install(app: FastAPI):
    """主应用：统一包装中间件 + 异常处理"""
    app.add_middleware(_EnvelopeMiddleware)
    install_errors(app)


def install_errors(app: FastAPI):
    """仅注册异常处理（子应用用，避免中间件双重包装）"""
    app.add_exception_handler(HTTPException, api_exception_handler)
    # 路由未匹配的 404（StarletteHTTPException）与未捕获 500 也统一包装
    app.add_exception_handler(StarletteHTTPException, _starlette_http_handler)
    app.add_exception_handler(Exception, _unhandled_handler)


async def _starlette_http_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    msg = str(detail) if detail is not None else "请求失败"
    return JSONResponse(status_code=exc.status_code,
                        content={"code": exc.status_code, "msg": msg, "data": None})


async def _unhandled_handler(request: Request, exc: Exception):
    """未捕获异常：打印堆栈便于排查，响应统一包装为 500"""
    traceback.print_exc()
    return JSONResponse(status_code=500,
                        content={"code": 500, "msg": "服务器内部错误", "data": None})
