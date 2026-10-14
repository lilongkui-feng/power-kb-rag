# -*- coding: utf-8 -*-
"""完整 RAG：检索（heading + hybrid α=0.5 + bge-reranker-v2-m3 重排）→ 组装 Prompt → LLM → 回答 + 出处

用法：
  python rag.py "阀控蓄电池多久做一次核对性放电？"            # 默认本地 ollama（qwen2.5:3b-instruct）
  python rag.py "..." --stream                                # 流式输出
  python rag.py "..." -k 4 --no-rerank --json
  python rag.py "..." --provider deepseek                     # 读取 DEEPSEEK_API_KEY（https://api.deepseek.com，deepseek-chat）
  python rag.py "..." --provider openai                       # 读取 OPENAI_API_KEY（https://api.openai.com/v1，OPENAI_MODEL 默认 gpt-4o-mini）
  python rag.py "..." --provider xai                          # 读取 XAI_API_KEY（https://api.x.ai/v1，XAI_MODEL 默认 grok-3-mini）
LLM 配置（环境变量，OpenAI 兼容 /chat/completions）：
  LLM_BASE_URL  默认 http://127.0.0.1:11434/v1（ollama）
  LLM_MODEL     默认 qwen2.5:3b-instruct
  LLM_API_KEY   默认 ollama（本地不校验）
  DeepSeek 示例：export LLM_BASE_URL=https://api.deepseek.com LLM_MODEL=deepseek-chat LLM_API_KEY=$DEEPSEEK_API_KEY
"""
from __future__ import annotations
import argparse, json, os, re, sys, time
import httpx

from config import settings, secret
from errors import (PowerKBError, ProviderNotReady, LLMError, LLMTimeout, LLMRateLimited, LLMAuthError, LLMUnavailable,
                    RetrievalError, IndexNotReady)
from kblog import get_logger, event, q_repr
import logging
log = get_logger("powerkb.rag")

# provider 静态信息；模型名 / 本地地址来自 config（config.yaml / 环境变量），key 只从环境变量 / .env 读
_PROVIDER_DEF = {
    "local": (None, "local_llm_model", None),
    "deepseek": ("https://api.deepseek.com", "deepseek_model", "DEEPSEEK_API_KEY"),
    "openai": ("https://api.openai.com/v1", "openai_model", "OPENAI_API_KEY"),
    "siliconflow": ("https://api.siliconflow.cn/v1", "siliconflow_model", "SILICONFLOW_API_KEY"),   # 备选 Qwen/Qwen2.5-72B-Instruct
    "xai": ("https://api.x.ai/v1", "xai_model", "XAI_API_KEY"),
    "custom": (None, "llm_model", None),     # 自定义 / OpenAI 兼容网关：LLM_BASE_URL + LLM_MODEL + LLM_API_KEY（如内网 glm 网关、vLLM、One-API）
}

def providers() -> dict:
    """provider → {base_url, model, key_env}。custom 只在设置了 LLM_BASE_URL 时出现。"""
    st = settings()
    out = {}
    for n, (base, mf, ke) in _PROVIDER_DEF.items():
        if n == "custom":
            if not st.llm_base_url:
                continue
            out[n] = {"base_url": st.llm_base_url, "model": st.llm_model or st.local_llm_model, "key_env": None}
        else:
            out[n] = {"base_url": base or st.local_llm_url, "model": getattr(st, mf), "key_env": ke}
    return out

def default_provider() -> str:
    """provider 留空时的解析结果：设置了 LLM_BASE_URL → custom，否则 local"""
    return "custom" if settings().llm_base_url else "local"

PROVIDERS = providers()

def retrieval_defaults() -> dict:
    """检索参数默认值（config：RETRIEVAL_MODE / HYBRID_ALPHA / RERANK_TOP_N / RERANK_BETA）；调用方显式传入的优先"""
    st = settings()
    return {"mode": st.retrieval_mode, "alpha": st.hybrid_alpha, "rerank_top_n": st.rerank_top_n, "rerank_beta": st.rerank_beta}

def provider_ready(provider: str) -> tuple[bool, str]:
    """界面用：检查提供方是否可用（只检查 key / 地址是否存在，不发请求）"""
    ps = providers()
    if provider not in ps:
        return False, "未设置 LLM_BASE_URL，无法使用 custom" if provider == "custom" else f"未知的 LLM 提供方：{provider}"
    p = ps[provider]
    if p["key_env"] and not secret(p["key_env"]):
        return False, f"未设置环境变量 {p['key_env']}，无法使用 {provider}"
    return True, f"{p['base_url']} · {p['model']}"

