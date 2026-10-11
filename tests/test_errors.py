# 异常体系：LLM 超时 / 429 / 401 / 5xx（httpx.MockTransport 模拟，不调真实云端）、重试退避、降级；API 全局异常映射与统一错误体
import json, os, sys, time
import httpx, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["KB_PRELOAD"] = "0"
import config
config.reload_settings()
import errors, rag

FAKE_KEY = "sk-fake-for-tests-0000111122223333"
HITS = [{"rank": 1, "chunk_id": "c1", "source": "DL_T_724.pdf", "heading_path": "7.4.1.2 核对性放电周期", "page_start": 20, "page_end": 20,
         "score": 0.99, "rerank_score": 0.99, "text": "新安装的阀控蓄电池组应进行全容量核对性放电试验，以后每2年至少进行一次。",
         "metadata": {"source": "DL_T_724.pdf", "heading_path": "7.4.1.2 核对性放电周期", "page_start": 20, "page_end": 20, "chunk_type": "text"}}]

@pytest.fixture
def llm(monkeypatch):
    """把 rag 内部的 httpx.Client 换成 MockTransport；handler 按 host 返回预设响应"""
    calls = []
    routes = {}
    def handler(req: httpx.Request):
        calls.append(req.url.host)
        r = routes.get(req.url.host, routes.get("*"))
        return r(req) if callable(r) else r
    real = httpx.Client
    monkeypatch.setattr(rag.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("SILICONFLOW_API_KEY", FAKE_KEY)
    monkeypatch.setenv("LLM_BACKOFF_BASE", "0"); monkeypatch.setenv("LLM_MAX_RETRIES", "2"); monkeypatch.setenv("LLM_TIMEOUT_RETRIES", "1")
    config.reload_settings()
    yield routes, calls
    config.reload_settings()

def ok(text="每2年至少进行一次核对性放电试验。[1]"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

def timeout(req):
    raise httpx.ReadTimeout("read timeout", request=req)

def cfg():
    return rag.llm_config("siliconflow")

MSG = [{"role": "user", "content": "hi"}]

def test_success_usage(llm):
    routes, calls = llm; routes["*"] = ok()
    text, info = rag.call_llm(MSG, cfg())
    assert "2年" in text and info["usage"]["total_tokens"] == 15 and info["attempts"] == 1

def test_401_auth_no_retry(llm):
    routes, calls = llm; routes["*"] = httpx.Response(401, json={"error": "bad key"})
    with pytest.raises(errors.LLMAuthError) as ei:
        rag.call_llm(MSG, cfg())
    assert len(calls) == 1 and ei.value.status == 502 and ei.value.code == "llm_auth_failed" and FAKE_KEY not in ei.value.message

def test_429_retry_then_success(llm):
    routes, calls = llm
    seq = iter([httpx.Response(429, headers={"retry-after": "0"}), httpx.Response(429), ok()])
    routes["*"] = lambda req: next(seq)
    text, info = rag.call_llm(MSG, cfg())
    assert len(calls) == 3 and info["attempts"] == 3

def test_429_exhausted(llm):
    routes, calls = llm; routes["*"] = httpx.Response(429)
    with pytest.raises(errors.LLMRateLimited) as ei:
        rag.call_llm(MSG, cfg())
    assert len(calls) == 3 and ei.value.status == 429                  # 1 次 + LLM_MAX_RETRIES=2

def test_timeout_retried_once(llm):
    routes, calls = llm; routes["*"] = timeout
    with pytest.raises(errors.LLMTimeout) as ei:
        rag.call_llm(MSG, cfg())
    assert len(calls) == 2 and ei.value.status == 504                  # LLM_TIMEOUT_RETRIES=1

def test_5xx_and_connect_error(llm):
    routes, calls = llm; routes["*"] = httpx.Response(503)
    with pytest.raises(errors.LLMUnavailable):
        rag.call_llm(MSG, cfg())
    def conn(req):
        raise httpx.ConnectError("refused", request=req)
    routes["*"] = conn
    with pytest.raises(errors.LLMUnavailable, match="无法连接"):
        rag.call_llm(MSG, cfg())

def test_400_and_bad_json(llm):
    routes, _ = llm; routes["*"] = httpx.Response(400)
    with pytest.raises(errors.LLMError) as ei:
        rag.call_llm(MSG, cfg())
    assert ei.value.code == "llm_error"
    routes["*"] = httpx.Response(200, json={"oops": 1})
    with pytest.raises(errors.LLMError, match="格式异常"):
        rag.call_llm(MSG, cfg())

def test_stream_parse(llm):
    routes, _ = llm
    body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in ["每2年", "一次。", "[1]"]) + "data: [DONE]\n\n"
    routes["*"] = httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    got = []
    text, info = rag.call_llm(MSG, cfg(), stream=True, on_token=got.append)
    assert text == "每2年一次。[1]" and got == ["每2年", "一次。", "[1]"] and info["first_token_secs"] is not None

def test_provider_not_ready(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False); config.reload_settings()
    with pytest.raises(errors.ProviderNotReady) as ei:
        rag.llm_config("deepseek")
    assert ei.value.status == 400
    with pytest.raises(errors.ProviderNotReady, match="未知"):
        rag.llm_config("nope")

# ---------------- 降级 ----------------
def _ans(**kw):
    return rag.answer("新安装的阀控蓄电池多久核对性放电？", k=1, provider="siliconflow", hits=HITS, refuse_below=None, **kw)

def test_fallback_retrieval_only(llm, monkeypatch):
    routes, _ = llm; routes["*"] = httpx.Response(503)
    monkeypatch.setenv("LLM_FALLBACK", "retrieval"); config.reload_settings()
    r = _ans()
    assert r["degraded"] and r["fallback"]["to"] == "retrieval_only" and r["error"]["code"] == "llm_unavailable"
    assert r["sources"][0]["source"] == "DL_T_724.pdf" and "检索到的最相关资料" in r["answer"] and not r["refused"]

def test_fallback_local(llm, monkeypatch):
    routes, calls = llm
    routes["api.siliconflow.cn"] = httpx.Response(401); routes["127.0.0.1"] = ok()
    monkeypatch.setenv("LLM_FALLBACK", "local"); config.reload_settings()
    r = _ans()
    assert r["fallback"]["to"] == "local" and r["fallback"]["reason"] == "llm_auth_failed" and r["provider"] == "local"
    assert r["sources"] and r["sources"][0]["id"] == 1 and any("本地模型" in w for w in r["support_warnings"])
    assert calls[0] == "api.siliconflow.cn" and calls[-1] == "127.0.0.1"

def test_fallback_local_then_retrieval(llm, monkeypatch):
    routes, _ = llm; routes["api.siliconflow.cn"] = httpx.Response(429); routes["127.0.0.1"] = timeout
    monkeypatch.setenv("LLM_FALLBACK", "local_then_retrieval"); config.reload_settings()
    r = _ans()
    assert r["degraded"] and r["error"]["code"] == "llm_timeout"

def test_fallback_none_raises(llm, monkeypatch):
    routes, _ = llm; routes["*"] = timeout
    monkeypatch.setenv("LLM_FALLBACK", "none"); config.reload_settings()
    with pytest.raises(errors.LLMTimeout):
        _ans()

# ---------------- API 映射（TestClient，不加载模型） ----------------
@pytest.fixture
def client(monkeypatch):
    import api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api, "need_models", lambda: None)
    with TestClient(api.app, raise_server_exceptions=False) as c:
        yield c, api

