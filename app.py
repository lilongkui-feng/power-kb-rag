# -*- coding: utf-8 -*-
"""电力运维知识库问答（Streamlit 纯前端）—— 所有检索/问答/入库都通过 PowerKB API（api.py）完成，本进程不加载任何模型。
启动：先 deploy/start_api.sh（uvicorn :8000），再 streamlit run app.py --server.port 8501 --server.headless true
环境变量：KB_API_URL（默认 http://127.0.0.1:8000）、KB_API_TOKEN（API 开启鉴权时填写同一个 token）
"""
from __future__ import annotations
import json, os, time
import httpx
import streamlit as st

API = os.environ.get("KB_API_URL", "http://127.0.0.1:8000").rstrip("/")
HDR = {"Authorization": f"Bearer {os.environ['KB_API_TOKEN']}"} if os.environ.get("KB_API_TOKEN") else {}
st.set_page_config(page_title="电力运维知识库问答", page_icon="⚡", layout="wide")
ss = st.session_state
ss.setdefault("messages", [])
ss.setdefault("ingest_log", [])

def api(method: str, path: str, timeout: float = 30, **kw):
    """调用 API；返回 (json 或 None, 错误信息或 None)"""
    try:
        r = httpx.request(method, API + path, headers=HDR, timeout=timeout, **kw)
    except httpx.HTTPError as e:
        return None, f"无法连接 API {API}（{type(e).__name__}）"
    if r.status_code >= 400:
        try:
            e = r.json()["error"]; return None, f"{e['message']}（{e['code']}，HTTP {r.status_code}）"
        except Exception:
            return None, f"HTTP {r.status_code}：{r.text[:200]}"
    return r.json(), None

health, err = api("GET", "/health", timeout=5)
if err:
    st.title("⚡ 电力运维知识库问答")
    st.error(f"后端 API 不可达：{err}")
    st.info("请先启动 API：`deploy/start_api.sh`（或 `uvicorn api:app --port 8000`），首次加载模型约 15 s；"
            "如 API 不在本机，设置环境变量 `KB_API_URL`。")
    if st.button("重试"):
        st.rerun()
    st.stop()
cfg, err = api("GET", "/config", timeout=10)
if err:
    st.error(f"读取 /config 失败：{err}"); st.stop()

# ---------------- 侧栏 ----------------
with st.sidebar:
    st.header("📚 知识库")
    files = st.file_uploader("上传 PDF / docx（可多选）", type=["pdf", "docx"], accept_multiple_files=True)
    if files and st.button(f"入库 {len(files)} 个文件", type="primary"):
        for f in files:
            bar = st.progress(0.0, text=f"{f.name}：上传…")
            j, e = api("POST", "/documents", timeout=300, files={"file": (f.name, f.getvalue())})
            if e:
                ss.ingest_log.append((f.name, "error", e)); bar.empty(); continue
            while j["status"] in ("queued", "running"):        # 轮询任务进度
                time.sleep(1.5)
                j2, e = api("GET", f"/jobs/{j['job_id']}")
                if e:
                    break
                j = j2
                bar.progress(min(j["progress"], 1.0), text=f"{f.name}：{j['message']}")
            bar.empty()
            ss.ingest_log.append((f.name, {"done": "ok"}.get(j["status"], j["status"]), e or j["message"]))
    for name, status, msg in ss.ingest_log[-6:]:
        (st.success if status == "ok" else st.warning if status == "duplicate" else st.error)(f"{name}：{msg}")

    docs, e = api("GET", "/documents")
    docs = docs or []
    up = [d for d in docs if d["deletable"]]
    with st.expander(f"库中文档：{len(docs)} 份 / {sum(d['chunks'] for d in docs)} 块（上传 {len(up)} 份）", expanded=False):
        for d in docs:
            c1, c2 = st.columns([5, 1])
            c1.caption(f"{'🆕' if d['deletable'] else '📄'} {d['source']} · {d['chunks']} 块")
            if d["deletable"] and c2.button("🗑", key="del_" + d["id"], help="删除该上传文档"):
                r, e = api("DELETE", f"/documents/{d['id']}", timeout=120)
                st.toast(e or r["message"]); st.rerun()

    st.header("⚙️ 检索与生成")
    dft = cfg["defaults"]
    use_rerank = st.toggle("重排（bge-reranker-v2-m3，CPU 约 +4 s）", value=dft["rerank"])
    top_k = st.slider("Top-k（送入大模型的资料条数）", 2, 8, dft["top_k"])
    expand = st.selectbox("上下文扩展", ["none", "neighbor", "parent"], index=["none", "neighbor", "parent"].index(dft["expand"]),
                          format_func={"none": "不扩展（推荐）", "neighbor": "相邻块", "parent": "父条款/整节（≤2000 字）"}.get)
    use_th = st.toggle("拒答阈值（重排 Top-1 分过低直接拒答，不调用大模型）", value=dft["refuse_below"] is not None)
    th = st.slider("阈值", 0.05, 0.9, dft["refuse_below"] or dft["recommended_refuse_below"], 0.05, disabled=not (use_th and use_rerank))
    sel = st.multiselect("只在这些文档中检索（留空=全部）", [d["source"] for d in docs])
    pinfo = {p["name"]: p for p in cfg["providers"]}
    labels = {"local": "本地 ollama · qwen2.5:3b-instruct", "siliconflow": "硅基流动 · DeepSeek-V3", "siliconflow:qwen72b": "硅基流动 · Qwen2.5-72B-Instruct",
              "deepseek": "DeepSeek", "openai": "OpenAI", "xai": "xAI"}
    choice = st.selectbox("LLM 提供方", [k for k in labels if k.split(":")[0] in pinfo], format_func=labels.get)
    provider = choice.split(":")[0]
    model_override = {"siliconflow:qwen72b": "Qwen/Qwen2.5-72B-Instruct"}.get(choice)
    p = pinfo[provider]
    ok = p["ready"]
    info = p["info"].split(" · ")[0] + " · " + model_override if (model_override and ok) else p["info"]
    (st.caption if ok else st.error)(("✅ " if ok else "⚠️ ") + info + ("" if ok else "（key 需在 API 服务端的环境变量中配置）"))
    if ok:
        st.caption(f"默认 Prompt {p['default_prompt']} · 跨语言检索 {p['default_xlang']}")
    if st.button("清空对话"):
        ss.messages = []; st.rerun()
    r = cfg["retrieval"]
    st.caption(f"API {API} · {health['status']} · 模型加载 {health['load_secs']}s · {r['collection']} + hybrid(α={r['alpha']})"
               + (f" + 重排 Top-{r['rerank_top_n']} β={r['rerank_beta']}" if use_rerank else ""))