SYSTEM_PROMPT = """你是电力设备运维技术助手。请严格遵守：
1. 只依据用户消息中“参考资料”的内容作答，不要使用资料以外的知识，不要编造数值、条款号或结论。
2. 先写出完整的回答句子，再在句末用方括号标注所依据的资料编号，如“……不应小于XX。[2]”；编号只能取参考资料中出现的编号，不要只输出编号。
3. 如果参考资料不足以回答问题，只回答“根据现有资料无法回答该问题。”，不要猜测；能回答时不要再写这句话。
4. 必须用简体中文回答（即使资料是英文），可保留英文术语、型号和数值。"""

# Prompt 版本（调参实验）：p0 = 原版；p1 = 逐条覆盖；p2 = 逐条覆盖 + 先列要点 + 格式示例（few-shot，内容与评测集无关）
P1_RULES = """
5. 问题若包含多个子问题、条件或数值，逐条回答，每条单独成句并各自标注引用，不要遗漏任何一个子问题。
6. 操作步骤类问题按资料中的先后顺序用 1. 2. 3. 编号列出；数值、单位和适用条件照抄资料原文，不要换算或概括。"""
P2_RULES = P1_RULES + """
7. 先用编号列出要点（每条一句、带引用），最后用一句话总结；回答中不要出现“编号”“XX”等占位词。"""
P2_EXAMPLE = """
格式示例（仅示意格式，内容与本次问题无关）：
问题：某装置的巡视周期和异常时的处理要求是什么？
回答：
1. 该装置每月巡视一次。[1]
2. 发现异常时应立即上报并做好记录。[2]
总结：每月巡视，异常立即上报。[1][2]"""
P3_RULES = P1_RULES + """
7. 先输出“【要点清单】”：从参考资料中逐条列出回答本问题必须覆盖的要点（数值+单位+条件、步骤、注意事项、例外），每条一行；
   再输出“【回答】”：按要点清单逐条作答，每条单独成句并标注引用，清单中的每一条都必须在回答中出现，不得遗漏。"""
PROMPTS = {"p0": SYSTEM_PROMPT, "p1": SYSTEM_PROMPT + P1_RULES, "p2": SYSTEM_PROMPT + P2_RULES + P2_EXAMPLE, "p3": SYSTEM_PROMPT + P3_RULES}   # 后者仅用于版本哈希

def strip_checklist(text: str) -> str:
    """p3：只保留【回答】之后的部分（要点清单是中间产物，不展示、不参与评分）"""
    m = re.search(r"【回答】[:：]?\s*", text)
    return text[m.end():].strip() if m else re.sub(r"【要点清单】.*?(?=\n\s*1[.、])", "", text, flags=re.S).strip()

REFLECT_PROMPT = """你是检索质量检查员。阅读参考资料和问题，判断参考资料是否足以完整回答问题的每一个子问题/条件。
只输出 JSON：{"enough": true 或 false, "missing": ["缺失的信息点，写成可直接用于检索的短查询", ...]}（missing 最多 2 条，足够时为空列表）"""

def reflect(question: str, hits: list[dict], cfg: dict, max_chars: int = 700) -> dict:
    """生成前自检：让 LLM 判断资料是否足够、列出缺失点（与 provider 无关，走同一 OpenAI 兼容接口）"""
    msgs = [{"role": "system", "content": REFLECT_PROMPT},
            {"role": "user", "content": f"参考资料：\n{build_context(hits, max_chars)}\n\n问题：{question}"}]
    t0 = time.time()
    try:
        text, info = call_llm(msgs, cfg, max_tokens=160, temperature=0.0)
        m = re.search(r"\{.*\}", text, re.S)
        d = json.loads(m.group(0)) if m else {}
    except Exception as e:
        return {"enough": True, "missing": [], "error": str(e)[:80], "secs": round(time.time() - t0, 2), "usage": {}}
    miss = [str(x)[:60] for x in (d.get("missing") or []) if str(x).strip()][:2]
    return {"enough": bool(d.get("enough", not miss)) and not miss, "missing": miss, "secs": round(time.time() - t0, 2), "usage": info.get("usage", {})}
DEFAULT_PROMPT = settings().rag_prompt or "p1"   # 调参结论：p1（逐条作答+步骤编号），见 output/version_scores.md

