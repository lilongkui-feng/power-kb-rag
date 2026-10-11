# API 集成测试：python -m pytest tests/test_api.py -v
# 需要已启动的服务（deploy/start_api.sh，默认 http://127.0.0.1:8000）和本地 ollama；云端端到端用 KB_TEST_CLOUD=1 开启（只调 1 次）
# 另起一个 :8011 实例（KB_API_TOKEN=testtoken、KB_PRELOAD=0、KB_MAX_UPLOAD_MB=1）测鉴权与大小限制
import json, os, subprocess, sys, time
import httpx, pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("KB_TEST_API", "http://127.0.0.1:8000")
AUTH_PORT = 8011

def _up(url, t=60):
    for _ in range(t):
        try:
            if httpx.get(url + "/health", timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return False

@pytest.fixture(scope="session")
def c():
    if not _up(API, 5):
        pytest.skip(f"API {API} 未启动（deploy/start_api.sh）")
    with httpx.Client(base_url=API, timeout=300) as cl:
        yield cl

@pytest.fixture(scope="session")
def authsrv():
    env = dict(os.environ, KB_API_TOKEN="testtoken", KB_PRELOAD="0", KB_MAX_UPLOAD_MB="1")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--port", str(AUTH_PORT)], cwd=HERE, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{AUTH_PORT}"
    assert _up(url, 60), "鉴权测试实例未启动"
    yield url
    p.terminate(); p.wait(10)

def _pdf(path, title):
    import fitz
    d = fitz.open(); pg = d.new_page()
    pg.insert_text((72, 72), "1 Test Device XK-900 Maintenance", fontsize=14)
    pg.insert_text((72, 110), f"{title}: the XK-900 test relay must be inspected every 7 months.", fontsize=11)
    pg.insert_text((72, 130), "The XK-900 battery voltage shall not be lower than 21.5 V.", fontsize=11)
    d.save(path)

def _err(r, code):
    j = r.json(); assert "error" in j and j["error"]["code"] == code, j; return j

# ---------------- system ----------------
def test_health(c):
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["models_loaded"] and h["chroma_count"] > 1000 and h["bm25_docs"] == h["chroma_count"]

def test_config_no_keys(c):
    r = c.get("/config"); j = r.json()
    names = {p["name"] for p in j["providers"]}
    assert {"local", "siliconflow"} <= names and j["defaults"]["top_k"] == 5
    key = os.environ.get("SILICONFLOW_API_KEY")
    if key:
        assert key not in r.text                        # 绝不返回 key

def test_openapi(c):
    o = c.get("/openapi.json").json()
    for p in ("/health", "/config", "/search", "/ask", "/ask/stream", "/documents", "/jobs/{job_id}", "/documents/{doc_id}"):
        assert p in o["paths"], p
    assert "AskReq" in o["components"]["schemas"] and "ErrorResp" in o["components"]["schemas"]

# ---------------- retrieval ----------------
def test_search(c):
    r = c.post("/search", json={"query": "运行中SF6设备灭弧气室湿度限值", "top_k": 3})
    j = r.json(); assert r.status_code == 200 and len(j["hits"]) == 3
    h = j["hits"][0]
    assert h["rerank_score"] is not None and h["text"] and h["chunk_id"]
    assert any("SF6" in x["text"] or "SF₆" in x["text"] for x in j["hits"])
    assert r.headers.get("X-Request-ID")

def test_search_filter_norerank(c):
    src = "ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf"
    j = c.post("/search", json={"query": "inspection interval", "top_k": 4, "rerank": False, "sources": [src], "include_text": False}).json()
    assert all(h["source"] == src for h in j["hits"]) and all(h["text"] is None and h["rerank_score"] is None for h in j["hits"])

def test_validation_error(c):
    _err(c.post("/search", json={"query": "", "top_k": 99}), "validation_error")
    _err(c.post("/ask", json={"question": "x", "provider": "nope"}), "validation_error")

def test_provider_not_ready(c):
    if os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("本机配置了 DEEPSEEK_API_KEY")
    r = c.post("/ask", json={"question": "测试", "provider": "deepseek"})
    assert r.status_code == 400; _err(r, "provider_not_ready")

# ---------------- qa（本地 ollama，不调云端） ----------------
def test_ask_local(c):
    r = c.post("/ask", json={"question": "阀控蓄电池组新安装后多久做一次核对性放电？", "provider": "local", "top_k": 4})
    j = r.json(); assert r.status_code == 200, j
    assert j["answer"] and not j["refused"] and j["citations"] and j["timing"]["total_secs"] > 0
    assert all(1 <= ci["id"] <= 4 for ci in j["citations"])

def test_ask_threshold_refuse(c):
    j = c.post("/ask", json={"question": "如何烤制法式可颂面包？", "provider": "local"}).json()
    assert j["refused"] and j["threshold_refused"] and j["citations"] == []

def test_ask_stream_local(c):
    events, toks = [], ""
    with c.stream("POST", "/ask/stream", json={"question": "SafeRing压力表指针在红区时怎么办？", "provider": "local", "top_k": 3}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        ev = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                ev = line[6:].strip(); events.append(ev)
            elif line.startswith("data:") and ev == "token":
                toks += json.loads(line[5:])["t"]
            elif line.startswith("data:") and ev == "done":
                done = json.loads(line[5:])
    assert events[0] == "start" and "token" in events and events[-1] == "done"
    assert done["answer"] and toks.strip()

@pytest.mark.skipif(os.environ.get("KB_TEST_CLOUD") != "1", reason="云端端到端默认不跑（KB_TEST_CLOUD=1 开启，调用 1 次硅基流动）")
def test_ask_cloud_once(c):
    j = c.post("/ask", json={"question": "运行中SF6设备灭弧气室的湿度限值是多少？", "provider": "siliconflow"}).json()
    assert "300" in j["answer"] and j["citations"] and j["usage"].get("total_tokens")

# ---------------- documents ----------------
def test_upload_progress_list_delete(c, tmp_path):
    name = f"apitest_{int(time.time())}.pdf"; p = tmp_path / name; _pdf(str(p), name)
    r = c.post("/documents", files={"file": (name, p.read_bytes(), "application/pdf")})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]; seen = set()
    for _ in range(240):
        j = c.get(f"/jobs/{jid}").json(); seen.add(j["status"])
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(1)
    assert j["status"] == "done", j
    assert j["result"]["chunks"] >= 1 and j["progress"] == 1.0
    docs = c.get("/documents").json()
    d = next(x for x in docs if x["source"] == name); assert d["deletable"] and d["id"]
    hits = c.post("/search", json={"query": "XK-900 test relay inspection months", "top_k": 3, "sources": [name]}).json()["hits"]
    assert hits and hits[0]["source"] == name
    # 重复上传 → duplicate
    r2 = c.post("/documents", files={"file": (name, p.read_bytes(), "application/pdf")}).json()
    for _ in range(60):
        j2 = c.get(f"/jobs/{r2['job_id']}").json()
        if j2["status"] not in ("queued", "running"):
            break
        time.sleep(1)
    assert j2["status"] == "duplicate"
    r3 = c.delete(f"/documents/{d['id']}"); assert r3.status_code == 200 and r3.json()["status"] == "ok"
    assert all(x["source"] != name for x in c.get("/documents").json())

def test_documents_errors(c):
    _err(c.post("/documents", files={"file": ("a.txt", b"hello", "text/plain")}), "unsupported_type")
    _err(c.get("/jobs/doesnotexist"), "not_found")
    _err(c.delete("/documents/nope123"), "not_found")
    base = next(d for d in c.get("/documents").json() if not d["deletable"])
    r = c.delete(f"/documents/{base['id']}"); assert r.status_code == 403; _err(r, "forbidden")

# ---------------- 鉴权 / 大小限制（独立实例） ----------------
def test_auth(authsrv):
    assert httpx.get(authsrv + "/health").status_code == 200           # health 不鉴权
    r = httpx.get(authsrv + "/config"); assert r.status_code == 401; _err(r, "unauthorized")
    assert httpx.get(authsrv + "/config", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert httpx.get(authsrv + "/config", headers={"Authorization": "Bearer testtoken"}).status_code == 200
    assert httpx.get(authsrv + "/config", headers={"X-API-Key": "testtoken"}).json()["auth_enabled"] is True

def test_upload_too_large(authsrv):
    r = httpx.post(authsrv + "/documents", headers={"X-API-Key": "testtoken"}, timeout=60,
                   files={"file": ("big.pdf", b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10), "application/pdf")})
    assert r.status_code == 413; _err(r, "payload_too_large")

def test_corrupt_pdf_job_failed_service_ok(c):
    """损坏 PDF：任务进入 failed（document_parse_error），服务与知识库不受影响"""
    before = c.get("/health").json()["documents"]
    data = b"%PDF-1.7\n1 0 obj << /Type /Catalog >>\n" + os.urandom(2000)          # 有 PDF 头但结构损坏
    r = c.post("/documents", files={"file": (f"corrupt_{int(time.time())}.pdf", data, "application/pdf")})
    assert r.status_code == 202, r.text
    for _ in range(120):
        j = c.get(f"/jobs/{r.json()['job_id']}").json()
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    assert j["status"] == "failed" and j["error"]["code"] in ("document_parse_error", "document_empty"), j
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["documents"] == before

def test_error_body_has_request_id(c):
    r = c.get("/jobs/doesnotexist", headers={"X-Request-ID": "rid-live-404"})
    e = r.json()["error"]
    assert r.status_code == 404 and e["code"] == "not_found" and e["request_id"] == "rid-live-404" and r.headers["x-request-id"] == "rid-live-404"
