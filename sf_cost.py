# 统计各运行的 token 用量与估算费用（按硅基流动国内站公开价，元/百万 token；以账单为准）
import glob, json, os, sys
PRICE = {"deepseek-ai/DeepSeek-V3": (2.0, 8.0), "Qwen/Qwen2.5-72B-Instruct": (4.13, 4.13)}
def usage(run_dir):
    cfg = json.load(open(os.path.join(run_dir, "run_config.json")))["config"]
    import evaluate
    pin = pout = n = 0
    ids = {json.loads(l)["id"] for l in open(os.path.join(run_dir, "per_item.jsonl"), encoding="utf-8")}   # 同配置的运行共用缓存文件：只统计本运行的题
    for l in open(evaluate.cache_path(cfg), encoding="utf-8"):
        r = json.loads(l)
        if r["id"] not in ids:
            continue
        u = (r.get("gen") or {}).get("usage") or {}
        pin += u.get("prompt_tokens", 0); pout += u.get("completion_tokens", 0); n += 1
    pi, po = PRICE.get(cfg["model"], (0, 0))
    return {"model": cfg["model"], "n": n, "prompt_tokens": pin, "completion_tokens": pout, "cost_cny": round(pin / 1e6 * pi + pout / 1e6 * po, 3)}
if __name__ == "__main__":
    out = {}
    for pre in sys.argv[1:]:
        d = sorted(glob.glob(f"output/eval_runs/{pre}_2*"))[-1]
        out[pre] = usage(d); print(pre, out[pre])
    json.dump(out, open("output/sf_usage.json", "w"), ensure_ascii=False, indent=1)