def llm_config(provider: str | None = None) -> dict:
    """解析 LLM 调用配置。优先级（高→低）：
    1. 显式 provider（请求体 / --provider / 网页下拉）：local=LOCAL_LLM_URL+LOCAL_LLM_MODEL；custom=LLM_BASE_URL+LLM_MODEL+LLM_API_KEY；
       云端档=写死的官方地址 + <NAME>_MODEL + <NAME>_API_KEY（LLM_BASE_URL 对它们不生效）
    2. provider 留空：设置了 LLM_BASE_URL → 等同 custom；否则等同 local
    API key：云端档用各自的 <NAME>_API_KEY（缺失则 ProviderNotReady）；local/custom 用 LLM_API_KEY，未设置时填占位 "ollama"
    """
    st = settings()
    if provider == "custom" and not st.llm_base_url:
        raise ProviderNotReady("未设置 LLM_BASE_URL，无法使用 custom（自定义 OpenAI 兼容网关）")
    ps = providers()
    if provider is not None and provider not in ps:
        raise ProviderNotReady(f"未知的 LLM 提供方：{provider}（可选 {', '.join(ps)}）")
    name = provider or default_provider()
    p = ps[name]
    if p["key_env"] and not secret(p["key_env"]):
        raise ProviderNotReady(f"未设置环境变量 {p['key_env']}，无法使用 {provider}")
    model = p["model"]
    if provider is None and name == "local" and st.llm_model:    # 兼容旧用法：只设 LLM_MODEL 时覆盖本地模型名
        model = st.llm_model
    return {"provider": name, "base_url": p["base_url"].rstrip("/"), "model": model,
            "api_key": (secret(p["key_env"]) if p["key_env"] else None) or secret("llm_api_key") or "ollama"}

TABLE_RULE = "\n5. 参考资料中的表格以 Markdown 给出（首行为表头）。引用表格数值时须对应正确的行和列，并写明该数值所在列的表头含义（如单位、适用条件）。"
TABLE_MAX_CHARS = 1500
EXPAND_MAX_CHARS = 2000      # 父块/相邻块扩展后单条资料上限
DEFAULT_EXPAND = settings().rag_expand
CLOUD_PROVIDERS = ("siliconflow", "deepseek", "openai", "xai")
DEFAULT_REFLECT = settings().rag_reflect   # 生成前自检+补检索（多一次 LLM 调用；默认关，待云端模型正式评测）
RECOMMENDED_REFUSE_BELOW = 0.3   # 重排 Top-1 分阈值：库内 139 题误拒 0%、库外拦截 44%（output/threshold_scan.md）
DEFAULT_REFUSE_BELOW = settings().rag_refuse_below    # 默认 0.3；RAG_REFUSE_BELOW=off 关闭   # 默认开启；RAG_REFUSE_BELOW=off 关闭

def _is_table(h) -> bool:
    return (h.get("metadata") or {}).get("chunk_type") in ("table", "table_row") or h["text"].startswith("【表格】")

def table_context(text: str, matched_row: str | None, cap: int = TABLE_MAX_CHARS) -> str:
    """表格块压缩：保留表题/章节/表头（到分隔行 |---|），优先保留命中的行，再按顺序补齐其余行，超长则注明省略行数"""
    lines = text.strip().split("\n")
    k = next((i for i, l in enumerate(lines) if l.startswith("|---")), 0) + 1
    head, body = lines[:k], lines[k:]
    if len("\n".join(lines)) <= cap:
        return "\n".join(lines)
    keys = [x for x in re.split(r"[：:；;。]", matched_row or "") if len(x.strip()) >= 2][1:]
    score = lambda l: sum(1 for x in keys if x.strip() in l)
    pri = sorted(range(len(body)), key=lambda i: (-score(body[i]), i))
    keep, n = set(), len("\n".join(head))
    for i in pri:
        if n + len(body[i]) + 1 > cap:
            continue
        keep.add(i); n += len(body[i]) + 1
    out = head + [body[i] for i in sorted(keep)]
    if len(keep) < len(body):
        out.append(f"…（本表其余 {len(body) - len(keep)} 行省略）")
    return "\n".join(out)

def build_context(hits: list[dict], max_chars: int = 700) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        m = h["metadata"]
        pg = f"p{m['page_start']}" + (f"-{m['page_end']}" if m.get("page_end") and m["page_end"] != m["page_start"] else "")
        if _is_table(h):                               # 表格：保留换行与表头，长度上限放宽
            txt = table_context(h["text"], h.get("matched_row"))
        else:
            txt = re.sub(r"\s+", " ", h["text"]).strip()
            cap = max(max_chars, EXPAND_MAX_CHARS) if h.get("expanded_ctx") else max_chars
            if len(txt) > cap:
                txt = txt[:cap] + "…"
        parts.append(f"[{i}] 文件：{m['source']}｜章节：{m.get('heading_path') or '-'}｜页码：{pg}\n{txt}")
    return "\n\n".join(parts)

def build_messages(question: str, hits: list[dict], max_chars: int = 700, prompt: str | None = None) -> list[dict]:
    user = f"参考资料：\n{build_context(hits, max_chars)}\n\n问题：{question}\n\n请依据参考资料回答，并用 [编号] 标注引用。"
    pv = prompt or DEFAULT_PROMPT
    base = {"p0": SYSTEM_PROMPT, "p1": SYSTEM_PROMPT + P1_RULES, "p2": SYSTEM_PROMPT + P2_RULES, "p3": SYSTEM_PROMPT + P3_RULES}[pv]
    tr = TABLE_RULE.replace("\n5.", "\n8." if pv in ("p2", "p3") else "\n7." if pv == "p1" else "\n5.")
    sp = base + (tr if any(_is_table(h) for h in hits) else "") + (P2_EXAMPLE if pv == "p2" else "")   # 有表格时才追加表格规则（无表格时 prompt 与旧版一致）
    return [{"role": "system", "content": sp}, {"role": "user", "content": user}]

