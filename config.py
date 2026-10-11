# -*- coding: utf-8 -*-
"""集中配置（pydantic-settings）。优先级（高 → 低）：环境变量 > .env > config.yaml > 代码默认值。

- 字段名与环境变量同名（不区分大小写），旧的环境变量写法继续有效；值为空字符串视为未设置。
- config.yaml 只放非敏感参数，可以按小节分组（retrieval: / rag: / llm: …），加载时会拍平；位置由 CONFIG_FILE 指定，默认 <项目>/config.yaml。
- API Key / Token 只允许来自环境变量或 .env（SecretStr，日志和摘要里只显示“已设置/未设置”）；
  config.yaml 里出现 *_api_key / *token / secret / password 这类键直接报 ConfigError。
- 用法：from config import settings；settings().rerank_top_n；secret("siliconflow_api_key")
  命令行：python config.py（打印脱敏摘要并校验）| python config.py get kb_api_port
"""
from __future__ import annotations
import functools, os, re, sys
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from errors import ConfigError

HERE = Path(__file__).resolve().parent
SECRET_FIELDS = ("siliconflow_api_key", "deepseek_api_key", "openai_api_key", "xai_api_key", "llm_api_key", "kb_api_token", "milvus_token")
SECRET_KEY_RE = re.compile(r"(api_?key|token|secret|password|passwd)", re.I)

def _flatten(d: dict, out: dict | None = None) -> dict:
    out = {} if out is None else out
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            _flatten(v, out)
        else:
            out[str(k).lower()] = v
    return out

