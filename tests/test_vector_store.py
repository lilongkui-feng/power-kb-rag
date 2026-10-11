# 向量库接口测试：ChromaStore 与 MilvusStore（Milvus Lite 临时文件）跑同一套用例
import os, sys
import numpy as np, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import vector_store as vs

BACKENDS = ["chroma", "milvus"] + (["milvus_standalone"] if os.environ.get("KB_TEST_MILVUS_URI") else [])   # 例：KB_TEST_MILVUS_URI=http://127.0.0.1:19530

@pytest.fixture(scope="module", params=BACKENDS)
def store(request, tmp_path_factory):
    d = tmp_path_factory.mktemp(request.param)
    if request.param == "chroma":
        os.environ["CHROMA_DIR"] = str(d); config.reload_settings(); vs._chroma_client = None
        s = vs.get_store("pytest_vs", create=True, backend_name="chroma")
    elif request.param == "milvus_standalone":
        s = vs.get_store("pytest_vs", create=True, backend_name="milvus", uri=os.environ["KB_TEST_MILVUS_URI"])
        if s.count():
            s.drop(); vs.forget("pytest_vs"); s = vs.get_store("pytest_vs", create=True, backend_name="milvus", uri=os.environ["KB_TEST_MILVUS_URI"])
    else:
        s = vs.get_store("pytest_vs", create=True, backend_name="milvus", uri=str(d / "t.db"))
    rng = np.random.default_rng(1); V = rng.normal(size=(8, vs.DIM)).astype(np.float32); V /= np.linalg.norm(V, axis=1, keepdims=True)
    ids = [f"c{i}" for i in range(8)]
    metas = [{"chunk_id": ids[i], "source": "A.pdf" if i < 4 else "B 手册.pdf", "page_start": i, "chunk_type": "table_row" if i % 2 else "text",
              "lang": "zh", "heading_path": f"第{i}章"} for i in range(8)]
    s.upsert(ids, V, [f"正文 {i}" for i in range(8)], metas)
    s.V = V
    yield s
    s.drop(); vs.forget("pytest_vs")
    if request.param == "chroma":
        os.environ.pop("CHROMA_DIR", None); config.reload_settings(); vs._chroma_client = None

def test_count_sources(store):
    assert store.count() == 8
    assert store.list_sources() == {"A.pdf": 4, "B 手册.pdf": 4}

def test_query_self_top1_cosine(store):
    r = store.query(store.V[5], 3)
    assert r[0]["id"] == "c5" and abs(r[0]["score"] - 1.0) < 1e-4 and r[0]["document"] == "正文 5"
    assert r[0]["metadata"]["source"] == "B 手册.pdf" and r[0]["metadata"]["page_start"] == 5
    assert [x["score"] for x in r] == sorted([x["score"] for x in r], reverse=True)

@pytest.mark.parametrize("where,expect", [
    ({"source": "A.pdf"}, {"c0", "c1", "c2", "c3"}),
    ({"source": {"$in": ["B 手册.pdf"]}}, {"c4", "c5", "c6", "c7"}),
    ({"source": "A.pdf", "chunk_type": "text"}, {"c0", "c2"}),
    ({"page_start": {"$gte": 6}}, {"c6", "c7"}),
    ({"$or": [{"page_start": {"$lt": 1}}, {"page_start": {"$gt": 6}}]}, {"c0", "c7"}),
    ({"source": {"$nin": ["A.pdf"]}, "chunk_type": {"$ne": "text"}}, {"c5", "c7"}),
])
def test_filters(store, where, expect):
    assert {h["id"] for h in store.query(store.V[0], 8, where)} == expect

def test_get_and_metadata(store):
    g = {x["id"]: x for x in store.get(["c1", "c3", "nope"])}
    assert set(g) == {"c1", "c3"} and g["c3"]["metadata"]["heading_path"] == "第3章"
    assert set(store.all_metadata()) == {f"c{i}" for i in range(8)}

def test_upsert_overwrite_and_delete(store):
    store.upsert(["c0"], store.V[:1], ["改写"], [{"chunk_id": "c0", "source": "A.pdf", "page_start": 0, "chunk_type": "text", "lang": "zh", "heading_path": "x"}])
    assert store.count() == 8 and store.get(["c0"])[0]["document"] == "改写"
    store.upsert(["tmp1", "tmp2"], store.V[:2], ["t", "t"], [{"chunk_id": "tmp1", "source": "C.pdf"}, {"chunk_id": "tmp2", "source": "C.pdf"}])
    assert store.count() == 10
    store.delete(ids=["tmp1"]); assert store.count() == 9
    store.delete(where={"source": "C.pdf"}); assert store.count() == 8 and "C.pdf" not in store.list_sources()

def test_all_vectors_roundtrip(store):
    got = [(i, np.asarray(v)) for ids, emb, _, _ in store.all_vectors(batch=3) for i, v in zip(ids, emb)]
    assert len(got) == 8
    d = dict(got); assert np.allclose(d["c4"], store.V[4], atol=1e-5)

def test_where_to_expr():
    e = vs.where_to_expr({"source": {"$in": ['a"b.pdf', "c"]}, "page_start": {"$gte": 3}, "x": True})
    assert e == '(source in ["a\\"b.pdf", "c"]) and (page_start >= 3) and (x == true)'
    with pytest.raises(ValueError):
        vs.where_to_expr({"a": {"$regex": "x"}})
