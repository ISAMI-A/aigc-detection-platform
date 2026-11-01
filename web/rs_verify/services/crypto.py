"""AES 加密工具（用于 api_key 等敏感配置落库）。

密钥来源：环境变量 RS_CRYPTO_KEY，未设置时使用内置默认值（本地工具场景）。
通过 SHA-256 派生为 32 字节 AES-256-GCM 密钥。
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DEFAULT_KEY = "rs-verify-web-local-default-key-2026"

_NONCE_LEN = 12


def _get_key() -> bytes:
    raw = os.environ.get("RS_CRYPTO_KEY", _DEFAULT_KEY).encode("utf-8")
    return hashlib.sha256(raw).digest()  # 32 bytes → AES-256


def encrypt(plain: str) -> str:
    """加密明文，返回 base64(nonce + ciphertext)；空串原样返回。"""
    if not plain:
        return ""
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_get_key()).encrypt(nonce, plain.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str) -> str:
    """解密 encrypt 的结果；空串/非法串返回空串。"""
    if not token:
        return ""
    try:
        data = base64.b64decode(token)
        nonce, ct = data[:_NONCE_LEN], data[_NONCE_LEN:]
        return AESGCM(_get_key()).decrypt(nonce, ct, None).decode("utf-8")
    except Exception:
        return ""
