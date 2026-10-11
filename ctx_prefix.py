# -*- coding: utf-8 -*-
"""Contextual 块前缀（规则版）：为 heading_v2 每块生成上下文前缀，写入新方法 heading_v2_ctx 的 embed_text（向量与 BM25 都用它；
documents 仍存原文 text，chunk_id 不变）。
前缀 = 【规范文档名（标准号《标题》/厂商 型号 手册）｜设备（中英）｜章节路径｜表题】+ 关键词（本块 TF-IDF 前 6 个术语；英文手册附中文术语，中文文档附英文术语）
可选 --llm N：对前 N 块用本地 3B 生成一句主题概括并计时（只评估可行性，默认不用）。
用法：python ctx_prefix.py && python embed_index.py --methods heading_v2_ctx && python bm25_index.py --methods heading_v2_ctx
"""
import json, os, re, math, sys, time, collections, argparse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bm25_index, qx

DOC = {  # 文件名前缀 → (规范名, 设备中文, 设备英文)
    "ABB_SafeRing": ("ABB SafeRing/SafePlus 12-24kV 环网柜 安装运行维护手册", "环网柜 气体绝缘开关柜", "ring main unit RMU switchgear"),
    "ABB_VD4": ("ABB VD4 36-40.5kV 真空断路器 安装与维护手册", "真空断路器", "vacuum circuit-breaker VCB"),
    "DL_T_1359": ("DL/T 1359-2025《六氟化硫电气设备故障气体分析和判断方法》", "SF6 电气设备 故障气体分析", "SF6 equipment fault gas analysis"),
    "DL_T_2228": ("DL/T 2228-2021《变电站用充气式开关柜运维检修规程》", "充气式开关柜", "gas-insulated switchgear cubicle"),
    "DL_T_2544": ("DL/T 2544-2022《继电保护装置状态检修导则》", "继电保护装置 状态检修", "protection relay condition-based maintenance"),
    "DL_T_2890": ("DL/T 2890-2025《高压交流断路器机械特性现场试验导则》", "高压断路器 机械特性试验", "circuit breaker mechanical characteristics test"),
    "DL_T_587": ("DL/T 587-2025《继电保护和安全自动装置运行管理规程》", "继电保护 安全自动装置", "relay protection automatic device"),
    "DL_T_595": ("DL/T 595-2025《六氟化硫电气设备气体监督导则》", "SF6 气体 监督", "SF6 gas supervision"),
    "DL_T_618": ("DL/T 618-2022《GIS现场交接试验规程》", "GIS 气体绝缘金属封闭开关设备 交接试验", "GIS commissioning test"),
    "DL_T_664": ("DL/T 664-2025《带电设备红外诊断应用规范》", "带电设备 红外诊断", "infrared diagnosis live equipment"),
    "DL_T_724": ("DL/T 724-2021《蓄电池直流电源装置运行与维护技术规程》", "蓄电池 直流电源", "battery DC power supply"),
    "DL_T_1555": ("DL/T 1555-2025《SF6气体泄漏在线监测报警装置运行维护导则》", "SF6 泄漏在线监测报警装置", "SF6 leakage online monitoring alarm device"),
    "SIPROTEC5": ("Siemens SIPROTEC 5 7SJ82-85 V8.60 手册", "继电保护装置 保护继电器", "protection relay IED"),
    "Schneider_GalaxyVS": ("Schneider Galaxy VS UPS 运行手册", "不间断电源 UPS", "uninterruptible power supply UPS"),
    "Schneider_SM6": ("Schneider SM6-24 中压开关柜 运行维护手册", "中压开关柜 负荷开关柜", "medium voltage switchgear cubicle"),
    "南方电网": ("南方电网《设备运行质量评价规则（变电在线监测装置部分）》2025", "变电在线监测装置 运行质量评价", "online monitoring device evaluation"),
    "平高_ZF12B": ("平高 ZF12B-126 GIS 安装使用说明书", "GIS 组合电器 SF6 断路器", "gas insulated switchgear GIS"),
    "施耐德_RM6": ("施耐德 RM6 SeT 环网柜 安装使用说明书", "环网柜", "ring main unit RMU"),
    "正泰_NM1": ("正泰 NM1 系列塑料外壳式断路器说明书", "塑壳断路器", "moulded case circuit breaker MCCB"),
}

