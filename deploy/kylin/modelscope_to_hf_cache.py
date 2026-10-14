#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从魔搭 ModelScope 直接下载模型文件，存成 HuggingFace 缓存布局（无需安装 modelscope / huggingface_hub）。

适用：受限网络（hf-mirror / huggingface.co 不通、ModelScope 通），以及 Python 3.7 这类老系统
（新版 modelscope 要求 ≥3.8，老版依赖 pyarrow 等大包装不上）。只用标准库，兼容 Python 3.7+。

用法：
  python3 modelscope_to_hf_cache.py --cache /opt/hf_cache                    # 默认下载 BAAI/bge-m3 与 BAAI/bge-reranker-v2-m3
  python3 modelscope_to_hf_cache.py --cache /opt/hf_cache --model BAAI/bge-m3 --exclude 'onnx/*' --exclude 'imgs/*'
  nohup python3 modelscope_to_hf_cache.py --cache /opt/hf_cache > /root/ms_dl.log 2>&1 &     # 长任务后台跑，SSH 断开不受影响
生成布局：<cache>/hub/models--BAAI--bge-m3/{refs/main, snapshots/<revision>/<文件>}，
容器里设 HF_HOME=<cache 挂载点>、HF_HUB_OFFLINE=1 即可离线加载（sentence-transformers / transformers 认这个布局）。
断点续传：未完成的文件保存为 *.incomplete，重跑时用 HTTP Range 续传；已完成且大小（和 sha256，若接口提供）一致的文件跳过。
"""
from __future__ import print_function
import argparse, fnmatch, hashlib, json, os, sys, time
try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    from urllib.parse import quote
except ImportError:                                   # pragma: no cover
    sys.exit("需要 Python 3")

API = "https://www.modelscope.cn/api/v1/models"
DEFAULT_MODELS = ["BAAI/bge-m3", "BAAI/bge-reranker-v2-m3"]
DEFAULT_EXCLUDE = ["onnx/*", "imgs/*", "assets/*", "*.jpg", "*.png", "*.onnx", "*.onnx_data", ".gitattributes"]   # bge-m3 的 onnx/ 有 2 GB+，本项目用不到
UA = {"User-Agent": "powerkb-ms-downloader/1.0"}


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a)
    sys.stdout.flush()


def get_json(url, retries=5, timeout=30):
    last = None
    for i in range(retries):
        try:
            with urlopen(Request(url, headers=UA), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError) as e:
            last = e
            log("  请求失败（%s），%ds 后重试 %d/%d" % (e, 2 ** i, i + 1, retries))
            time.sleep(2 ** i)
    raise RuntimeError("多次重试仍失败：%s（%s）" % (url, last))


def list_files(model, revision):
    url = "%s/%s/repo/files?Revision=%s&Recursive=true" % (API, model, quote(revision))
    d = get_json(url)
    if d.get("Code") != 200:
        raise RuntimeError("列文件失败：%s" % (d.get("Message") or d))
    files = [f for f in d["Data"]["Files"] if f.get("Type") == "blob"]
    rev = next((f.get("Revision") for f in d["Data"]["Files"] if f.get("Revision")), None) or revision
    return files, rev


def excluded(path, pats):
    return any(fnmatch.fnmatch(path, p) for p in pats)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(model, revision, fpath, dest, size, sha, retries=20):
    """下载单个文件到 dest，支持断点续传；返回 True=新下载，False=已存在跳过"""
    if os.path.exists(dest) and (not size or os.path.getsize(dest) == size):
        return False
    tmp = dest + ".incomplete"
    url = "%s/%s/repo?Revision=%s&FilePath=%s" % (API, model, quote(revision), quote(fpath))
    for i in range(retries):
        have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        if size and have > size:
            os.remove(tmp); have = 0
        if size and have == size:
            break
        hdr = dict(UA)
        if have:
            hdr["Range"] = "bytes=%d-" % have
        try:
            with urlopen(Request(url, headers=hdr), timeout=60) as r:
                if have and r.status != 206:          # 服务器不支持 Range → 从头下
                    have = 0
                mode = "ab" if have else "wb"
                t0, got = time.time(), 0
                with open(tmp, mode) as f:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b); got += len(b)
                        if size and got % (64 << 20) < (1 << 20):
                            log("    %s %.0f%%（%.1f MB/s）" % (fpath, 100.0 * (have + got) / size, got / 1e6 / max(time.time() - t0, 1e-3)))
            if not size:
                break
        except (HTTPError, URLError, OSError) as e:
            wait = min(60, 2 ** i)
            log("    %s 中断（%s），%ds 后续传 %d/%d" % (fpath, e, wait, i + 1, retries))
            time.sleep(wait)
    else:
        raise RuntimeError("下载失败：%s" % fpath)
    if size and os.path.getsize(tmp) != size:
        raise RuntimeError("大小不符：%s（%d ≠ %d）" % (fpath, os.path.getsize(tmp), size))
    if sha and sha256_of(tmp) != sha:
        os.remove(tmp)
        raise RuntimeError("sha256 校验失败：%s（已删除，重跑即可）" % fpath)
    os.rename(tmp, dest)
    return True


def fetch_model(model, cache, revision, exclude, dry_run=False):
    files, rev = list_files(model, revision)
    files = [f for f in files if not excluded(f["Path"], exclude)]
    total = sum(int(f.get("Size") or 0) for f in files)
    log("%s @ %s：%d 个文件，共 %.2f GB" % (model, rev[:12], len(files), total / 1e9))
    repo = os.path.join(cache, "hub", "models--" + model.replace("/", "--"))
    snap = os.path.join(repo, "snapshots", rev)
    if dry_run:
        for f in files:
            print("  %12d  %s" % (int(f.get("Size") or 0), f["Path"]))
        return
    for f in files:
        dest = os.path.join(snap, *f["Path"].split("/"))
        if not os.path.isdir(os.path.dirname(dest)):
            os.makedirs(os.path.dirname(dest))
        new = download(model, revision, f["Path"], dest, int(f.get("Size") or 0), f.get("Sha256") or "")
        log("  %s %s" % ("✔ 下载" if new else "· 已有", f["Path"]))
    refs = os.path.join(repo, "refs")
    if not os.path.isdir(refs):
        os.makedirs(refs)
    with open(os.path.join(refs, "main"), "w") as fh:
        fh.write(rev)
    log("完成 %s → %s" % (model, snap))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True, help="HF 缓存根目录（即 HF_HOME；文件写到 <cache>/hub/）。不要放在 /root 下：容器内 uid 1000 进不去")
    ap.add_argument("--model", action="append", help="ModelScope 模型 ID，可多次；默认 %s" % " ".join(DEFAULT_MODELS))
    ap.add_argument("--revision", default="master")
    ap.add_argument("--exclude", action="append", help="排除的 glob（可多次）；默认 %s" % " ".join(DEFAULT_EXCLUDE))
    ap.add_argument("--dry-run", action="store_true", help="只列出要下载的文件")
    a = ap.parse_args(argv)
    for m in a.model or DEFAULT_MODELS:
        fetch_model(m, a.cache, a.revision, a.exclude if a.exclude is not None else DEFAULT_EXCLUDE, a.dry_run)
    if not a.dry_run:
        log("全部完成。目录可读性：chmod -R a+rX %s（容器内 uid 1000 需要可读）" % a.cache)


if __name__ == "__main__":
    main()
