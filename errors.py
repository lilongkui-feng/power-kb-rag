# -*- coding: utf-8 -*-
"""PowerKB 异常体系：每个异常自带 HTTP 状态码和稳定的错误码，API 全局处理器据此生成统一错误体
{"error": {"code", "message", "detail", "request_id"}}。message 面向用户（中文、无堆栈、无密钥）。"""
from __future__ import annotations

class PowerKBError(Exception):
    status = 500
    code = "internal_error"
    default_message = "服务器内部错误"
    def __init__(self, message: str | None = None, detail=None, *, code: str | None = None, status: int | None = None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.detail = detail
        if code:
            self.code = code
        if status:
            self.status = status
    @property
    def status_code(self):          # 兼容旧 ApiError 接口
        return self.status

class ConfigError(PowerKBError):
    status, code, default_message = 500, "config_error", "配置错误"

# ---- 请求 / 鉴权 ----
class BadRequest(PowerKBError):
    status, code, default_message = 400, "bad_request", "请求不合法"
class AuthError(PowerKBError):
    status, code, default_message = 401, "unauthorized", "缺少或错误的 API Token"
class Forbidden(PowerKBError):
    status, code, default_message = 403, "forbidden", "无权执行该操作"
class NotFound(PowerKBError):
    status, code, default_message = 404, "not_found", "资源不存在"
class Busy(PowerKBError):
    status, code, default_message = 409, "busy", "资源忙，请稍后重试"

# ---- 文档 ----
class UnsupportedFile(PowerKBError):
    status, code, default_message = 415, "unsupported_type", "只支持 PDF / DOCX"
class FileTooLarge(PowerKBError):
    status, code, default_message = 413, "payload_too_large", "文件过大"
class DocumentParseError(PowerKBError):
    status, code, default_message = 422, "document_parse_error", "文档解析失败（可能已加密、损坏或不是有效的 PDF/DOCX）"

# ---- 检索 / 索引 ----
class RetrievalError(PowerKBError):
    status, code, default_message = 500, "retrieval_error", "检索失败"
class IndexNotReady(PowerKBError):
    status, code, default_message = 503, "index_not_ready", "模型或索引尚未就绪，请稍后重试"

# ---- LLM ----
class ProviderNotReady(PowerKBError):
    status, code, default_message = 400, "provider_not_ready", "LLM 提供方未配置"
class LLMError(PowerKBError):
    status, code, default_message = 502, "llm_error", "大模型调用失败"
class LLMTimeout(LLMError):
    status, code, default_message = 504, "llm_timeout", "大模型响应超时"
class LLMRateLimited(LLMError):
    status, code, default_message = 429, "llm_rate_limited", "大模型接口限流，请稍后重试"
class LLMAuthError(LLMError):
    status, code, default_message = 502, "llm_auth_failed", "大模型接口鉴权失败（服务端 API Key 无效或无权限）"
class LLMUnavailable(LLMError):
    status, code, default_message = 503, "llm_unavailable", "大模型服务不可用（无法连接或服务端错误）"

ERROR_TABLE = [ConfigError, BadRequest, AuthError, Forbidden, NotFound, Busy, UnsupportedFile, FileTooLarge, DocumentParseError,
               RetrievalError, IndexNotReady, ProviderNotReady, LLMError, LLMTimeout, LLMRateLimited, LLMAuthError, LLMUnavailable]
