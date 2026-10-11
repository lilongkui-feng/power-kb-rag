# -*- coding: utf-8 -*-
"""PowerKB API 服务（FastAPI）：检索 / 问答（含 SSE 流式）/ 文档入库与删除。
启动：uvicorn api:app --host 127.0.0.1 --port 8000      （或 deploy/start_api.sh）
文档：http://127.0.0.1:8000/docs （Swagger）、/redoc、/openapi.json

环境变量：
  KB_API_TOKEN        非空则启用鉴权（Authorization: Bearer <token> 或 X-API-Key: <token>）；/health 不鉴权
  KB_CORS_ORIGINS     逗号分隔的允许来源，默认 http://localhost:8501,http://127.0.0.1:8501；"*" 表示全部
  KB_MAX_UPLOAD_MB    上传大小上限，默认 50
  KB_MAX_CONCURRENCY  同时执行的 search/ask 数，默认 2（CPU 重排/向量化是重任务）
  KB_PRELOAD          0 = 启动时不预加载模型（测试用），默认 1
  SILICONFLOW_API_KEY 等云端 key 只在服务端读取，任何接口都不会返回 key
"""
from __future__ import annotations
import asyncio, contextvars, json, logging, os, shutil, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional

from config import settings, secret                      # 先加载配置（校验失败直接报 ConfigError，进程退出）
from errors import (PowerKBError, AuthError, Busy, DocumentParseError, FileTooLarge, Forbidden, IndexNotReady, NotFound,
                    ProviderNotReady, UnsupportedFile, BadRequest)
import kblog
kblog.setup_logging()
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import kb_store, rag

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.0.0"
log = logging.getLogger("powerkb.api")
CFG = settings()
MAX_UPLOAD = CFG.kb_max_upload_mb * 1024 * 1024
SEM = asyncio.Semaphore(CFG.kb_max_concurrency)
WRITE_LOCK = threading.Lock()                    # 索引写入（入库/删除）串行；Chroma + BM25 + 登记表一起改
INGEST_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")
JOBS: dict[str, dict] = {}
STATE: dict[str, Any] = {"loaded": False, "load_error": None, "load_secs": None, "started": time.time()}
TMP = os.path.join(HERE, "uploads", "tmp")

def _vs_backend():
    from vector_store import backend
    return backend()

def _load_models():
    t0 = time.time()
    from embed_index import get_model
    from vector_store import get_store
    import rerank, bm25_index
    get_model(); rerank.get_reranker(); bm25_index.load(kb_store.METHOD)
    STATE["vector_count"] = get_store(kb_store.METHOD).count()
    STATE.update(loaded=True, load_secs=round(time.time() - t0, 1))

@asynccontextmanager
async def lifespan(app: FastAPI):
    global INGEST_POOL
    if getattr(INGEST_POOL, "_shutdown", False):                # 同一进程内重复启动（测试）时重建
        INGEST_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")
    kblog.event(log, "config.summary", **{k: v for k, v in CFG.summary().items()
                                          if k.endswith(("_api_key", "_token")) or k in ("vector_store", "kb_collection", "kb_method", "rerank_model",
                                          "bge_model", "llm_fallback", "llm_timeout", "llm_max_retries", "log_level", "log_format", "log_questions",
                                          "kb_max_upload_mb", "kb_max_concurrency", "rag_refuse_below", "rag_expand", "_config_file")})
    if CFG.kb_preload:
        try:
            await run_in_threadpool(_load_models)          # 一次性加载 bge-m3 / reranker / BM25 / Chroma
            log.info("models loaded in %ss", STATE["load_secs"])
        except Exception as e:                              # 加载失败也启动，/health 报告
            STATE["load_error"] = kblog.redact(f"{type(e).__name__}: {str(e)[:300]}"); log.exception("model load failed")
    yield
    INGEST_POOL.shutdown(wait=False, cancel_futures=True)

TAGS = [{"name": "system", "description": "健康检查与配置"}, {"name": "retrieval", "description": "检索"},
        {"name": "qa", "description": "问答（RAG）"}, {"name": "documents", "description": "文档入库 / 列表 / 删除 / 任务进度"}]