def doc_info(src):
    return next((v for k, v in DOC.items() if src.startswith(k)), (os.path.splitext(src)[0], "", ""))

GENERIC = set("依据 判断 建议 推荐 导致 参阅 请参阅 部门 进行 应当 相关 情况 内容 方法 要求 规定 说明 以下 如下 包括 可以 需要 使用 时应 不得 必须 see refer following page chapter section note".split())

def keywords(chunks):
    toks = [[t for t in bm25_index.tokenize(c["text"]) if not re.fullmatch(r"[\d.]+|[a-z]", t) and len(t) >= 2 and t not in GENERIC] for c in chunks]
    df = collections.Counter(t for ts in toks for t in set(ts)); n = len(toks)
    out = []
    for ts in toks:
        tf = collections.Counter(ts)
        sc = sorted(tf, key=lambda t: -tf[t] * math.log(n / (1 + df[t])))
        keep = []
        for t in sc:                                            # 去掉被更长关键词包含的碎片（cut_for_search 会切出子词）
            if not any(t != k and t in k for k in sc[:12]):
                keep.append(t)
        out.append(keep[:6])
    return out

def bilingual(kws, lang):
    z2e, e2z, _, _ = qx._dict()
    extra = []
    for k in kws:
        if lang == "zh" and k in z2e:
            extra.append(z2e[k][0])
        elif lang != "zh":
            z = qx.en2zh(k)
            if z and re.search(r"[\u4e00-\u9fff]", z):
                extra.append(z)
    return list(dict.fromkeys(extra))[:5]

def prefix(c, kws):
    title, dz, de = doc_info(c["source"])
    parts = [title, f"{dz} / {de}".strip(" /"), c.get("heading_path") or ""]
    if c.get("table_caption"):
        parts.append(c["table_caption"])
    p = "【" + "｜".join(x for x in parts if x) + "】"
    bi = bilingual(kws, c.get("lang", "zh"))
    p += "\n关键词：" + "、".join(kws) + (f"（{' / '.join(bi)}）" if bi else "")
    return p

def build(src_path, dst_path):
    cs = [json.loads(l) for l in open(src_path, encoding="utf-8")]
    kw = keywords(cs)
    with open(dst_path, "w", encoding="utf-8") as f:
        for c, k in zip(cs, kw):
            d = dict(c, method="heading_v2_ctx", ctx_prefix=prefix(c, k))
            d["embed_text"] = d["ctx_prefix"] + "\n" + c["text"]
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return len(cs)

def llm_trial(n):
    import httpx
    cs = [json.loads(l) for l in open(os.path.join(HERE, "output", "chunks_heading_v2.jsonl"), encoding="utf-8")][200:200 + n]
    t0 = time.time(); outs = []
    for c in cs:
        r = httpx.post("http://127.0.0.1:11434/v1/chat/completions", timeout=300, json={"model": "qwen2.5:3b-instruct", "temperature": 0, "max_tokens": 60,
              "messages": [{"role": "user", "content": f"文档：{c['source']}\n章节：{c.get('heading_path')}\n片段：{c['text'][:800]}\n用一句不超过40字的话概括这个片段在讲什么（只输出这句话）："}]})
        outs.append(r.json()["choices"][0]["message"]["content"].strip())
    dt = (time.time() - t0) / n
    return dt, outs

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--llm", type=int, default=0); a = ap.parse_args()
    if a.llm:
        dt, outs = llm_trial(a.llm)
        print(f"本地 3B 概括：{dt:.1f} s/块；全库 3474+ 块约 {dt * 3500 / 3600:.1f} 小时"); print("\n".join(outs[:5])); sys.exit()
    n1 = build(os.path.join(HERE, "output", "chunks_heading_v2.jsonl"), os.path.join(HERE, "output", "chunks_heading_v2_ctx.jsonl"))
    n2 = build(os.path.join(HERE, "uploads", "chunks_uploaded_v2.jsonl"), os.path.join(HERE, "uploads", "chunks_uploaded_heading_v2_ctx.jsonl"))
    print(n1, n2)
    ex = [json.loads(l) for l in open(os.path.join(HERE, "output", "chunks_heading_v2_ctx.jsonl"), encoding="utf-8")]
    for i in (300, 1500, 2600):
        print(ex[i]["ctx_prefix"]); print("--")
