# -*- coding: utf-8 -*-
"""数值引用校验 v2：把回答中带引用句子里的数值抽成“量”（数值 + 量纲 + 基准单位值），与所引资料（含表格单元格）比对。

归一化：NFKC 全半角；中文数字（三年、两次、十五分钟）；科学计数（1.5×10^3、1.5×10³、1e-3）；
范围（3～20、3至20、3-20、3~20 μL/L → 两端都带单位）与 ±（220 V±10%）；比较词（≥/不小于/不低于/≤/不大于…）只是修饰，不影响取值；
单位换算到基准：kV/V/mV、kA/A/mA/μA、μL/L=ppm、MPa/kPa/Pa/bar、MΩ/kΩ/Ω、km/m/cm/mm、h/min/s/ms、kW/W、kHz/Hz、℃。
判定（回答中的一个量 q）：
  1) 资料中有同量纲、基准值相等的量 → 支持；
  2) 资料中有同一裸数值，且资料中出现过同量纲的单位（表头“（μL/L）”+ 单元格“3～20”这类）或该数值在资料中本身无单位 → 支持；
  3) q 无单位：资料中出现同一数值即支持；
不满足才告警；若在其它（未引用的）资料中满足则提示“引用可能错配”。
忽略：个位数无单位整数（编号/步骤）、条款号（6.1.3）、标准号（DL/T 724-2021、IEC 62271-200）。
"""
from __future__ import annotations
import re, unicodedata
from dataclasses import dataclass

UNITS = [  # (正则, 量纲, 换算到基准的系数)
    (r"μl/l|ul/l|µl/l|ppmv|ppm", "ppm", 1), (r"μg/g|ug/g", "ug/g", 1), (r"%", "%", 1), (r"‰", "%", 0.1),
    (r"kv", "V", 1e3), (r"mv", "V", 1e-3), (r"v", "V", 1), (r"ka", "A", 1e3), (r"ma", "A", 1e-3), (r"μa|ua", "A", 1e-6), (r"a", "A", 1),
    (r"mpa", "Pa", 1e6), (r"kpa", "Pa", 1e3), (r"pa", "Pa", 1), (r"bar", "Pa", 1e5),
    (r"mω|mohm", "ohm", 1e6), (r"kω", "ohm", 1e3), (r"μω|uω", "ohm", 1e-6), (r"ω", "ohm", 1),
    (r"℃|°c", "C", 1), (r"km", "m", 1e3), (r"mm", "m", 1e-3), (r"cm", "m", 1e-2), (r"m(?!in|s|ω|a|v|pa|m)", "m", 1),
    (r"ms", "s", 1e-3), (r"min|分钟", "s", 60), (r"h(?!z)|小时", "s", 3600), (r"s(?![a-z])|秒", "s", 1),
    (r"天|days?|d(?![a-z])", "day", 1), (r"周|weeks?", "day", 7), (r"个月|月|months?", "month", 1), (r"年|years?|yrs?", "month", 12),
    (r"hours?|hrs?", "s", 3600), (r"minutes?|mins?", "s", 60), (r"seconds?|secs?", "s", 1), (r"times", "times", 1),
    (r"mva", "VA", 1e6), (r"kva", "VA", 1e3), (r"mw", "W", 1e6), (r"kw", "W", 1e3), (r"w", "W", 1),
    (r"mhz", "Hz", 1e6), (r"khz", "Hz", 1e3), (r"hz", "Hz", 1), (r"n·m|n\.m|nm", "Nm", 1), (r"kg", "kg", 1), (r"g(?![a-z])", "kg", 1e-3),
    (r"次", "times", 1), (r"台|只|个", "count", 1),
]
UNIT_RE = "|".join(f"(?:{u})" for u, _, _ in UNITS)
CN = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
NUM = r"\d+(?:\.\d+)?(?:\s*[×x*]\s*10\s*(?:\^|\*\*)?\s*[-−]?\d+|e[-+]?\d+)?"
NUMX = NUM + r"(?![\d])(?!\.\d)"
_UB = rf"(?:{UNIT_RE})(?![a-z])"                                                # 单位后不能紧跟字母（避免 100 mile、5 amps 误判）
QTY_RE = re.compile(rf"(?<![a-z0-9_.])({NUMX})(?:\s*({_UB}))?(?:\s*(?:~|至|到|-|—)\s*({NUMX})\s*({_UB})?)?", re.I)
UNIT_MENTION = re.compile(rf"[（(\[/|]\s*({UNIT_RE})\s*(?=[)）\]|/,，])|单位[:：为]?\s*({UNIT_RE})|\bin\s+({UNIT_RE})\b|[a-z]\s+({UNIT_RE})\s*\|", re.I)   # 表头/括注里的单位
SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
STD_RE = re.compile(r"(?<![a-z0-9])(?:dl|gb|iec|ieee|ansi|en|q/csg|q/gdw|nb|jb|din|vde|ul)\s*/?\s*t?\s*\d+(?:\.\d+)?(?:\s*[-—]\s*\d{2,4})?", re.I)
CLAUSE_RE = re.compile(r"(?<![\d.])\d+(?:\.\d+){2,}(?![\d])")