app = FastAPI(title="PowerKB API", version=VERSION, lifespan=lifespan, openapi_tags=TAGS,
              description="电力设备运维知识库 RAG 服务：hybrid 检索（bge-m3 + BM25）+ bge-reranker 重排 + LLM 生成与引用校验。")
origins = [o.strip() for o in CFG.kb_cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"], allow_credentials="*" not in origins)

# ---------------- 统一错误格式 + 请求日志 ----------------
class ErrorBody(BaseModel):
    code: str = Field(..., examples=["not_found"])
    message: str
    detail: Any = None
    request_id: Optional[str] = None

class ErrorResp(BaseModel):
    error: ErrorBody

def _err(status_code: int, code: str, message: str, detail=None, request: Request | None = None):
    rid = kblog.request_id.get()
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": kblog.redact(message), "detail": detail, "request_id": rid}},
                        headers={"X-Request-ID": rid})

ApiError = PowerKBError                                  # 兼容旧名

@app.exception_handler(PowerKBError)
async def _kb_err(request: Request, e: PowerKBError):
    kblog.event(log, "request.error", logging.ERROR if e.status >= 500 else logging.WARNING, code=e.code, status=e.status,
                path=request.url.path, message=e.message)
    return _err(e.status, e.code, e.message, e.detail, request)

@app.exception_handler(HTTPException)
async def _http_err(request: Request, e: HTTPException):
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}.get(e.status_code, "http_error")
    return _err(e.status_code, code, str(e.detail), None, request)

@app.exception_handler(RequestValidationError)
async def _val_err(request: Request, e: RequestValidationError):
    return _err(422, "validation_error", "请求参数校验失败", [{"loc": x.get("loc"), "msg": x.get("msg")} for x in e.errors()], request)

@app.exception_handler(Exception)
async def _unhandled(request: Request, e: Exception):
    log.exception("unhandled error path=%s", request.url.path)          # 堆栈只进日志（已打码），不返回给客户端
    return _err(500, "internal_error", "服务器内部错误，请凭 request_id 查看服务端日志", None, request)

@app.middleware("http")
async def _reqlog(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    rid = "".join(ch for ch in rid if ch.isalnum() or ch in "-_")[:64] or uuid.uuid4().hex[:12]
    token = kblog.request_id.set(rid)
    request.state.rid = rid
    t0 = time.time()
    try:
        resp = await call_next(request)
    except Exception:
        log.exception("request crashed")
        resp = _err(500, "internal_error", "服务器内部错误，请凭 request_id 查看服务端日志")
    resp.headers["X-Request-ID"] = rid
    kblog.event(log, "request", method=request.method, path=request.url.path, status=resp.status_code, ms=round((time.time() - t0) * 1000))
    kblog.request_id.reset(token)
    return resp

# ---------------- 鉴权（KB_API_TOKEN 为空则关闭） ----------------
_bearer = HTTPBearer(auto_error=False)
_apikey = APIKeyHeader(name="X-API-Key", auto_error=False)

def auth(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), key: str | None = Depends(_apikey)):
    tok = secret("kb_api_token") or ""
    if not tok:
        return
    if (cred and cred.credentials == tok) or key == tok:
        return
    raise AuthError("缺少或错误的 API Token（Authorization: Bearer <token> 或 X-API-Key）")

def need_models():
    if not STATE["loaded"]:
        try:
            _load_models()                                  # KB_PRELOAD=0 时按需加载
        except Exception as e:
            raise IndexNotReady(f"模型/索引未就绪（{type(e).__name__}），请稍后重试或查看服务端日志") from None

# ---------------- 数据模型 ----------------
Provider = Literal["local", "siliconflow", "deepseek", "openai", "xai"]
XLang = Literal["none", "dict", "llm", "cap", "mismatch", "auto"]

class Health(BaseModel):
    status: Literal["ok", "loading", "error"]
    version: str
    models_loaded: bool
    load_secs: Optional[float] = None
    load_error: Optional[str] = None
    collection: str
    vector_store: str = Field(..., description="chroma | milvus（VECTOR_STORE）")
    vector_count: Optional[int] = None
    chroma_count: Optional[int] = Field(None, description="兼容旧字段，等于 vector_count")
    bm25_docs: Optional[int] = None
    documents: int
    uptime_secs: float
    jobs_running: int

