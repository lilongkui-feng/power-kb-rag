# pytest：python -m pytest tests/test_numcheck.py -q
import os, sys, pytest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
import numcheck as n

# ---- 单元测试（自造文本，不依赖知识库原文） ----
def q(text):
    return [(x.raw, x.dim, x.base) for x in n.quantities(text)]

def test_units_and_ranges():
    assert (0.35, "Pa", 350000.0) in q("压力 0.35MPa")
    assert (3.0, "ppm", 3.0) in q("3～20 μL/L") and (20.0, "ppm", 20.0) in q("3～20 μL/L")
    assert (2.0, "month", 24.0) in q("两年一次")
    assert (1500.0, "V", 1500.0) in q("1.5×10³ V")
    assert (4.0, "month", 48.0) in q("every 4 years")
    assert (1.0, "s", 3600.0) in q("隔(1~2) h 后")

def test_ignore_codes():
    assert q("按 DL/T 724-2021 第 6.1.3 条") == []

def _chk(ans, *texts):
    return n.check(ans, [{"text": t} for t in texts])

def test_le_300_case():                      # README 中提到的“≤ 300”误报
    assert _chk("湿度不大于300μL/L[1]。", "| 湿度 | μL/L | ≤ 300（灭弧气室） ≤ 500（非灭弧气室） |") == []

def test_table_header_unit():
    assert _chk("检测值为3～20μL/L时需复测[1]。", "| 气室 | 故障组分（μL/L） |\n| 灭弧气室 | 3～20 |") == []

def test_unit_conversion():
    assert _chk("额定电压 40500V[1]。", "额定电压 40.5 kV") == []
    assert _chk("压力 350kPa[1]。", "压力 0.35 MPa") == []

def test_fabricated_flagged():
    w = _chk("压力 0.45MPa[1]。", "压力 0.35 MPa")
    assert w and "0.45" in w[0]
    w = _chk("每 3 年检查一次[1]。", "every 4 years")
    assert w

def test_once_not_flagged():
    assert _chk("至少每4年检查一次[1]。", "inspection at least every 4 years") == []

def test_mismatch_hint():
    w = _chk("湿度不大于150μL/L[1]。", "无关文字 10 kV", "湿度 ≤ 150 μL/L")
    assert w and "错配" in w[0]

# ---- 回归集（需要本地 chunks 文件；没有则跳过） ----
def test_regression():
    from tests.numcheck_eval import evaluate, load_chunks
    if not load_chunks():
        pytest.skip("本地没有 chunks 文件（不入库，需先 build_v2.py）")
    r, _ = evaluate()
    fp_old = r["fp_old"][0] / max(1, r["fp_old"][1]); fp_new = r["fp_new"][0] / max(1, r["fp_new"][1])
    miss_new = r["miss_new"][0] / max(1, r["miss_new"][1])
    assert fp_new < fp_old * 0.3, r          # 误报至少降 70%
    assert miss_new <= 0.15, r               # 漏报率不超过 15%