def call_llm(messages, cfg, stream=False, max_tokens=512, temperature=0.1, on_token=None) -> tuple[str, dict]:
    """OpenAI 兼容 /chat/completions。失败映射：超时→LLMTimeout，429→LLMRateLimited，401/403→LLMAuthError（不重试），
    5xx/网络→LLMUnavailable，其它 4xx→LLMError。429/5xx/网络错误按 LLM_MAX_RETRIES 指数退避重试（遵守 Retry-After），
    超时另按 LLM_TIMEOUT_RETRIES 计数；流式已输出部分 token 后不再重试（避免重复内容）。"""
    st = settings()
    url = cfg["base_url"] + "/chat/completions"
    body = {"model": cfg["model"], "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": stream}
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    attempt = t_retries = 0
    while True:
        emitted = [False]
        def tok(t):
            emitted[0] = True
            on_token(t)
        retry_after = None
        try:
            text, info = _call_llm_once(url, body, headers, stream, tok if on_token else None, st)
            info["attempts"] = attempt + 1
            return text, info
        except httpx.TimeoutException:
            err = LLMTimeout(f"大模型响应超时（>{st.llm_timeout:g}s）"); retry = t_retries < st.llm_timeout_retries; t_retries += 1
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            retry_after = e.response.headers.get("retry-after")
            if code in (401, 403):
                err, retry = LLMAuthError(detail={"upstream_status": code}), False
            elif code == 429:
                err, retry = LLMRateLimited(detail={"upstream_status": code}), True
            elif code >= 500:
                err, retry = LLMUnavailable(f"大模型服务端错误（HTTP {code}）", detail={"upstream_status": code}), True
            else:
                err, retry = LLMError(f"大模型请求被拒绝（HTTP {code}）", detail={"upstream_status": code}), False
        except httpx.TransportError as e:
            err, retry = LLMUnavailable(f"无法连接大模型服务（{type(e).__name__}）"), True
        except (KeyError, IndexError, ValueError, TypeError):
            err, retry = LLMError("大模型返回格式异常"), False
        if emitted[0]:
            retry = False
        if not retry or attempt >= st.llm_max_retries:
            event(log, "llm.failed", logging.WARNING, provider=cfg.get("provider"), model=cfg["model"], code=err.code, attempts=attempt + 1)
            raise err
        wait = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else min(st.llm_backoff_cap, st.llm_backoff_base * 2 ** attempt)
        event(log, "llm.retry", logging.WARNING, provider=cfg.get("provider"), model=cfg["model"], code=err.code, attempt=attempt + 1, wait_secs=wait)
        time.sleep(wait)
        attempt += 1

def _call_llm_once(url, body, headers, stream, on_token, st=None):
    st = st or settings()
    t0, first, usage, out = time.time(), None, {}, []
    with httpx.Client(timeout=httpx.Timeout(st.llm_timeout, connect=st.llm_connect_timeout)) as cli:
        if not stream:
            r = cli.post(url, json=body, headers=headers); r.raise_for_status()
            d = r.json(); usage = d.get("usage", {}) or {}
            text = d["choices"][0]["message"]["content"]
        else:
            with cli.stream("POST", url, json=body, headers=headers) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    d = json.loads(data)
                    if d.get("usage"):
                        usage = d["usage"]
                    if d.get("choices"):
                        tok = d["choices"][0].get("delta", {}).get("content") or ""
                        if tok:
                            first = first or time.time()
                            out.append(tok)
                            if on_token:
                                on_token(tok)
            text = "".join(out)
    return text, {"usage": usage, "secs": round(time.time() - t0, 2),
                  "first_token_secs": round(first - t0, 2) if first else None}

CITE_RE = re.compile(r"\[(\d+(?:\s*[,，、]\s*\d+)*)\]")
REFUSE_RE = re.compile(r"无法回答|不知道|没有(相关|提及|涉及)|未(提及|涉及|包含|找到)|资料(中)?(不足|没有)")

def parse_citations(answer: str, n: int) -> tuple[list[int], list[int]]:
    used, bad = [], []
    for m in CITE_RE.finditer(answer):
        for x in re.split(r"[,，、]", m.group(1)):
            i = int(x)
            (used if 1 <= i <= n else bad).append(i)
    return sorted(set(used)), sorted(set(bad))