class ProviderInfo(BaseModel):
    name: str
    ready: bool
    info: str = Field(..., description="base_url · 默认模型；未就绪时为原因（不含 key）")
    default_prompt: str
    default_xlang: str

class ConfigResp(BaseModel):
    providers: list[ProviderInfo]
    default_provider: str
    defaults: dict
    retrieval: dict
    limits: dict
    auth_enabled: bool

class SearchReq(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, examples=["运行中SF6设备灭弧气室湿度限值"])
    top_k: int = Field(5, ge=1, le=20)
    rerank: bool = True
    sources: Optional[list[str]] = Field(None, description="只在这些文档中检索")
    filters: Optional[dict] = Field(None, description="Chroma 风格元数据过滤，如 {\"category\": \"标准\"}；与 sources 同时给时取交集")
    xlang: XLang = "none"
    include_text: bool = True

class Hit(BaseModel):
    rank: int
    chunk_id: str
    source: str
    section: Optional[str] = None
    page_start: Optional[Any] = None
    page_end: Optional[Any] = None
    chunk_type: Optional[str] = None
    score: Optional[float] = None
    rerank_score: Optional[float] = None
    text: Optional[str] = None
    metadata: dict = {}

class SearchResp(BaseModel):
    query: str
    hits: list[Hit]
    timing: dict

class AskReq(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, examples=["阀控蓄电池多久做一次核对性放电？"])
    provider: Optional[Provider] = Field(None, description="空 = 服务端默认（LLM_BASE_URL 或本地 ollama）")
    model: Optional[str] = Field(None, description="覆盖提供方默认模型，如 Qwen/Qwen2.5-72B-Instruct")
    prompt: Optional[Literal["p0", "p1", "p2", "p3"]] = Field(None, description="空 = 本地 p1 / 云端 p2")
    top_k: int = Field(5, ge=1, le=10)
    rerank: bool = True
    expand: Optional[Literal["none", "neighbor", "parent"]] = None
    refuse_below: Optional[float] = Field(-1.0, ge=-1.0, le=1.0, description="-1 = 服务端默认（0.3）；null = 关闭阈值拒答")
    sources: Optional[list[str]] = None
    xlang: Optional[XLang] = Field(None, description="空 = 云端 cap / 本地 none")

class Citation(BaseModel):
    id: int
    source: str
    section: Optional[str] = None
    pages: Optional[str] = None
    chunk_id: Optional[str] = None
    excerpt: Optional[str] = None
    score: Optional[float] = None
    rerank_score: Optional[float] = None

class AskResp(BaseModel):
    question: str
    answer: str
    refused: bool
    threshold_refused: bool = False
    citations: list[Citation]
    invalid_citations: list[int] = []
    warnings: list[str] = Field([], description="数值引用校验告警（numcheck v2）")
    retrieved: list[dict] = []
    timing: dict
    usage: dict = {}
    model: str
    provider: Optional[str] = None
    degraded: bool = Field(False, description="LLM 失败后降级为“仅检索结果”")
    fallback: Optional[dict] = Field(None, description="降级/回退信息 {from, to, reason, message}")

class JobResp(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "duplicate", "failed"]
    error: Optional[dict] = Field(None, description="failed 时 {code, message}")
    progress: float = 0.0
    message: str = ""
    filename: str
    created: float
    finished: Optional[float] = None
    result: Optional[dict] = None

class Doc(BaseModel):
    id: str = Field(..., description="上传文档 = sha256 前 12 位；基础库文档 = base:<文件名>")
    source: str
    chunks: int
    origin: str
    deletable: bool
    pages: Optional[int] = None
    ocr_pages: Optional[int] = None
    added: Optional[str] = None

ERR = {401: {"model": ErrorResp}, 422: {"model": ErrorResp}, 500: {"model": ErrorResp}}

