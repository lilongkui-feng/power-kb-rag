# -*- coding: utf-8 -*-
"""统一日志：setup_logging() 配置根 logger（控制台 + logs/ 轮转文件，text|json），request_id 用 contextvar 贯穿（含线程池），
RedactingFormatter 在输出前自动打码：已配置的密钥原值、Bearer/Authorization、sk-…、api_key=… 等。
用法：from kblog import get_logger, event, q_repr；event(log, "rag.answer", provider=..., total_secs=...)"""
from __future__ import annotations
import contextvars, copy, hashlib, json, logging, logging.handlers, os, re, sys, time
from typing import Any

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_PATTERNS = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;\"']+"), r"\1\2***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/=]{6,}"), "Bearer ***"),
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s,;\"']+"), r"\1***"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'}]{4,}"), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"\bxai-[A-Za-z0-9_\-]{8,}"), "xai-***"),
]
_secrets: list[str] = []

def register_secrets(values):
    """把已配置的密钥原值加入打码表（长的先替换）"""
    global _secrets
    _secrets = sorted({v for v in values if v and len(v) >= 6}, key=len, reverse=True)

def redact(text: str) -> str:
    if not text:
        return text
    for s in _secrets:
        if s in text:
            text = text.replace(s, "***")
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    return text

class _CtxFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id.get()
        return True

class RedactingFormatter(logging.Formatter):
    def format(self, record):
        f = getattr(record, "fields", None)
        if f:                                      # 不改原 record（多个 handler 共用同一个 record）
            record = copy.copy(record)
            record.msg = f"{record.getMessage()} " + " ".join(f"{k}={_fmt(v)}" for k, v in f.items())
            record.args = None
        return redact(super().format(record))

class JsonFormatter(logging.Formatter):
    def format(self, record):
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)) + f".{int(record.msecs):03d}" + time.strftime("%z"),
             "level": record.levelname, "logger": record.name, "request_id": getattr(record, "request_id", "-"), "msg": record.getMessage()}
        d.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(d, ensure_ascii=False, default=str))

def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)

_configured = False
logging.raiseExceptions = False          # 解释器退出时 handler 已关闭等日志内部错误不再刷屏

def setup_logging(force: bool = False, s=None):
    """幂等；读取 config.settings()（LOG_LEVEL / LOG_FORMAT / LOG_DIR / LOG_FILE / 轮转参数）"""
    global _configured
    if _configured and not force:
        return
    if s is None:
        from config import settings
        s = settings()
    register_secrets(s.secret_values())
    fmt = JsonFormatter() if s.log_format == "json" else RedactingFormatter(
        "%(asctime)s %(levelname)s %(name)s [rid=%(request_id)s] %(message)s")
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_powerkb", False) or force:
            root.removeHandler(h)
    hs = [logging.StreamHandler(sys.stderr)]
    if s.log_file:
        d = s.path(s.log_dir)
        os.makedirs(d, exist_ok=True)
        hs.append(logging.handlers.RotatingFileHandler(os.path.join(d, s.log_file), maxBytes=s.log_max_bytes,
                                                       backupCount=s.log_backup_count, encoding="utf-8"))
    for h in hs:
        h._powerkb = True
        h.setFormatter(fmt); h.addFilter(_CtxFilter())
        root.addHandler(h)
    root.setLevel(s.log_level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):       # uvicorn 日志也走统一格式与打码
        lg = logging.getLogger(name); lg.handlers.clear(); lg.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)       # 访问日志由 api 中间件记录（带 request_id 和耗时）
    for noisy in ("httpx", "httpcore", "urllib3", "chromadb", "huggingface_hub", "sentence_transformers", "jieba"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

def event(logger: logging.Logger, name: str, level: int = logging.INFO, **fields: Any):
    """结构化事件：text 格式输出 `name k=v ...`，json 格式把字段平铺进 JSON"""
    logger.log(level, name, extra={"fields": fields})

def q_repr(q: str) -> str:
    """问句的日志表示：LOG_QUESTIONS=true 记录原文（截断 200 字），否则只记长度 + 哈希"""
    try:
        from config import settings
        full = settings().log_questions
    except Exception:
        full = False
    if full:
        return (q or "")[:200]
    return f"<len={len(q or '')} sha1={hashlib.sha1((q or '').encode()).hexdigest()[:10]}>"
