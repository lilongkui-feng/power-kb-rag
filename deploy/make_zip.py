# 打包 /workspace/power_kb.zip（系统无 zip 命令）。文件集合 = git 跟踪 + 未跟踪但未被 .gitignore 忽略的文件，
# 与仓库同一套规则：不含 .venv / 索引 / 模型缓存 / 原文 PDF/docx / 由原文生成的切块（chunks*.jsonl）/ data/ / milvus_db/ / .env
import os, subprocess, zipfile
ROOT = "/workspace/power_kb"; DST = "/workspace/power_kb.zip"
files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
                       capture_output=True, check=True).stdout.decode().split("\0")
files = sorted(f for f in files if f and os.path.isfile(os.path.join(ROOT, f)))
BAD = (".pdf", ".docx", ".doc", ".pkl", ".env")
bad = [f for f in files if f.lower().endswith(BAD) or os.path.basename(f).startswith("chunks") and f.endswith(".jsonl")
       or f.startswith(("data/", "milvus_db/", "chroma_db/", "bm25_index/", "emb_cache/"))]
assert not bad, f"这些文件不应打包，请检查 .gitignore：{bad[:10]}"
with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(os.path.join(ROOT, f), os.path.join("power_kb", f))
names = zipfile.ZipFile(DST).namelist()
assert "power_kb/paddle/paddle_worker.py" in names
key = os.environ.get("SILICONFLOW_API_KEY")
if key:
    with zipfile.ZipFile(DST) as z:
        assert not any(key.encode() in z.read(n) for n in names), "zip 中发现 API key"
print(len(files), "files", round(os.path.getsize(DST) / 1e6, 1), "MB")
