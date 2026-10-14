# 部署文件静态检查：compose 不写死 LLM 地址、ollama 可选、构建源参数贯通到 Dockerfile 的每条 pip 安装
import os, re
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class _L(yaml.SafeLoader):
    pass
_L.add_multi_constructor("!", lambda loader, tag, node: None)    # compose 专用标签（!reset / !override）
def _y(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return yaml.load(f, Loader=_L)
def _t(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()

def test_compose_llm_env_uses_defaults_not_hardcoded():
    env = _y("docker-compose.yml")["services"]["api"]["environment"]
    assert env["LOCAL_LLM_URL"] == "${LOCAL_LLM_URL:-http://ollama:11434/v1}"
    assert env["LOCAL_LLM_MODEL"].startswith("${LOCAL_LLM_MODEL:-")
    assert env["LLM_BASE_URL"] == "${LLM_BASE_URL:-}"          # 默认空：不会让 custom 档误指 ollama
    h = _y("docker-compose.hostnet.yml")["services"]["api"]["environment"]
    assert h["LOCAL_LLM_URL"].startswith("${LOCAL_LLM_URL:-") and h["LLM_BASE_URL"] == "${LLM_BASE_URL:-}"

def test_ollama_optional_profile():
    s = _y("docker-compose.yml")["services"]
    assert s["ollama"]["profiles"] == ["ollama"] and s["ollama-pull"]["profiles"] == ["ollama"]
    assert s["api"]["depends_on"]["ollama"]["required"] is False

def test_build_args_passed_and_declared():
    args = _y("docker-compose.yml")["x-app"]["build"]["args"]
    df = _t("Dockerfile")
    for a in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "TORCH_INDEX_URL", "APT_MIRROR", "PIP_MIRROR"):
        assert a in args and args[a].startswith("${" + a), a
        assert re.search(rf"^ARG {a}=", df, re.M), f"Dockerfile 缺 ARG {a}"
    pip_lines = [l for l in re.split(r"(?<!\\)\n", df) if "pip install" in l and "venv" not in l]
    assert len(pip_lines) == 2
    for l in pip_lines:
        assert "IDX" in l, f"pip 安装行未使用镜像源：{l[:80]}"

def test_env_example_documents_new_vars():
    e = _t(".env.example")
    for v in ("LOCAL_LLM_URL=", "LOCAL_LLM_MODEL=", "PIP_INDEX_URL=", "APT_MIRROR=", "COMPOSE_PROFILES=", "KB_STREAMING="):
        assert v in e, v