# ---------------- 主区 ----------------
st.title("⚡ 电力运维知识库问答")
st.caption("回答只依据库内资料，并以 [n] 标注出处；资料不足时会拒答。本地 3B 模型仅用于联调，答案请以原文为准。")

def show_details(r: dict):
    t = r["timing"]
    with st.expander(f"📎 出处 {len(r['citations'])} 条 · 耗时 {t['total_secs']}s"):
        if r["citations"]:
            for s in r["citations"]:
                rs = f"，重排分 {s['rerank_score']:.3f}" if s.get("rerank_score") is not None else ""
                sc = f"分数 {s['score']:.3f}" if s.get("score") is not None else ""
                st.markdown(f"**[{s['id']}] {s['source']}**  \n章节：{s['section']} ｜ 页码：p{s['pages']} ｜ {sc}{rs}")
                st.markdown(f"> {s['excerpt']}")
        else:
            st.info("无出处（已拒答）" if r["refused"] else "回答未标注引用，请谨慎采信")
        for w in r.get("warnings", []):
            st.warning("引用校验：" + w)
        st.caption(f"检索 {t['retrieval_secs']}s ｜ 重排 {t['rerank_secs']}s ｜ 生成 {t['generation_secs']}s"
                   f"（首 token {t.get('first_token_secs')}s）｜ 总计 {t['total_secs']}s ｜ 模型 {r['model']}（经 API）")
        st.dataframe([{"#": h["rank"], "文件": h["source"], "章节": h["section"], "页": h["page_start"],
                       "分数": round(h["score"], 3) if h.get("score") is not None else None, "重排分": h["rerank_score"]} for h in r["retrieved"]],
                     hide_index=True, use_container_width=True)

def ask_stream(body: dict, ph):
    """POST /ask/stream，解析 SSE：token 事件逐段显示，done 事件返回完整结果"""
    acc, ev, result = "", None, None
    with httpx.stream("POST", API + "/ask/stream", json=body, headers=HDR, timeout=httpx.Timeout(600, connect=5)) as resp:
        if resp.status_code >= 400:
            resp.read()
            try:
                e = resp.json()["error"]; raise RuntimeError(f"{e['message']}（{e['code']}）")
            except (ValueError, KeyError):
                raise RuntimeError(f"HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
                if ev == "token":
                    acc += data["t"]; ph.markdown(acc + "▌")
                elif ev == "done":
                    result = data
                elif ev == "error":
                    raise RuntimeError(f"{data['message']}（{data['code']}）")
    return result

for m in ss.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("result"):
            show_details(m["result"])

q = st.chat_input("输入问题，例如：阀控蓄电池多久做一次核对性放电？")
if q:
    ss.messages.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        if not ok:
            st.error(info); ss.messages.append({"role": "assistant", "content": f"⚠️ {info}"}); st.stop()
        body = {"question": q, "provider": provider, "model": model_override, "top_k": top_k, "rerank": use_rerank, "expand": expand,
                "refuse_below": (th if (use_th and use_rerank) else None), "sources": sel or None}
        ph = st.empty()
        try:
            with st.spinner("检索、重排中…（经 API）"):
                r = ask_stream(body, ph)
        except (httpx.HTTPError, RuntimeError) as e:
            ph.empty(); st.error(f"出错：{e}"); ss.messages.append({"role": "assistant", "content": f"出错：{e}"}); st.stop()
        ph.empty()
        st.markdown(r["answer"])
        show_details(r)
        ss.messages.append({"role": "assistant", "content": r["answer"], "result": r})