# ---------------- system ----------------
@app.get("/health", response_model=Health, tags=["system"], summary="健康检查（含模型与索引状态，不鉴权）")
def health():
    bm = None
    if STATE["loaded"]:                                       # 实时读取（入库/删除后 BM25 会重建、缓存失效）
        try:
            import bm25_index
            from vector_store import get_store
            bm = len(bm25_index.load(kb_store.METHOD).get("ids", [])) or None
            STATE["vector_count"] = get_store(kb_store.METHOD).count()
        except Exception:
            pass
    st = "ok" if STATE["loaded"] else ("error" if STATE["load_error"] else "loading")
    return Health(status=st, version=VERSION, models_loaded=STATE["loaded"], load_secs=STATE["load_secs"], load_error=STATE["load_error"],
                  collection=kb_store.METHOD, vector_store=_vs_backend(), vector_count=STATE.get("vector_count"), chroma_count=STATE.get("vector_count"), bm25_docs=bm, documents=len(kb_store.list_docs()),
                  uptime_secs=round(time.time() - STATE["started"], 1), jobs_running=sum(j["status"] in ("queued", "running") for j in JOBS.values()))

@app.get("/config", response_model=ConfigResp, tags=["system"], dependencies=[Depends(auth)], responses=ERR, summary="可用 provider 与默认参数（不含任何 key）")
def config():
    ps = []
    for name in rag.PROVIDERS:
        ok, info = rag.provider_ready(name)
        cloud = name in rag.CLOUD_PROVIDERS
        ps.append(ProviderInfo(name=name, ready=ok, info=info, default_prompt=CFG.rag_prompt or ("p2" if cloud else rag.DEFAULT_PROMPT),
                               default_xlang=CFG.rag_xlang or ("cap" if cloud else "none")))
    return ConfigResp(providers=ps, default_provider="local",
                      defaults={"top_k": 5, "rerank": True, "expand": rag.DEFAULT_EXPAND, "refuse_below": rag.DEFAULT_REFUSE_BELOW,
                                "recommended_refuse_below": rag.RECOMMENDED_REFUSE_BELOW, "numcheck": rag.NUMCHECK},
                      retrieval={"collection": kb_store.METHOD, "mode": "hybrid", "alpha": 0.5, "rerank_model": "BAAI/bge-reranker-v2-m3",
                                 "rerank_top_n": 20, "rerank_beta": 0.8, "embed_model": "BAAI/bge-m3", "vector_store": _vs_backend()},
                      limits={"max_upload_mb": MAX_UPLOAD // 1024 // 1024, "max_concurrency": SEM._value if hasattr(SEM, "_value") else None,
                              "upload_types": [".pdf", ".docx"]},
                      auth_enabled=bool(secret("kb_api_token")))

# ---------------- retrieval ----------------
def _filters(sources, filters):
    f = dict(filters or {})
    if sources:
        f["source"] = {"$in": sources}
    return f or None

def _hit(h: dict, text=True) -> Hit:
    m = h.get("metadata", {}) or {}
    return Hit(rank=h["rank"], chunk_id=h["chunk_id"], source=h["source"], section=h.get("heading_path") or m.get("heading_path"),
               page_start=h.get("page_start") or m.get("page_start"), page_end=h.get("page_end") or m.get("page_end"),
               chunk_type=m.get("chunk_type"), score=h.get("score"), rerank_score=h.get("rerank_score"),
               text=h["text"] if text else None, metadata={k: v for k, v in m.items() if k not in ("text_hash",)})

@app.post("/search", response_model=SearchResp, tags=["retrieval"], dependencies=[Depends(auth)], responses=ERR, summary="混合检索 + 可选重排")
async def search(req: SearchReq):
    await run_in_threadpool(need_models)
    from retrieve import search as _search
    t0 = time.time()
    async with SEM:
        hits = await run_in_threadpool(lambda: _search(req.query, k=req.top_k, filters=_filters(req.sources, req.filters), rerank=req.rerank,
                                                       collection=kb_store.METHOD, rerank_use_cache=False, xlang=req.xlang))
    rr = hits[0].pop("_rerank_secs", None) if hits else None
    return SearchResp(query=req.query, hits=[_hit(h, req.include_text) for h in hits],
                      timing={"total_secs": round(time.time() - t0, 2), "rerank_secs": rr})

# ---------------- qa ----------------
def _check_provider(p):
    if p and p in rag.PROVIDERS:
        ok, info = rag.provider_ready(p)
        if not ok:
            raise ProviderNotReady(info)

