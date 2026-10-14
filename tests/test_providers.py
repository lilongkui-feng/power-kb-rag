# LLM provider 解析：custom（LLM_BASE_URL 网关）与 local / 云端档的优先级（不发任何网络请求）
import os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config, rag
from errors import ProviderNotReady

@pytest.fixture
def mk(monkeypatch, tmp_path):
    for k in list(os.environ):
        if k.lower() in config.Settings.model_fields or k == "CONFIG_FILE":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "none.yaml"))
    def make(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        ef = tmp_path / "empty.env"; ef.write_text("")
        s = config.Settings(_env_file=str(ef))
        monkeypatch.setattr(rag, "settings", lambda: s)
        monkeypatch.setattr(rag, "secret", lambda n: s.secret(n))
        return s
    return make

def test_default_local_without_base_url(mk):
    mk()
    c = rag.llm_config(None)
    assert c["provider"] == "local" and c["base_url"] == "http://127.0.0.1:11434/v1" and c["model"] == "qwen2.5:3b-instruct"
    assert "custom" not in rag.providers() and rag.default_provider() == "local"

def test_custom_from_env(mk):
    mk(LLM_BASE_URL="http://gw.example:7863/v1/", LLM_MODEL="cn:glm-5.3-flash", LLM_API_KEY="tok123456")
    c = rag.llm_config("custom")
    assert c == {"provider": "custom", "base_url": "http://gw.example:7863/v1", "model": "cn:glm-5.3-flash", "api_key": "tok123456"}
    assert rag.llm_config(None)["provider"] == "custom" and rag.default_provider() == "custom"
    ok, info = rag.provider_ready("custom")
    assert ok and "gw.example" in info and "glm-5.3-flash" in info and "tok123456" not in info

def test_explicit_local_ignores_llm_base_url(mk):
    mk(LLM_BASE_URL="http://gw.example/v1", LLM_MODEL="m1", LOCAL_LLM_URL="http://ollama:11434/v1", LOCAL_LLM_MODEL="qwen2.5:7b")
    c = rag.llm_config("local")
    assert c["provider"] == "local" and c["base_url"] == "http://ollama:11434/v1" and c["model"] == "qwen2.5:7b"

def test_cloud_provider_keeps_official_url(mk):
    mk(LLM_BASE_URL="http://gw.example/v1", OPENAI_API_KEY="sk-test-123456")
    c = rag.llm_config("openai")
    assert c["base_url"] == "https://api.openai.com/v1" and c["api_key"] == "sk-test-123456"

def test_custom_without_base_url_not_ready(mk):
    mk()
    ok, info = rag.provider_ready("custom")
    assert not ok and "LLM_BASE_URL" in info
    with pytest.raises(ProviderNotReady):
        rag.llm_config("custom")

def test_custom_model_defaults_to_local_model(mk):
    mk(LLM_BASE_URL="http://gw.example/v1")
    assert rag.llm_config("custom")["model"] == "qwen2.5:3b-instruct"
    assert rag.llm_config("custom")["api_key"] == "ollama"       # 无 key 网关：占位

def test_legacy_llm_model_only_overrides_local(mk):
    mk(LLM_MODEL="qwen2.5:7b-instruct")
    c = rag.llm_config(None)
    assert c["provider"] == "local" and c["model"] == "qwen2.5:7b-instruct"

def test_api_provider_literal_includes_custom():
    import typing, api
    assert "custom" in typing.get_args(api.Provider)
