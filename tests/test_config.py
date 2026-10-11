# 配置：优先级（默认 < yaml < .env < 环境变量）、密钥只许来自环境变量/.env、校验错误不回显值、脱敏摘要
import os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from errors import ConfigError

@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in list(os.environ):
        if k.lower() in config.Settings.model_fields or k == "CONFIG_FILE":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "none.yaml"))
    return monkeypatch, tmp_path

def S(tmp, yaml_text=None, env_text=None):
    if yaml_text is not None:
        (tmp / "c.yaml").write_text(yaml_text, encoding="utf-8"); os.environ["CONFIG_FILE"] = str(tmp / "c.yaml")
    ef = tmp / "t.env"
    ef.write_text(env_text or "", encoding="utf-8")
    try:
        return config.Settings(_env_file=str(ef))
    except Exception as e:
        raise e

def test_defaults(env):
    _, t = env
    s = S(t)
    assert s.rerank_top_n == 20 and s.vector_store == "chroma" and s.llm_fallback == "retrieval" and s.rag_refuse_below == 0.3

def test_priority_yaml_dotenv_env(env):
    mp, t = env
    y = "retrieval:\n  rerank_top_n: 30\n  top_k: 7\nlogging:\n  log_level: debug\n"
    assert S(t, y).rerank_top_n == 30 and S(t, y).log_level == "DEBUG"               # yaml > 默认（分节拍平，大小写规范化）
    s = S(t, y, "RERANK_TOP_N=40\n")
    assert s.rerank_top_n == 40 and s.top_k == 7                                       # .env > yaml
    mp.setenv("RERANK_TOP_N", "50")
    assert S(t, y, "RERANK_TOP_N=40\n").rerank_top_n == 50                             # 环境变量 > .env

def test_empty_env_ignored_and_off(env):
    mp, t = env
    mp.setenv("SILICONFLOW_MODEL", ""); mp.setenv("RAG_REFUSE_BELOW", "off")
    s = S(t)
    assert s.siliconflow_model == "deepseek-ai/DeepSeek-V3" and s.rag_refuse_below is None

@pytest.mark.parametrize("y", ["siliconflow_api_key: sk-abcdefgh1234\n", "llm:\n  openai_api_key: x\n",
                               "api:\n  kb_api_token: t0ps3cret\n", "foo_secret: x\n", "nested:\n  password: p\n"])
def test_secret_in_yaml_rejected(env, y):
    _, t = env
    with pytest.raises(ConfigError) as ei:
        S(t, y)
    assert "不允许" in str(ei.value) and "sk-abcdefgh1234" not in str(ei.value) and "t0ps3cret" not in str(ei.value)

def test_unknown_and_invalid(env):
    _, t = env
    with pytest.raises(ConfigError, match="未知配置项"):
        S(t, "rerank_topn: 3\n")
    with pytest.raises(ConfigError, match="不是合法的 YAML"):
        S(t, "a: [1,\n")
    t2 = t / "x"; t2.mkdir()
    os.environ["CONFIG_FILE"] = str(t2 / "none.yaml"); os.environ["LOG_FORMAT"] = "xml"
    try:
        with pytest.raises(ConfigError) as ei:
            config._load()
        assert "log_format" in str(ei.value) and "xml" not in str(ei.value).split("：", 1)[1].split("log_format")[0]
    finally:
        os.environ.pop("LOG_FORMAT")

def test_secrets_from_env_masked(env):
    mp, t = env
    mp.setenv("SILICONFLOW_API_KEY", "sk-live-0123456789abcdef")
    s = S(t, None, "KB_API_TOKEN=tok-from-dotenv-123\n")
    assert s.secret("siliconflow_api_key") == "sk-live-0123456789abcdef" and s.secret("kb_api_token") == "tok-from-dotenv-123"
    summ = str(s.summary()); rep = repr(s)
    for v in ("sk-live-0123456789abcdef", "tok-from-dotenv-123"):
        assert v not in summ and v not in rep
    assert s.summary()["siliconflow_api_key"] == "已设置" and s.summary()["openai_api_key"] == "未设置"
    assert set(s.secret_values()) == {"sk-live-0123456789abcdef", "tok-from-dotenv-123"}

def test_example_yaml_valid_and_secret_free(env):
    mp, t = env
    p = os.path.join(config.HERE, "config.example.yaml")
    mp.setenv("CONFIG_FILE", p)
    s = config.Settings(_env_file=str(t / "none.env"))
    assert s.kb_api_port == 8000 and s.log_format == "text"

def test_retrieval_params_wired(monkeypatch):
    """RERANK_TOP_N / RERANK_BETA / HYBRID_ALPHA / RETRIEVAL_MODE 实际进入检索调用参数"""
    import rag
    monkeypatch.setenv("RERANK_TOP_N", "12"); monkeypatch.setenv("HYBRID_ALPHA", "0.3")
    config.reload_settings()
    try:
        d = rag.retrieval_defaults()
        assert d == {"mode": "hybrid", "alpha": 0.3, "rerank_top_n": 12, "rerank_beta": 0.8}
    finally:
        monkeypatch.delenv("RERANK_TOP_N"); monkeypatch.delenv("HYBRID_ALPHA"); config.reload_settings()