def _ask_kwargs(req: AskReq) -> dict:
    skw = {"collection": kb_store.METHOD}
    if req.xlang:
        skw["xlang"] = req.xlang
    return dict(k=req.top_k, rerank=req.rerank, provider=req.provider, model=req.model, prompt=req.prompt, expand=req.expand,
                refuse_below=req.refuse_below, filters=_filters(req.sources, None), search_kw=skw)

def _to_resp(q: str, r: dict, provider) -> AskResp:
    return AskResp(question=q, answer=r["answer"], refused=r["refused"], threshold_refused=r.get("threshold_refused", False),
                   citations=[Citation(**{k: s.get(k) for k in Citation.model_fields}) for s in r["sources"]],
                   invalid_citations=r.get("invalid_citations", []), warnings=r.get("support_warnings", []), retrieved=r.get("retrieved", []),
                   timing=r["timing"], usage=r.get("usage") or {}, model=r["model"], provider=r.get("provider") or provider,
                   degraded=r.get("degraded", False), fallback=r.get("fallback"))

def _run_answer(req: AskReq, **extra):
    return rag.answer(req.question, **_ask_kwargs(req), **extra)     # 异常（LLMError / RetrievalError …）由全局处理器映射

@app.post("/ask", response_model=AskResp, tags=["qa"], dependencies=[Depends(auth)], responses={**ERR, 400: {"model": ErrorResp}, 502: {"model": ErrorResp}},
          summary="RAG 问答（检索 → 重排 → 拒答阈值 → LLM → 引用校验）")
async def ask(req: AskReq):
    _check_provider(req.provider)
    await run_in_threadpool(need_models)
    async with SEM:
        r = await run_in_threadpool(_run_answer, req)
    return _to_resp(req.question, r, req.provider)

def _sse(event: str, data) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()

@app.post("/ask/stream", tags=["qa"], dependencies=[Depends(auth)], responses=ERR,
          summary="流式问答（SSE）：event: token（{\"t\": 文本片段}）… 最后 event: done（与 /ask 相同的完整结果）；出错 event: error",
          response_class=StreamingResponse)
async def ask_stream(req: AskReq):
    _check_provider(req.provider)
    await run_in_threadpool(need_models)
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def work():
        try:
            r = _run_answer(req, stream=True, on_token=lambda t: loop.call_soon_threadsafe(q.put_nowait, ("token", {"t": t})))
            loop.call_soon_threadsafe(q.put_nowait, ("done", _to_resp(req.question, r, req.provider).model_dump()))
        except PowerKBError as e:
            kblog.event(log, "request.error", logging.WARNING, code=e.code, status=e.status, path="/ask/stream", message=e.message)
            loop.call_soon_threadsafe(q.put_nowait, ("error", {"code": e.code, "message": e.message, "status": e.status, "request_id": kblog.request_id.get()}))
        except BaseException:                                # noqa：不把内部异常文本发给客户端
            log.exception("stream crashed")
            loop.call_soon_threadsafe(q.put_nowait, ("error", {"code": "internal_error", "message": "服务器内部错误，请凭 request_id 查看服务端日志",
                                                               "status": 500, "request_id": kblog.request_id.get()}))
        loop.call_soon_threadsafe(q.put_nowait, None)

    async def gen():
        async with SEM:
            yield _sse("start", {"question": req.question})
            fut = loop.run_in_executor(None, contextvars.copy_context().run, work)     # request_id 带进线程
            while True:
                item = await q.get()
                if item is None:
                    break
                yield _sse(*item)
            await fut
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---------------- documents ----------------
def _ingest_job(jid: str, path: str, name: str):
    j = JOBS[jid]
    def prog(f, m):
        j.update(progress=round(min(float(f), 1.0), 3), message=m)
    try:
        with WRITE_LOCK:
            j.update(status="running", message="开始入库…")
            res = kb_store.ingest(path, name, progress=prog)
        st = {"ok": "done", "duplicate": "duplicate"}.get(res["status"], "failed")
        j.update(status=st, result=res, message=res["msg"], progress=1.0,
                 error=None if st != "failed" else {"code": "document_empty", "message": res["msg"]})
    except PowerKBError as e:                                 # 解析失败等：任务 failed，服务不受影响
        j.update(status="failed", message=e.message, error={"code": e.code, "message": e.message})
    except Exception as e:
        log.exception("ingest failed")
        j.update(status="failed", message="入库失败（内部错误），请查看服务端日志", error={"code": "internal_error", "message": type(e).__name__})
    finally:
        j["finished"] = time.time()
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        kblog.event(log, "ingest.job", job_id=jid, file=name, status=j["status"], code=(j.get("error") or {}).get("code"),
                    chunks=(j.get("result") or {}).get("chunks"), secs=round(time.time() - j["created"], 1))

