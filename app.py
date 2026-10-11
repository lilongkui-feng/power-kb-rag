# -*- coding: utf-8 -*-
"""电力运维知识库问答（Streamlit）
启动：streamlit run app.py --server.port 8501 --server.headless true
侧栏：上传 PDF/docx 入库（解析+自动 OCR(PaddleOCR PP-StructureV3) + 表格结构化 → heading_v2 切分（正文+表格父子块） → Chroma + BM25 增量）、文档列表/删除、检索参数、LLM 提供方
主区：聊天式提问，流式回答，展开查看出处与耗时
"""
from __future__ import annotations
import os, queue, tempfile, threading, time
import streamlit as st

os.environ.setdefault("HF_HOME", "/workspace/hf_cache")
st.set_page_config(page_title="电力运维知识库问答", page_icon="⚡", layout="wide")

import kb_store, rag

@st.cache_resource(show_spinner="首次加载 bge-m3 / bge-reranker-v2-m3 / BM25 索引（约 15 s）…")
def load_models():
    from embed_index import get_model
    import rerank, bm25_index
    get_model(); rerank.get_reranker(); bm25_index.load(kb_store.METHOD)
    return time.strftime("%H:%M:%S")

loaded_at = load_models()
ss = st.session_state
ss.setdefault("messages", [])
ss.setdefault("ingest_log", [])

# ---------------- 侧栏 ----------------
with st.sidebar:
    st.header("📚 知识库")
    files = st.file_uploader("上传 PDF / docx（可多选）", type=["pdf", "docx"], accept_multiple_files=True)
    if files and st.button(f"入库 {len(files)} 个文件", type="primary"):
        for f in files:
            bar = st.progress(0.0, text=f"{f.name}：准备…")
            with tempfile.TemporaryDirectory() as td:
                p = os.path.join(td, f.name)
                with open(p, "wb") as w:
                    w.write(f.getbuffer())
                try:
                    res = kb_store.ingest(p, f.name, progress=lambda fr, m, n=f.name: bar.progress(min(fr, 1.0), text=f"{n}：{m}"))
                except Exception as e:                     # noqa
                    res = {"status": "error", "msg": f"失败：{e}"}
            bar.empty()
            ss.ingest_log.append((f.name, res["status"], res["msg"]))
    for name, status, msg in ss.ingest_log[-6:]:
        (st.success if status == "ok" else st.warning if status == "duplicate" else st.error)(f"{name}：{msg}")

    docs = kb_store.list_docs()
    up = [d for d in docs if d["deletable"]]
    total = sum(d["chunks"] for d in docs)
    with st.expander(f"库中文档：{len(docs)} 份 / {total} 块（上传 {len(up)} 份）", expanded=False):
        for d in docs:
            c1, c2 = st.columns([5, 1])
            c1.caption(f"{'🆕' if d['deletable'] else '📄'} {d['source']} · {d['chunks']} 块")
            if d["deletable"] and c2.button("🗑", key="del_" + d["source"], help="删除该上传文档"):
                st.toast(kb_store.delete(d["source"])["msg"]); st.rerun()

    st.header("⚙️ 检索与生成")
    use_rerank = st.toggle("重排（bge-reranker-v2-m3，CPU 约 +4 s）", value=True)
    top_k = st.slider("Top-k（送入大模型的资料条数）", 2, 8, 5)
    expand = st.selectbox("上下文扩展", ["none", "neighbor", "parent"], index=["none", "neighbor", "parent"].index(rag.DEFAULT_EXPAND),
                          format_func={"none": "不扩展（推荐）", "neighbor": "相邻块", "parent": "父条款/整节（≤2000 字）"}.get)
    use_th = st.toggle("拒答阈值（重排 Top-1 分过低直接拒答，不调用大模型）", value=rag.DEFAULT_REFUSE_BELOW is not None)
    th = st.slider("阈值", 0.05, 0.9, rag.DEFAULT_REFUSE_BELOW or rag.RECOMMENDED_REFUSE_BELOW, 0.05, disabled=not (use_th and use_rerank))
    sel = st.multiselect("只在这些文档中检索（留空=全部）", [d["source"] for d in docs])
    labels = {"local": "本地 ollama · qwen2.5:3b-instruct",
              "siliconflow": "硅基流动 · DeepSeek-V3（SILICONFLOW_API_KEY）", "siliconflow:qwen72b": "硅基流动 · Qwen2.5-72B-Instruct", "deepseek": "DeepSeek（DEEPSEEK_API_KEY）",
              "openai": "OpenAI（OPENAI_API_KEY）", "xai": "xAI（XAI_API_KEY）"}
    provider = st.selectbox("LLM 提供方", list(labels), format_func=labels.get)
    model_override = {"siliconflow:qwen72b": "Qwen/Qwen2.5-72B-Instruct"}.get(provider)
    provider = provider.split(":")[0]
    ok, info = rag.provider_ready(provider)
    if model_override and ok:
        info = info.split(" · ")[0] + " · " + model_override
    (st.caption if ok else st.error)(("✅ " if ok else "⚠️ ") + info)
    if st.button("清空对话"):
        ss.messages = []; st.rerun()
    st.caption(f"模型已加载（{loaded_at}）· 检索：{kb_store.METHOD} + hybrid(α=0.5)" + (" + 重排 Top-20 β=0.8" if use_rerank else ""))