@pytest.mark.parametrize("exc,status,code", [
    (errors.LLMTimeout(), 504, "llm_timeout"), (errors.LLMRateLimited(), 429, "llm_rate_limited"),
    (errors.LLMAuthError(), 502, "llm_auth_failed"), (errors.LLMUnavailable(), 503, "llm_unavailable"), (errors.LLMError(), 502, "llm_error"),
    (errors.IndexNotReady(), 503, "index_not_ready"), (errors.RetrievalError(), 500, "retrieval_error"),
    (errors.ProviderNotReady("x"), 400, "provider_not_ready"), (errors.ConfigError(), 500, "config_error"),
])
def test_api_error_mapping(client, monkeypatch, exc, status, code):
    c, api = client
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(api.rag, "answer", boom)
    r = c.post("/ask", json={"question": "测试", "provider": "local"}, headers={"X-Request-ID": "rid-map-1"})
    assert r.status_code == status
    e = r.json()["error"]
    assert e["code"] == code and e["request_id"] == "rid-map-1" and r.headers["X-Request-ID"] == "rid-map-1" and e["message"]

def test_api_unhandled_no_leak(client, monkeypatch):
    c, api = client
    def boom(*a, **k):
        raise RuntimeError(f"db password=hunter22 key {FAKE_KEY} at /secret/path.py line 3")
    monkeypatch.setattr(api.rag, "answer", boom)
    r = c.post("/ask", json={"question": "测试", "provider": "local"})
    assert r.status_code == 500
    body = r.text
    assert r.json()["error"]["code"] == "internal_error" and "hunter22" not in body and FAKE_KEY not in body and "Traceback" not in body
    assert r.json()["error"]["request_id"] not in ("-", None)