@app.post("/documents", response_model=JobResp, status_code=202, tags=["documents"], dependencies=[Depends(auth)],
          responses={**ERR, 413: {"model": ErrorResp}, 415: {"model": ErrorResp}}, summary="上传 PDF/docx，后台异步入库，返回 job_id")
async def upload(file: UploadFile = File(..., description="PDF 或 docx")):
    name = os.path.basename(file.filename or "")
    if not name.lower().endswith((".pdf", ".docx")):
        raise UnsupportedFile("只支持 .pdf / .docx")
    jid = uuid.uuid4().hex[:12]
    d = os.path.join(TMP, jid); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name); size = 0
    with open(path, "wb") as w:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                w.close(); shutil.rmtree(d, ignore_errors=True)
                raise FileTooLarge(f"文件超过 {MAX_UPLOAD // 1024 // 1024} MB 上限")
            w.write(chunk)
    if size == 0:
        shutil.rmtree(d, ignore_errors=True)
        raise BadRequest("空文件", code="empty_file", status=422)
    with open(path, "rb") as f:                                 # 按文件头校验类型（防止改扩展名）
        head = f.read(8)
    if not (head.startswith(b"%PDF") if name.lower().endswith(".pdf") else head.startswith(b"PK\x03\x04")):
        shutil.rmtree(d, ignore_errors=True)
        raise UnsupportedFile("文件内容与扩展名不符（不是有效的 PDF / DOCX）")
    JOBS[jid] = {"job_id": jid, "status": "queued", "progress": 0.0, "message": "排队中", "filename": name, "created": time.time(), "finished": None,
                 "result": None, "error": None}
    INGEST_POOL.submit(contextvars.copy_context().run, _ingest_job, jid, path, name)           # 单线程池：入库串行，且不阻塞事件循环
    return JobResp(**JOBS[jid])

@app.get("/jobs/{job_id}", response_model=JobResp, tags=["documents"], dependencies=[Depends(auth)], responses={**ERR, 404: {"model": ErrorResp}}, summary="入库任务进度")
def job(job_id: str):
    if job_id not in JOBS:
        raise NotFound(f"任务 {job_id} 不存在（服务重启后任务记录会清空）")
    return JobResp(**JOBS[job_id])

@app.get("/documents", response_model=list[Doc], tags=["documents"], dependencies=[Depends(auth)], responses=ERR, summary="库中文档列表")
def documents():
    return [Doc(id=(d["sha256"] if d["deletable"] else "base:" + d["source"]), **{k: d.get(k) for k in Doc.model_fields if k != "id"}) for d in kb_store.list_docs()]

@app.delete("/documents/{doc_id}", tags=["documents"], dependencies=[Depends(auth)], responses={**ERR, 403: {"model": ErrorResp}, 404: {"model": ErrorResp}, 409: {"model": ErrorResp}},
            summary="删除上传的文档（id = sha256 前 12 位或文件名；基础库文档不可删）")
async def delete_document(doc_id: str):
    docs = kb_store.list_docs()
    d = next((x for x in docs if x.get("sha256") == doc_id or x["source"] == doc_id or "base:" + x["source"] == doc_id), None)
    if not d:
        raise NotFound(f"文档 {doc_id} 不存在")
    if not d["deletable"]:
        raise Forbidden("基础库文档不可通过 API 删除")
    if not WRITE_LOCK.acquire(timeout=1):
        raise Busy("有入库任务正在写索引，请稍后重试")
    try:
        r = await run_in_threadpool(kb_store.delete, d["source"])
    finally:
        WRITE_LOCK.release()
    return {"status": r["status"], "message": r["msg"], "source": d["source"]}
