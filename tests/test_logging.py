# 日志：打码（密钥原值 / Bearer / Authorization / sk- / api_key=）、request_id、json 格式、文件内容不含 key、问句默认不记原文
import json, logging, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config, kblog

KEY = "sk-test-SECRETVALUE-987654321"

def _setup(tmp_path, monkeypatch, fmt="text", questions=False):
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "none.yaml"))
    monkeypatch.setenv("SILICONFLOW_API_KEY", KEY)
    s = config.Settings(_env_file=str(tmp_path / "x.env"), log_dir=str(tmp_path / "logs"), log_format=fmt, log_questions=questions)
    kblog.setup_logging(force=True, s=s)
    return s, tmp_path / "logs" / "powerkb.log"

def _flush():
    for h in logging.getLogger().handlers:
        h.flush()

def test_redact_patterns():
    kblog.register_secrets(["my-super-secret-value"])
    t = kblog.redact("a my-super-secret-value Authorization: Bearer abc.def-ghi X-API-Key: k123456 api_key=zzzz9999 "
                     '{"token": "tttt8888"} sk-abcdefgh12345 xai-ABCDEFGH1234')
    for bad in ("my-super-secret-value", "abc.def-ghi", "k123456", "zzzz9999", "tttt8888", "sk-abcdefgh12345", "xai-ABCDEFGH1234"):
        assert bad not in t, bad
    assert "***" in t

def test_text_log_file_masked_with_request_id(tmp_path, monkeypatch):
    s, f = _setup(tmp_path, monkeypatch)
    lg = kblog.get_logger("powerkb.test")
    tok = kblog.request_id.set("rid-abc123")
    lg.warning("upstream said: invalid key %s", KEY)
    kblog.event(lg, "rag.answer", provider="siliconflow", total_secs=1.5, q=kblog.q_repr("SF6 湿度限值是多少？"))
    try:
        raise RuntimeError(f"boom Authorization: Bearer {KEY}")
    except RuntimeError:
        lg.exception("crash")
    kblog.request_id.reset(tok); _flush()
    text = f.read_text(encoding="utf-8")
    assert KEY not in text and "rid=rid-abc123" in text and "provider=siliconflow" in text
    assert "SF6 湿度限值" not in text and "len=" in text                      # 默认不记问句原文
    assert "Traceback" in text                                                 # 堆栈进日志，但已打码

def test_json_format_and_questions_opt_in(tmp_path, monkeypatch):
    s, f = _setup(tmp_path, monkeypatch, fmt="json", questions=True)
    monkeypatch.setenv("LOG_QUESTIONS", "true"); config.reload_settings()
    lg = kblog.get_logger("powerkb.test")
    tok = kblog.request_id.set("rid-json")
    kblog.event(lg, "rag.answer", provider="local", total_tokens=123, q=kblog.q_repr("问句原文"), note=f"key={KEY}")
    kblog.request_id.reset(tok); _flush()
    line = [l for l in f.read_text(encoding="utf-8").splitlines() if "rag.answer" in l][-1]
    d = json.loads(line)
    assert d["request_id"] == "rid-json" and d["total_tokens"] == 123 and d["q"] == "问句原文" and KEY not in line
    monkeypatch.delenv("LOG_QUESTIONS"); config.reload_settings()
