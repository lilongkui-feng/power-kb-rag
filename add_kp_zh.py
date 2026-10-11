# 为 eval_set_v3 中缺 key_points_zh 的英文题生成中文要点（逐条对应、保留数值/型号/英文术语），写回 eval_set_v3.jsonl
import json, re
from concurrent.futures import ThreadPoolExecutor
import rag
cfg = rag.llm_config("siliconflow")
rows = [json.loads(l) for l in open("eval_set_v3.jsonl", encoding="utf-8")]
need = [r for r in rows if r["lang"] == "en" and r["category"] != "拒答" and not r.get("key_points_zh")]
SYS = "把下列英文评分要点逐条译成简体中文，条数和顺序不变；数值、单位、型号、按钮/菜单名等保留原文（可在中文后括注英文）。只输出 JSON 数组。"
def one(r):
    t, _ = rag.call_llm([{"role": "system", "content": SYS}, {"role": "user", "content": json.dumps(r["key_points"], ensure_ascii=False)}], cfg, max_tokens=600, temperature=0)
    zh = json.loads(re.search(r"\[.*\]", t, re.S).group(0))
    assert len(zh) == len(r["key_points"])
    return r["id"], zh
with ThreadPoolExecutor(4) as ex:
    res = dict(ex.map(one, need))
for r in rows:
    if r["id"] in res:
        r["key_points_zh"] = res[r["id"]]
with open("eval_set_v3.jsonl", "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(len(res), "题补了中文要点"); [print(k, v[:2]) for k, v in list(res.items())[:4]]