def clean_invalid(answer: str, bad: list[int]) -> str:
    for b in bad:
        answer = re.sub(rf"\[{b}\]", "", answer)
    return answer

NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|μL/L|A|V|kV|年|月|次|个月|h|min|s|mm)?")

def _nums(s: str) -> set[str]:
    return {re.sub(r"\s", "", m.group(0)) for m in NUM_RE.finditer(s) if len(m.group(0).strip()) > 0}

SENT_RE = re.compile(r"[^。；;!?\n]+[。；;!?\n]?(?:\s*\[\d+(?:\s*[,，、]\s*\d+)*\])*")

NUMCHECK = settings().rag_numcheck   # v2 = numcheck.py（单位换算/范围/表头单位）；v1 = 旧版字符串包含

def support_check(answer: str, hits: list[dict]) -> list[str]:
    if NUMCHECK == "v1":
        return support_check_v1(answer, hits)
    import numcheck
    return numcheck.check(answer, hits)

def support_check_v1(answer: str, hits: list[dict]) -> list[str]:
    """旧版粗检：每个带引用的句子里的数值，是否出现在它引用的资料中；不在则若在其他资料中出现，提示"引用可能错配"，都不在提示"数值无出处" """
    warns = []
    for sent in SENT_RE.findall(answer):
        cites, _ = parse_citations(sent, len(hits))
        nums = {n for n in _nums(CITE_RE.sub("", sent)) if not re.fullmatch(r"\d", n)}
        if not cites or not nums:
            continue
        cited = re.sub(r"\s", "", " ".join(hits[i - 1]["text"] for i in cites))
        for n in nums:
            if n not in cited:
                other = [i + 1 for i, h in enumerate(hits) if n in re.sub(r"\s", "", h["text"])]
                warns.append(f"“{n}”不在引用 {cites} 中" + (f"，但见于资料 {other}（引用可能错配）" if other else "（数值无出处，可能编造）"))
    return warns