def cn2num(s: str) -> int | None:
    if not s or any(c not in "零一二两三四五六七八九十百" for c in s):
        return None
    if "百" in s:
        a, b = s.split("百", 1)
        return (CN.get(a, 1) if a else 1) * 100 + (cn2num(b) or 0)
    if "十" in s:
        a, b = s.split("十", 1)
        return (CN.get(a, 1) if a else 1) * 10 + (CN.get(b, 0) if b else 0)
    return CN.get(s) if len(s) == 1 else None

def normalize(text: str) -> str:
    t = re.sub(r"[×x]\s*10([⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "×10^" + m.group(1).translate(SUP), text or "")   # 先于 NFKC，保住上标指数
    t = unicodedata.normalize("NFKC", t).translate(SUP).replace("µ", "μ").lower()
    t = t.replace("～", "~").replace("〜", "~").replace("−", "-")
    t = re.sub(r"\[\d+(?:\s*[,，、]\s*\d+)*\]", " ", t)                       # 引用标记
    t = STD_RE.sub(" ", t)
    t = re.sub(r"(?<![a-z0-9])[a-z][a-z0-9]*(?:-[a-z0-9]+)*-\d+[a-z0-9]*", " ", t)   # 型号：zf12b-126、sm6-24、nm1-63
    t = re.sub(r"[_:]\d+(?::\d+)+|\b0\d{4,}\b", " ", t)                          # 信号编号 _:090413:25 等代码
    t = re.sub(r"(?m)^\s*\d+(?:\.\d+)+\s+(?=\D)", " ", t)                         # 行首多级步骤号 1.1 / 2.1
    t = CLAUSE_RE.sub(" ", t)
    t = re.sub(r"[零一二两三四五六七八九十百]+(?=\s*(?:个月|年|月|次|天|周|小时|分钟|秒|台|只|个|倍))",
               lambda m: str(cn2num(m.group(0))) if cn2num(m.group(0)) is not None else m.group(0), t)
    t = re.sub(r"(?m)^\s*(?:\d+[.、)](?!\d)|[(（]\d+[)）])\s*", " ", t)          # 行首步骤编号
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)                                   # 1,000 -> 1000
    t = re.sub(r"(?<![a-z])l(?=\s*(?:年|次|个月|月|天|h\b))", "1", t)            # OCR：l年 -> 1年
    t = re.sub(rf"[(（]?\s*({NUM})\s*±\s*({NUM})\s*[)）]?\s*({UNIT_RE})",          # (6±2)年 -> 6年 ±2年
               lambda m: f"{m.group(1)}{m.group(3)} ±{m.group(2)}{m.group(3)}", t)
    t = t.replace("±", " ")
    t = re.sub(rf"[(（]\s*({NUM})\s*(~|至|到|-)\s*({NUM})\s*[)）]\s*(?=(?:{UNIT_RE}))", r"\1~\3 ", t)   # (1~2) h -> 1~2 h
    return t

def _val(s: str) -> float:
    s = s.replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)[×x*]10(?:\^|\*\*)?([-]?\d+)", s)
    return float(m.group(1)) * 10 ** int(m.group(2)) if m else float(s)

def _unit(u: str | None):
    if not u:
        return None, 1.0
    for rx, dim, f in UNITS:
        if re.fullmatch(rx, u, re.I):
            return dim, f
    return None, 1.0

@dataclass(frozen=True)
class Q:
    raw: float          # 原单位下的数值
    dim: str | None
    base: float | None  # 基准单位值
    u: str = ""         # 原单位写法（仅显示用）
    cell: bool = False  # 裸数值是否位于表格单元格/比较符或范围符之后（可视为“带表头单位的取值”）

