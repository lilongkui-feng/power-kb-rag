# 打包 /workspace/power_kb.zip（系统无 zip 命令）。排除环境/索引/缓存/原始文档，包含 paddle/paddle_worker.py
import os, zipfile
ROOT = "/workspace/power_kb"; DST = "/workspace/power_kb.zip"
EX_DIRS = {".venv", "chroma_db", "bm25_index", "emb_cache", ".ocr_cache", "__pycache__", ".rerank_cache", "docx_test", "ocr_out", "hf_cache", ".cache"}
EX_EXT = {".pdf", ".docx", ".pyc", ".pkl"}
n = 0
with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
    for dp, dns, fns in os.walk(ROOT):
        rel = os.path.relpath(dp, ROOT)
        dns[:] = [d for d in dns if d not in EX_DIRS and not d.endswith("_cache") and not (rel == "uploads" and d == "files")
                  and not (rel == "output" and d == "eval_cache")]
        for f in fns:
            if f == ".env" or os.path.splitext(f)[1].lower() in EX_EXT or f.endswith(".log") or f.startswith(".paddle_worker"):
                continue
            z.write(os.path.join(dp, f), os.path.join("power_kb", rel, f) if rel != "." else os.path.join("power_kb", f)); n += 1
names = zipfile.ZipFile(DST).namelist()
assert "power_kb/paddle/paddle_worker.py" in names
print(n, "files", round(os.path.getsize(DST) / 1e6, 1), "MB")
