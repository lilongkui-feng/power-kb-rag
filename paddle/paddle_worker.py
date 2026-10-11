# -*- coding: utf-8 -*-
"""PaddleOCR / PP-StructureV3 常驻子进程（运行在独立 Python 3.11 环境 /workspace/paddle_env，主环境 3.13 无 paddle 轮子）
协议：stdin 每行一个 JSON 请求 {"image": "/path.png", "mode": "structure"|"ocr"}，stdout 每行一个 JSON 结果（坐标为像素）。
  ocr       -> {"boxes":[{"poly","text","conf"}], "secs"}
  structure -> 上述 boxes（整页 OCR）+ {"layout":[{"label","bbox","content"}], "tables":[{"bbox","html"}]}
启动成功后先输出一行 {"ready": true, "load_secs": ..}；内存峰值见 maxrss_mb。"""
import json, os, resource, sys, time, logging
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("OMP_NUM_THREADS", "4")
logging.disable(logging.WARNING)

def _out(d):
    d["maxrss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    sys.__stdout__.write(json.dumps(d, ensure_ascii=False) + "\n"); sys.__stdout__.flush()

def main():
    sys.stdout = sys.stderr                     # paddle 的打印全部转到 stderr，stdout 只走协议
    t = time.time()
    from paddleocr import PPStructureV3, PaddleOCR
    pp = PPStructureV3(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
                       use_seal_recognition=False, use_formula_recognition=False, use_chart_recognition=False,
                       use_region_detection=False, device="cpu")
    ocr = None
    _out({"ready": True, "load_secs": round(time.time() - t, 1)})
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        t = time.time()
        try:
            if req.get("mode") == "ocr":
                if ocr is None:
                    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, device="cpu")
                r = ocr.predict(req["image"])[0]
                boxes = [{"poly": [[float(x), float(y)] for x, y in p], "text": tx, "conf": float(sc)}
                         for p, tx, sc in zip(r["rec_polys"], r["rec_texts"], r["rec_scores"])]
                _out({"boxes": boxes, "secs": round(time.time() - t, 2)})
            else:
                r = pp.predict(req["image"])[0]
                o = r["overall_ocr_res"]
                boxes = [{"poly": [[float(x), float(y)] for x, y in p], "text": tx, "conf": float(sc)}
                         for p, tx, sc in zip(o["rec_polys"], o["rec_texts"], o["rec_scores"])]
                layout = [{"label": b.label, "bbox": [float(v) for v in b.bbox], "content": b.content or ""} for b in r["parsing_res_list"]]
                tables = []
                for tb in r["table_res_list"]:
                    cb = tb.get("cell_box_list")
                    tables.append({"bbox": _union(cb) if cb is not None and len(cb) else [0, 0, 0, 0], "html": tb["pred_html"]})
                # 表格 bbox 以版面块为准（cell_box_list 并集作兜底）
                tlay = [b for b in layout if b["label"] == "table"]
                for i, tb in enumerate(tables):
                    if i < len(tlay):
                        tb["bbox"] = tlay[i]["bbox"]
                _out({"boxes": boxes, "layout": layout, "tables": tables, "secs": round(time.time() - t, 2)})
        except Exception as e:                     # noqa
            _out({"error": repr(e), "secs": round(time.time() - t, 2)})

def _union(bs):
    bs = [list(map(float, b)) for b in bs]
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]

if __name__ == "__main__":
    main()
