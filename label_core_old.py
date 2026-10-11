# 为 eval_set_50 的 key_points 标 core（下标列表），由 DeepSeek-V3 建议，人工复核后写入 evalset/core_old.json
import json, re
from concurrent.futures import ThreadPoolExecutor
import rag
cfg = rag.llm_config("siliconflow")
items = [json.loads(l) for l in open("eval_set_50.jsonl", encoding="utf-8") if not json.loads(l)["id"].startswith("R")]
SYS = "你是评测集审核员。给出问题和评分要点（带编号），判断哪些是回答该问题必须包含的核心要点（core：问题直接问到的数值/条件/关键步骤/结论），其余为次要（minor：补充说明、例外、附带信息）。至少 1 条 core。只输出 JSON：{\"core\": [编号...]}"
def one(it):
    kp = "\n".join(f"{i}. {k}" for i, k in enumerate(it["key_points"]))
    t, _ = rag.call_llm([{"role": "system", "content": SYS}, {"role": "user", "content": f"问题：{it['question']}\n要点：\n{kp}"}], cfg, max_tokens=60, temperature=0)
    try:
        c = [int(x) for x in json.loads(re.search(r"\{.*\}", t, re.S).group(0))["core"] if 0 <= int(x) < len(it["key_points"])]
    except Exception:
        c = list(range(len(it["key_points"])))
    return it["id"], c or list(range(len(it["key_points"])))
with ThreadPoolExecutor(4) as ex:
    res = dict(ex.map(one, items))
json.dump(res, open("evalset/core_old.json", "w"), ensure_ascii=False, indent=0)
for it in items:
    print(it["id"], it["question"][:40], "| CORE:", "；".join(it["key_points"][i][:28] for i in res[it["id"]]), "| minor:", "；".join(k[:20] for i, k in enumerate(it["key_points"]) if i not in res[it["id"]]))