class YamlSource(PydanticBaseSettingsSource):
    """读取 config.yaml（可分节），拍平成字段；发现敏感键直接报错（不回显值）"""
    def __init__(self, settings_cls):
        super().__init__(settings_cls)
        p = os.environ.get("CONFIG_FILE") or str(HERE / "config.yaml")
        self.path = Path(p)
        self.data = {}
        if self.path.exists():
            try:
                raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                raise ConfigError(f"{self.path} 不是合法的 YAML：{str(e).splitlines()[0]}") from None
            if not isinstance(raw, dict):
                raise ConfigError(f"{self.path} 顶层必须是映射（key: value）")
            flat = _flatten(raw)
            bad = sorted(k for k in flat if k in SECRET_FIELDS or SECRET_KEY_RE.search(k))
            if bad:
                raise ConfigError(f"{self.path.name} 中不允许出现密钥类配置：{', '.join(bad)}。API Key / Token 只能放在环境变量或 .env 中")
            unknown = sorted(k for k in flat if k not in settings_cls.model_fields)
            if unknown:
                raise ConfigError(f"{self.path.name} 中有未知配置项：{', '.join(unknown)}（拼写错误？可用项见 config.example.yaml）")
            self.data = flat
    def get_field_value(self, field, field_name):
        return self.data.get(field_name), field_name, False
    def __call__(self) -> dict[str, Any]:
        return dict(self.data)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(HERE / ".env"), env_file_encoding="utf-8", env_ignore_empty=True,
                                      case_sensitive=False, extra="ignore", validate_default=True)

    # ---- 路径 / 索引 ----
    kb_method: str = Field("heading_v2", description="上传入库与 API 使用的切分方法/集合")
    kb_collection: str = "heading_v2"
    vector_store: Literal["chroma", "milvus"] = "chroma"
    chroma_dir: str = "chroma_db"
    milvus_uri: Optional[str] = Field(None, description="Milvus Lite 文件路径或 http://host:19530；默认 milvus_db/power_kb.db")
    milvus_index: Literal["HNSW", "FLAT", "AUTOINDEX", "IVF_FLAT"] = "HNSW"
    hf_home: Optional[str] = Field(None, description="HuggingFace 模型缓存目录（未设置时用 HF 默认 ~/.cache/huggingface）")
    hf_endpoint: Optional[str] = Field(None, description="HF 镜像，如 https://hf-mirror.com")
    # ---- 模型 / 检索 / 重排 ----
    bge_model: str = "BAAI/bge-m3"
    bge_device: Optional[str] = None
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    retrieval_mode: Literal["hybrid", "dense", "bm25"] = "hybrid"
    hybrid_alpha: float = Field(0.5, ge=0, le=1)
    rerank: bool = True
    rerank_top_n: int = Field(20, ge=1, le=100)
    rerank_beta: float = Field(0.8, ge=0, le=1)
    top_k: int = Field(5, ge=1, le=20)
    # ---- 切分（上传入库） ----
    chunk_max_size: int = Field(800, ge=100, le=5000)
    chunk_overlap: int = Field(50, ge=0, le=1000)
    # ---- OCR ----
    ocr_engine: Optional[Literal["paddle", "rapid"]] = None
    paddle_py: str = "/workspace/paddle_env/bin/python"
    # ---- RAG ----
    rag_prompt: Optional[Literal["p0", "p1", "p2", "p3"]] = Field(None, description="空 = 本地 p1、云端 p2")
    rag_expand: Literal["none", "neighbor", "parent"] = "none"
    rag_refuse_below: Optional[float] = Field(0.3, description="重排 Top-1 分低于此值直接拒答；off/none 关闭")
    rag_reflect: bool = False
    rag_numcheck: Literal["v1", "v2"] = "v2"
    rag_xlang: Optional[Literal["none", "dict", "llm", "cap", "mismatch", "auto", "auto_llm"]] = Field(None, description="空 = 云端 cap、本地 none")
    # ---- LLM provider（模型名 / 地址，非敏感） ----
    local_llm_url: str = "http://127.0.0.1:11434/v1"
    local_llm_model: str = "qwen2.5:3b-instruct"
    siliconflow_model: str = "deepseek-ai/DeepSeek-V3"
    deepseek_model: str = "deepseek-chat"
    openai_model: str = "gpt-4o-mini"
    xai_model: str = "grok-3-mini"
    llm_base_url: Optional[str] = Field(None, description="不指定 provider 时使用的 OpenAI 兼容地址")
    llm_model: Optional[str] = None
    qx_llm_provider: str = "local"
    qx_llm_model: str = "qwen2.5:3b-instruct"
    # ---- LLM 调用健壮性 ----
    llm_timeout: float = Field(180, gt=0, description="单次请求读超时（秒）")
    llm_connect_timeout: float = Field(10, gt=0)
    llm_max_retries: int = Field(5, ge=0, le=10, description="429 / 5xx / 网络错误的最大重试次数")
    llm_timeout_retries: int = Field(1, ge=0, le=5, description="超时单独计数的重试次数（超时代价高）")
    llm_backoff_base: float = Field(2.0, ge=0, description="退避：min(cap, base·2^attempt) 秒；遵守 Retry-After")
    llm_backoff_cap: float = Field(60.0, ge=0)
    llm_fallback: Literal["none", "local", "retrieval", "local_then_retrieval"] = Field(
        "retrieval", description="LLM 失败时：none=报错；local=云端失败改用本地模型；retrieval=返回仅检索结果；local_then_retrieval=先本地再检索")
    # ---- API 服务 ----
    kb_api_host: str = "127.0.0.1"
    kb_api_port: int = Field(8000, ge=1, le=65535)
    kb_api_url: str = Field("http://127.0.0.1:8000", description="前端访问 API 的地址")
    kb_cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    kb_max_upload_mb: int = Field(50, ge=1, le=2048)
    kb_max_concurrency: int = Field(2, ge=1, le=64)
    kb_preload: bool = True
    # ---- 日志 ----
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["text", "json"] = "text"
    log_dir: str = "logs"
    log_file: Optional[str] = Field("powerkb.log", description="空/none 关闭文件日志")
    log_max_bytes: int = Field(10 * 1024 * 1024, ge=1024)
    log_backup_count: int = Field(5, ge=0, le=100)
    log_questions: bool = Field(False, description="是否在日志中记录问句原文（默认只记长度和哈希）")
    # ---- 密钥：只允许来自环境变量 / .env ----
    siliconflow_api_key: Optional[SecretStr] = None
    deepseek_api_key: Optional[SecretStr] = None
    openai_api_key: Optional[SecretStr] = None
    xai_api_key: Optional[SecretStr] = None
    llm_api_key: Optional[SecretStr] = None
    kb_api_token: Optional[SecretStr] = None
    milvus_token: Optional[SecretStr] = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v):
        return v.upper() if isinstance(v, str) else v

    @field_validator("milvus_index", mode="before")
    @classmethod
    def _upper_idx(cls, v):
        return v.upper() if isinstance(v, str) else v

    @field_validator("rag_refuse_below", mode="before")
    @classmethod
    def _refuse(cls, v):
        if isinstance(v, str) and v.strip().lower() in ("off", "none", "null", "0", "false"):
            return None
        return v

    @field_validator("log_file", "milvus_uri", "hf_home", "hf_endpoint", "bge_device", "llm_base_url", "llm_model", mode="before")
    @classmethod
    def _none(cls, v):
        return None if isinstance(v, str) and v.strip().lower() in ("", "none", "null", "off") else v

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (init_settings, env_settings, dotenv_settings, YamlSource(settings_cls))   # 前者优先

    # ---- 帮助方法 ----
    def path(self, p: str | None) -> Optional[str]:
        """相对路径按项目根目录解析"""
        if not p:
            return None
        return p if os.path.isabs(p) or "://" in p else str(HERE / p)

    def secret(self, name: str) -> Optional[str]:
        v = getattr(self, name.lower(), None)
        return v.get_secret_value() if isinstance(v, SecretStr) and v.get_secret_value() else None

    def secret_values(self) -> list[str]:
        return [s for s in (self.secret(f) for f in SECRET_FIELDS) if s and len(s) >= 6]

    def summary(self) -> dict:
        """脱敏摘要：密钥只显示是否设置"""
        out = {}
        for k in type(self).model_fields:
            v = getattr(self, k)
            out[k] = ("已设置" if self.secret(k) else "未设置") if k in SECRET_FIELDS else v
        out["_config_file"] = os.environ.get("CONFIG_FILE") or (str(HERE / "config.yaml") if (HERE / "config.yaml").exists() else None)
        out["_env_file"] = str(HERE / ".env") if (HERE / ".env").exists() else None
        return out

def _load() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            msgs.append(f"{loc}: {err.get('msg')}")                # 不回显输入值（可能是密钥）
        raise ConfigError("配置校验失败：" + "；".join(msgs)) from None

@functools.lru_cache(maxsize=1)
def settings() -> Settings:
    s = _load()
    if s.hf_home:                                                  # HF 库自己读环境变量，这里同步过去
        os.environ.setdefault("HF_HOME", s.path(s.hf_home))
    if s.hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", s.hf_endpoint)
    return s

def reload_settings() -> Settings:
    """测试或修改环境变量后重新加载"""
    settings.cache_clear()
    return settings()

def secret(name: str) -> Optional[str]:
    return settings().secret(name)

if __name__ == "__main__":
    try:
        s = settings()
    except ConfigError as e:
        print(f"配置错误：{e}", file=sys.stderr); sys.exit(2)
    if len(sys.argv) >= 3 and sys.argv[1] == "get":
        v = s.summary().get(sys.argv[2].lower())
        print("" if v is None else v); sys.exit(0)
    import json
    print(json.dumps(s.summary(), ensure_ascii=False, indent=1, default=str))