def excerpt(text: str, answer: str, n: int = 160) -> str:
    """摘取与回答重合度最高的一句作原文摘录（退化为开头）"""
    t = re.sub(r"\s+", " ", text).strip()
    sents = [s for s in re.split(r"(?<=[。；;!?])\s*|(?<=[^\d]\.)\s+", t) if len(s) > 8] or [t]
    ans = set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9.%]+", answer))
    best = max(sents, key=lambda s: len(ans & set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9.%]+", s))))
    return best[:n] + ("…" if len(best) > n else "")

def answer(question: str, k: int = 5, rerank: bool = True, provider: str | None = None, stream: bool = False,
           on_token=None, filters: dict | None = None, max_chars: int = 700, max_tokens: int = 512, hits: list | None = None, search_kw: dict | None = None,
           model: str | None = None, prompt: str | None = None, expand: str | None = None, refuse_below: float | None = -1.0,
           reflect_round: bool | None = None) -> dict:
    """expand: none|neighbor|parent（默认 RAG_EXPAND）；refuse_below: 重排 Top-1 分低于该值直接拒答、不调用 LLM（-1=用默认 RAG_REFUSE_BELOW，None=关闭）"""
    from retrieve import search
    cfg = llm_config(provider)
    if prompt is None and provider in CLOUD_PROVIDERS and settings().rag_prompt is None:
        prompt = "p2"                 # 云端大模型推荐 p2（见 version_scores.md），本地 3B 保持 p1
    if model:
        cfg["model"] = model            # 先校验 LLM 配置（如缺 DEEPSEEK_API_KEY 直接报 ProviderNotReady），再检索
    t0 = time.time()
    if hits is None:                       # 评测脚本可传入已检索好的 hits，避免重复检索
        skw = {**retrieval_defaults(), **(search_kw or {})}; skw.setdefault("collection", settings().kb_collection)   # 默认走 v2 集合（表格父子块）
        xl = settings().rag_xlang or ("cap" if provider in CLOUD_PROVIDERS else "none")   # 云端默认跨语言 cap（Day 18 验证）
        if xl != "none" and "xlang" not in skw:
            import qx
            if provider in CLOUD_PROVIDERS:
                qx.QX_PROVIDER = provider       # 问句翻译与回答用同一云端模型（结果缓存）
            skw["xlang"] = xl
        hits = _search_safe(search, question, k=k, filters=filters, rerank=rerank, rerank_use_cache=False, **skw)   # 实时计算重排，耗时真实
    else:
        hits = [dict(h) for h in hits[:k]]
    t_search = time.time() - t0
    t_rr = hits[0].pop("_rerank_secs", 0.0) if hits else 0.0
    for h in hits:
        h.pop("_rerank_secs", None)
    th = DEFAULT_REFUSE_BELOW if refuse_below == -1.0 else refuse_below
    top = hits[0].get("rerank_score") if hits else None
    if th is not None and (not hits or (top is not None and top < th)):
        msg = "根据现有资料无法回答该问题。"
        if stream and on_token:
            on_token(msg)
        return _logged(question, {"question": question, "answer": msg, "raw_answer": msg, "sources": [], "invalid_citations": [], "refused": True,
                "threshold_refused": True, "retried": False, "support_warnings": [], "model": cfg["model"], "base_url": cfg["base_url"],
                "retrieved": [{"rank": h["rank"], "source": h["source"], "section": h.get("heading_path"), "score": h["score"],
                               "rerank_score": h.get("rerank_score"), "page_start": h.get("page_start"), "page_end": h.get("page_end")} for h in hits],
                "timing": {"retrieval_secs": round(t_search - t_rr, 2), "rerank_secs": round(t_rr, 2), "generation_secs": 0.0,
                           "first_token_secs": None, "total_secs": round(time.time() - t0, 2)}, "usage": {}, "prompt_chars": 0,
                "provider": cfg.get("provider"), "top_rerank": top})
    ex = expand if expand is not None else DEFAULT_EXPAND
    if ex and ex != "none":
        from context_expand import expand_hits
        hits = expand_hits(hits, method=(search_kw or {}).get("collection") or settings().kb_collection, mode=ex)
    rf = None
    if (DEFAULT_REFLECT if reflect_round is None else reflect_round):     # 自检 → 缺失点补检 1 轮（每个缺失点取 Top-2，去重后追加，最多 +3 条）
        rf = reflect(question, hits, cfg, max_chars)
        if not rf["enough"] and rf["missing"]:
            skw = {**retrieval_defaults(), **(search_kw or {})}; skw.setdefault("collection", settings().kb_collection)
            have = {h["chunk_id"] for h in hits}; added = []
            for mq in rf["missing"]:
                for h in search(mq, k=2, filters=filters, rerank=rerank, **skw):
                    if h["chunk_id"] not in have and len(added) < 3:
                        h.pop("_rerank_secs", None); have.add(h["chunk_id"]); added.append(h)
            hits = hits + added
            for i, h in enumerate(hits):
                h["rank"] = i + 1
            rf["added"] = [f"{h['source']}｜{h.get('heading_path', '')}"[:80] for h in added]
    msgs = build_messages(question, hits, max_chars, prompt)
    if (prompt or DEFAULT_PROMPT) == "p3":
        max_tokens = max(max_tokens, 1024)          # p3 先写要点清单再作答，512 会截断
    fallback = None
    try:
        text, info, retried = _generate(msgs, cfg, stream, on_token, max_tokens)
    except LLMError as e:
        fb = settings().llm_fallback
        if fb in ("local", "local_then_retrieval") and cfg.get("provider") in CLOUD_PROVIDERS:
            try:
                lcfg = llm_config("local")
                event(log, "llm.fallback", logging.WARNING, frm=cfg.get("provider"), to="local", reason=e.code)
                if stream and on_token:
                    on_token("\n（云端大模型调用失败，已改用本地模型）\n")
                text, info, retried = _generate(msgs, lcfg, stream, on_token, max_tokens)
                fallback = {"from": cfg.get("provider"), "to": "local", "reason": e.code, "message": e.message}
                cfg = lcfg
            except LLMError as e2:
                if fb == "local":
                    raise
                return _logged(question, _retrieval_only(question, hits, e2, cfg, t0, t_search, t_rr, stream, on_token, first_error=e))
        elif fb in ("retrieval", "local_then_retrieval"):
            return _logged(question, _retrieval_only(question, hits, e, cfg, t0, t_search, t_rr, stream, on_token))
        else:
            raise
    if (prompt or DEFAULT_PROMPT) == "p3":
        text = strip_checklist(text)
    used, bad = parse_citations(text, len(hits))
    text_clean = clean_invalid(text, bad).replace("[编号]", "")
    body = CITE_RE.sub("", text_clean).strip()
    refused = bool(REFUSE_RE.search(body)) and (not used or len(body) < 40)   # 短的拒答句即使带了编号也视为拒答
    if refused:
        used, text_clean = [], body
    warnings = support_check(text_clean, hits) if not refused else []
    sources = []
    for i in used:
        h = hits[i - 1]; m = h["metadata"]
        sources.append({"id": i, "source": m["source"], "section": m.get("heading_path") or "-",
                        "pages": f"{m['page_start']}" + (f"-{m['page_end']}" if m.get("page_end") and m["page_end"] != m["page_start"] else ""),
                        "chunk_id": h["chunk_id"], "excerpt": excerpt(h["text"], text_clean),
                        "score": h.get("score"), "rerank_score": h.get("rerank_score"), "stage1_rank": h.get("stage1_rank")})
    if fallback:
        warnings = [f"云端模型调用失败（{fallback['message']}），本回答由本地模型生成"] + warnings
    return _logged(question, {"question": question, "answer": text_clean, "raw_answer": text, "sources": sources, "reflect": rf,
            "extra_hits": [{"rank": h["rank"], "chunk_id": h["chunk_id"], "source": h["source"], "heading_path": h.get("heading_path", ""),
                            "page_start": h.get("page_start"), "page_end": h.get("page_end"), "text": h["text"], "metadata": h.get("metadata", {})}
                           for h in hits[k:]] if rf and rf.get("added") else [],
            "invalid_citations": bad, "refused": refused, "retried": retried, "support_warnings": warnings, "model": cfg["model"], "base_url": cfg["base_url"],
            "retrieved": [{"rank": h["rank"], "source": h["source"], "section": h.get("heading_path"), "score": h["score"],
                           "rerank_score": h.get("rerank_score"), "page_start": h.get("page_start"), "page_end": h.get("page_end")} for h in hits],
            "timing": {"retrieval_secs": round(t_search - t_rr, 2), "rerank_secs": round(t_rr, 2),
                       "generation_secs": round(info["secs"] + ((rf or {}).get("secs") or 0), 2), "first_token_secs": info["first_token_secs"],
                       "reflect_secs": (rf or {}).get("secs"),
                       "total_secs": round(time.time() - t0, 2)},
            "usage": info["usage"], "prompt_chars": sum(len(m["content"]) for m in msgs),
            "provider": cfg.get("provider"), "fallback": fallback, "degraded": False, "top_rerank": top})

def _generate(msgs, cfg, stream, on_token, max_tokens):
    text, info = call_llm(msgs, cfg, stream=stream, on_token=on_token, max_tokens=max_tokens)
    retried = False
    if len(CITE_RE.sub("", text).strip(" \n。.")) < 4:             # 小模型偶发只输出编号：补一次提示重试
        retried = True
        msgs2 = msgs + [{"role": "assistant", "content": text},
                        {"role": "user", "content": "请用完整的中文句子回答问题，并在句末标注引用编号。"}]
        if stream and on_token:
            on_token("\n（重新生成）\n")
        text, info2 = call_llm(msgs2, cfg, stream=stream, on_token=on_token, max_tokens=max_tokens)
        info = {"usage": info2["usage"], "secs": round(info["secs"] + info2["secs"], 2), "first_token_secs": info["first_token_secs"]}
    return text, info, retried

def _search_safe(search, question, **kw):
    """检索异常 → RetrievalError / IndexNotReady（集合不存在、模型未下载等）"""
    try:
        return search(question, **kw)
    except PowerKBError:
        raise
    except Exception as e:
        msg = str(e).lower()
        log.exception("retrieval failed")
        if "does not exist" in msg or "not exist" in msg or "no such file" in msg or "collection" in msg and "not found" in msg:
            raise IndexNotReady("向量索引不存在或未构建（请先建索引，见 README“准备文档并重建索引”）") from None
        raise RetrievalError(f"检索失败（{type(e).__name__}）") from None

def _retrieval_only(question, hits, err, cfg, t0, t_search, t_rr, stream, on_token, first_error=None):
    """降级：LLM 不可用时直接返回检索到的资料（不生成）"""
    event(log, "llm.fallback", logging.WARNING, frm=cfg.get("provider"), to="retrieval_only", reason=err.code)
    top = hits[:min(3, len(hits))]
    lines = [f"⚠ 大模型暂时不可用（{(first_error or err).message}），以下是检索到的最相关资料，请直接查阅原文："]
    sources = []
    for i, h in enumerate(top, 1):
        m = h.get("metadata", {}) or {}
        ex = re.sub(r"\s+", " ", h["text"]).strip()[:160]
        lines.append(f"[{i}] {h['source']}｜{h.get('heading_path') or '-'}（p{h.get('page_start')}）：{ex}…")
        sources.append({"id": i, "source": h["source"], "section": h.get("heading_path") or "-", "pages": str(h.get("page_start")),
                        "chunk_id": h["chunk_id"], "excerpt": ex, "score": h.get("score"), "rerank_score": h.get("rerank_score"),
                        "stage1_rank": h.get("stage1_rank")})
    text = "\n\n".join(lines)
    if stream and on_token:
        on_token(text)
    msgs = [first_error.message] if first_error else []
    return {"question": question, "answer": text, "raw_answer": "", "sources": sources, "reflect": None, "extra_hits": [],
            "invalid_citations": [], "refused": False, "retried": False, "support_warnings": msgs + [err.message],
            "model": cfg["model"], "base_url": cfg["base_url"], "provider": cfg.get("provider"),
            "retrieved": [{"rank": h["rank"], "source": h["source"], "section": h.get("heading_path"), "score": h["score"],
                           "rerank_score": h.get("rerank_score"), "page_start": h.get("page_start"), "page_end": h.get("page_end")} for h in hits],
            "timing": {"retrieval_secs": round(t_search - t_rr, 2), "rerank_secs": round(t_rr, 2), "generation_secs": 0.0,
                       "first_token_secs": None, "total_secs": round(time.time() - t0, 2)},
            "usage": {}, "prompt_chars": 0, "degraded": True, "fallback": {"from": cfg.get("provider"), "to": "retrieval_only", "reason": err.code,
                                                                          "message": err.message},
            "error": {"code": err.code, "message": err.message}, "top_rerank": hits[0].get("rerank_score") if hits else None}

def _logged(question: str, r: dict) -> dict:
    """每次问答一条结构化日志：各阶段耗时、provider、token、拒答、降级"""
    t, u = r.get("timing", {}), r.get("usage") or {}
    event(log, "rag.answer", provider=r.get("provider"), model=r.get("model"), q=q_repr(question),
          retrieval_secs=t.get("retrieval_secs"), rerank_secs=t.get("rerank_secs"), generation_secs=t.get("generation_secs"),
          first_token_secs=t.get("first_token_secs"), total_secs=t.get("total_secs"),
          prompt_tokens=u.get("prompt_tokens"), completion_tokens=u.get("completion_tokens"), total_tokens=u.get("total_tokens"),
          top_rerank=round(r["top_rerank"], 3) if isinstance(r.get("top_rerank"), (int, float)) else None,
          refused=r.get("refused"), threshold_refused=r.get("threshold_refused", False), n_citations=len(r.get("sources", [])),
          invalid_citations=len(r.get("invalid_citations", [])), numcheck_warnings=len(r.get("support_warnings", [])),
          degraded=r.get("degraded", False), fallback=(r.get("fallback") or {}).get("to"))
    return r

def format_result(r: dict, show_answer=True) -> str:
    L = []
    if show_answer:
        L += [r["answer"].strip(), ""]
    if r["sources"]:
        L.append("出处：")
        for s in r["sources"]:
            L.append(f"[{s['id']}] {s['source']}｜{s['section']}｜p{s['pages']}\n    原文：{s['excerpt']}")
    elif r["refused"]:
        L.append("出处：无（资料不足，已拒答）")
    else:
        L.append("出处：无（回答未标注引用，请谨慎采信）")
    for w in r.get("support_warnings", []):
        L.append(f"⚠ 引用校验：{w}")
    if r["invalid_citations"]:
        L.append(f"（已删除不存在的引用编号：{r['invalid_citations']}）")
    t = r["timing"]
    L.append(f"\n耗时：检索 {t['retrieval_secs']}s｜重排 {t['rerank_secs']}s｜生成 {t['generation_secs']}s｜总计 {t['total_secs']}s（模型 {r['model']}）")
    return "\n".join(L)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--provider", choices=list(_PROVIDER_DEF), default=None, help="不填=设了 LLM_BASE_URL 走 custom，否则本地；custom=LLM_BASE_URL 网关；deepseek=用 DEEPSEEK_API_KEY")
    ap.add_argument("--model", default=None, help="覆盖提供方的默认模型，如 Qwen/Qwen2.5-72B-Instruct")
    ap.add_argument("--reflect", action="store_true", help="生成前自检 + 缺失点补检 1 轮")
    ap.add_argument("--prompt", default=None, choices=["p0", "p1", "p2", "p3"], help="默认：本地 p1，云端 p2（或 RAG_PROMPT）")
    ap.add_argument("--expand", default=None, choices=["none", "neighbor", "parent"], help="上下文扩展，默认 RAG_EXPAND 或 none")
    ap.add_argument("--refuse-below", default=None, help="重排 Top-1 分拒答阈值，默认 0.3（RAG_REFUSE_BELOW）；off=关闭")
    ap.add_argument("--stream", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rb = -1.0 if a.refuse_below is None else (None if a.refuse_below.lower() in ("off", "none") else float(a.refuse_below))
    kw = dict(model=a.model, prompt=a.prompt, expand=a.expand, refuse_below=rb, reflect_round=a.reflect or None)
    from kblog import setup_logging
    setup_logging()
    try:
        if a.stream and not a.json:
            r = answer(a.question, a.k, not a.no_rerank, a.provider, stream=True, on_token=lambda t: print(t, end="", flush=True), **kw)
            print("\n"); print(format_result(r, show_answer=False))
        else:
            r = answer(a.question, a.k, not a.no_rerank, a.provider, **kw)
            print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else format_result(r))
    except PowerKBError as e:                  # 友好提示，不打印堆栈
        print(f"\n错误 [{e.code}]：{e.message}", file=sys.stderr); sys.exit(1)