def test_api_stream_error_event(client, monkeypatch):
    c, api = client
    def boom(*a, **k):
        raise errors.LLMRateLimited()
    monkeypatch.setattr(api.rag, "answer", boom)
    with c.stream("POST", "/ask/stream", json={"question": "测试", "provider": "local"}) as r:
        lines = list(r.iter_lines())
    ev = [l for l in lines if l.startswith("event:")]
    data = json.loads([l for l in lines if l.startswith("data:")][-1][5:])
    assert ev[-1] == "event: error" and data["code"] == "llm_rate_limited" and data["status"] == 429 and data["request_id"]

def test_api_degraded_passthrough(client, monkeypatch, llm):
    c, api = client
    routes, _ = llm; routes["*"] = httpx.Response(503)
    monkeypatch.setenv("LLM_FALLBACK", "retrieval"); config.reload_settings()
    orig = rag.answer
    monkeypatch.setattr(api.rag, "answer", lambda q, **kw: orig(q, k=1, provider="siliconflow", hits=HITS, refuse_below=None))
    j = c.post("/ask", json={"question": "测试", "provider": "local"}).json()
    assert j["degraded"] is True and j["fallback"]["to"] == "retrieval_only" and j["citations"]

def test_api_upload_failed_job(client, monkeypatch):
    c, api = client
    def bad(path, name, progress=None):
        raise errors.DocumentParseError(f"《{name}》解析失败（FileDataError）")
    monkeypatch.setattr(api.kb_store, "ingest", bad)
    j = c.post("/documents", files={"file": ("bad.pdf", b"%PDF-1.4 broken", "application/pdf")}).json()
    for _ in range(50):
        s = c.get(f"/jobs/{j['job_id']}").json()
        if s["status"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert s["status"] == "failed" and s["error"]["code"] == "document_parse_error"
    assert c.get("/health").status_code == 200                                     # 服务不受影响

def test_api_upload_magic_mismatch(client):
    c, _ = client
    r = c.post("/documents", files={"file": ("fake.pdf", b"hello not a pdf", "application/pdf")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_type"

def test_api_auth_token_from_env(client, monkeypatch):
    c, api = client
    monkeypatch.setenv("KB_API_TOKEN", "tok-test-123456"); config.reload_settings()
    r = c.get("/config")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert c.get("/config", headers={"Authorization": "Bearer tok-test-123456"}).status_code == 200
    monkeypatch.delenv("KB_API_TOKEN"); config.reload_settings()