# ---------------- 主区 ----------------
st.title("⚡ 电力运维知识库问答")
st.caption("回答只依据库内资料，并以 [n] 标注出处；资料不足时会拒答。本地 3B 模型仅用于联调，答案请以原文为准。")

def show_details(r: dict):
    t = r["timing"]
    with st.expander(f"📎 出处 {len(r['sources'])} 条 · 耗时 {t['total_secs']}s"):
        if r["sources"]:
            for s in r["sources"]:
                rs = f"，重排分 {s['rerank_score']:.3f}" if s.get("rerank_score") is not None else ""
                st.markdown(f"**[{s['id']}] {s['source']}**  \n章节：{s['section']} ｜ 页码：p{s['pages']} ｜ 分数 {s['score']:.3f}{rs}")
                st.markdown(f"> {s['excerpt']}")
        else:
            st.info("无出处（已拒答）" if r["refused"] else "回答未标注引用，请谨慎采信")
        for w in r.get("support_warnings", []):
            st.warning("引用校验：" + w)
        st.caption(f"检索 {t['retrieval_secs']}s ｜ 重排 {t['rerank_secs']}s ｜ 生成 {t['generation_secs']}s"
                   f"（首 token {t.get('first_token_secs')}s）｜ 总计 {t['total_secs']}s ｜ 模型 {r['model']}")
        st.dataframe([{"#": h["rank"], "文件": h["source"], "章节": h["section"], "页": h["page_start"],
                       "分数": round(h["score"], 3), "重排分": h["rerank_score"]} for h in r["retrieved"]],
                     hide_index=True, use_container_width=True)

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
        qu, box = queue.Queue(), {}
        filters = {"source": {"$in": sel}} if sel else None
        def work():
            try:
                box["r"] = rag.answer(q, k=top_k, rerank=use_rerank, provider=provider, model=model_override, stream=True,
                                      expand=expand, refuse_below=(th if (use_th and use_rerank) else None), search_kw={"collection": kb_store.METHOD},
                                      on_token=qu.put, filters=filters)
            except BaseException as e:                   # noqa（含 SystemExit）
                box["e"] = e
            qu.put(None)
        threading.Thread(target=work, daemon=True).start()
        with st.spinner("检索、重排中…"):
            first = qu.get()                             # 第一个 token 到达前显示 spinner
        if first is not None:
            ph, acc = st.empty(), first
            ph.markdown(acc + "▌")
            for tok in iter(qu.get, None):               # 流式显示
                acc += tok
                ph.markdown(acc + "▌")
            ph.empty()
        if "e" in box:
            st.error(f"出错：{box['e']}"); ss.messages.append({"role": "assistant", "content": f"出错：{box['e']}"}); st.stop()
        r = box["r"]
        st.markdown(r["answer"])
        show_details(r)
        ss.messages.append({"role": "assistant", "content": r["answer"], "result": r})