def quantities(text: str) -> list[Q]:
    out = []
    t = normalize(text)
    for m in QTY_RE.finditer(t):
        a, ua, b, ub = m.groups()
        pre = t[max(0, m.start() - 3):m.start()].strip()[-1:] if m.start() else ""
        post = t[m.end():m.end() + 3].strip()[:1]
        cell = pre in ("|", "≤", "≥", "<", ">", "~", "=") or post in ("|", "(", "（") or bool(b)
        u = ua or ub                                         # 3~20 μl/l：单位作用于两端
        for num, uu in ((a, ua or (ub if b else None)), (b, ub or ua)):
            if num is None:
                continue
            try:
                v = _val(num)
            except ValueError:
                continue
            dim, f = _unit(uu)
            out.append(Q(v, dim, v * f if dim else None, (uu or "") if dim else "", cell))
    return out

EXPLICIT = re.compile(rf"单位[:：为]?\s*({UNIT_RE})|\bin\s+({UNIT_RE})\b", re.I)

def explicit_units(text: str) -> set:
    """“单位：V”“interval in years”这类整段声明的单位：其后的裸数值都按该单位理解"""
    t = normalize(text)
    return {_unit(next(g for g in m.groups() if g))[0] for m in EXPLICIT.finditer(t)} - {None}

def unit_mentions(text: str) -> set:
    t = normalize(text)
    return {_unit(next(g for g in m.groups() if g))[0] for m in UNIT_MENTION.finditer(t)} - {None}

def _eq(x, y):
    return abs(x - y) <= 1e-9 + 1e-6 * max(abs(x), abs(y))

def supported(q: Q, src: list[Q], src_dims: set, explicit: set = frozenset()) -> bool:
    if q.dim is None:
        return any(_eq(q.raw, s.raw) for s in src)
    if any(s.dim == q.dim and _eq(q.base, s.base) for s in src):
        return True
    bare = any(s.dim is None and (s.cell or q.dim in explicit) and _eq(q.raw, s.raw) for s in src)   # 表格单元格 / “≤ 300（灭弧气室）” 这类裸数值
    return bare and (q.dim in src_dims or not src_dims)

def _skip(q: Q) -> bool:
    if q.dim in ("times", "count") and q.raw <= 1:           # “一次/每年一次/1台”多为措辞，不当作数值断言
        return True
    return q.dim is None and float(q.raw).is_integer() and q.raw < 10

SENT_RE = re.compile(r"[^。；;!?\n]+[。；;!?\n]?(?:\s*\[\d+(?:\s*[,，、]\s*\d+)*\])*")
CITE_RE = re.compile(r"\[(\d+(?:\s*[,，、]\s*\d+)*)\]")

def _cites(sent: str, n: int) -> list[int]:
    out = []
    for g in CITE_RE.findall(sent):
        out += [int(x) for x in re.split(r"[,，、\s]+", g) if x.isdigit() and 0 < int(x) <= n]
    return sorted(set(out))

def fmt(q: Q) -> str:
    return f"{q.raw:g}{q.u}"

def check(answer: str, hits: list[dict]) -> list[str]:
    """返回告警列表（与 rag.support_check 同格式）"""
    texts = [h.get("text", "") for h in hits]
    srcq = [quantities(t) for t in texts]
    dims = [{q.dim for q in qs if q.dim} | unit_mentions(t) for qs, t in zip(srcq, texts)]
    expl = [explicit_units(t) for t in texts]
    warns, seen = [], set()
    for sent in SENT_RE.findall(answer):
        cites = _cites(sent, len(hits))
        if not cites:
            continue
        for q in quantities(sent):
            if _skip(q) or (sent, q.raw, q.dim) in seen:
                continue
            seen.add((sent, q.raw, q.dim))
            pool = [x for i in cites for x in srcq[i - 1]]
            pd = set().union(*[dims[i - 1] for i in cites])
            pe = set().union(*[expl[i - 1] for i in cites])
            if supported(q, pool, pd, pe):
                continue
            other = [i + 1 for i in range(len(hits)) if i + 1 not in cites and supported(q, srcq[i], dims[i], expl[i])]
            warns.append(f"“{fmt(q)}”不在引用 {cites} 中" + (f"，但见于资料 {other}（引用可能错配）" if other else "（数值无出处，可能编造）"))
    return warns
