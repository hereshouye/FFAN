# -*- coding: utf-8 -*-
"""通用 LLM HTTP 客户端: urllib only, 不依赖第三方包.

支持两类 API:
  - openai_compat: Chat Completions 协议 (OpenAI / DeepSeek / 通义千问 / Together / etc.)
  - anthropic:     Claude Messages API

配置存 data/llm_config.json (data/ 已 gitignored, key 永不进 git).
"""
from __future__ import annotations
import json
import os
import urllib.request
import urllib.error
from pathlib import Path


def _data_dir() -> Path:
    """优先看环境变量 (PyInstaller 包跑时 rankprobe_lite 会设置), 否则推 tools/.."""
    env = os.environ.get("RANKPROBE_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


CONFIG_PATH = _data_dir() / "llm_config.json"


# ---------------------------------------------------------------------------
# 配置存取
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 强制本地存, 不发其他地方. 旧配置会被原子替换.
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def masked(cfg: dict) -> dict:
    """脱敏后用于前端展示 (永远不把完整 key 暴露给浏览器)."""
    out = dict(cfg)
    k = out.get("api_key") or ""
    if k:
        out["api_key"] = f"{k[:4]}...{k[-4:]}" if len(k) > 10 else "***"
    return out


# ---------------------------------------------------------------------------
# 通用 HTTP 调用
# ---------------------------------------------------------------------------
class LLMError(RuntimeError):
    pass


def _http_post_json(url: str, headers: dict, body: dict, timeout: int = 120) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        raise LLMError(f"HTTP {e.code}: {err_body[:500]}")
    except urllib.error.URLError as e:
        raise LLMError(f"网络错误: {e.reason}")
    except Exception as e:
        raise LLMError(f"未知错误: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 协议 1: OpenAI-compatible (Chat Completions)
# 兼容: OpenAI / DeepSeek / 通义 / Together / 智谱 / 月之暗面 / OpenRouter / vLLM / ollama-openai
# ---------------------------------------------------------------------------
def call_openai_compat(cfg: dict, system: str, user: str,
                       json_mode: bool = False, max_tokens: int = 4096) -> str:
    endpoint = (cfg.get("endpoint") or "").rstrip("/")
    if not endpoint:
        raise LLMError("缺 endpoint")
    # 自动补 path: 用户可能填 https://api.deepseek.com 或 .../v1
    if not endpoint.endswith("/chat/completions"):
        if endpoint.endswith("/v1"):
            endpoint += "/chat/completions"
        else:
            endpoint += "/v1/chat/completions"
    key = cfg.get("api_key") or ""
    if not key:
        raise LLMError("缺 api_key")
    model = cfg.get("model") or ""
    if not model:
        raise LLMError("缺 model")

    body = {
        "model":       model,
        "messages":    [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": float(cfg.get("temperature", 0.7)),
        "max_tokens":  int(max_tokens),
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }
    resp = _http_post_json(endpoint, headers, body)
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"返回格式异常: {json.dumps(resp, ensure_ascii=False)[:500]}")


# ---------------------------------------------------------------------------
# 协议 2: Anthropic (Claude Messages API)
# ---------------------------------------------------------------------------
def call_anthropic(cfg: dict, system: str, user: str,
                   max_tokens: int = 4096) -> str:
    endpoint = (cfg.get("endpoint") or "https://api.anthropic.com").rstrip("/")
    if not endpoint.endswith("/v1/messages"):
        endpoint += "/v1/messages"
    key = cfg.get("api_key") or ""
    if not key:
        raise LLMError("缺 api_key")
    model = cfg.get("model") or "claude-sonnet-4-5"

    body = {
        "model":       model,
        "max_tokens":  int(max_tokens),
        "system":      system,
        "messages":    [{"role": "user", "content": user}],
        "temperature": float(cfg.get("temperature", 0.7)),
    }
    headers = {
        "x-api-key":         key,
        "anthropic-version": cfg.get("anthropic_version", "2023-06-01"),
        "Content-Type":      "application/json",
    }
    resp = _http_post_json(endpoint, headers, body)
    try:
        # Anthropic 返回 {"content": [{"type":"text", "text":"..."}], ...}
        parts = resp.get("content") or []
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        if not text:
            raise LLMError(f"返回内容为空: {json.dumps(resp, ensure_ascii=False)[:300]}")
        return text
    except Exception as e:
        raise LLMError(f"返回格式异常: {json.dumps(resp, ensure_ascii=False)[:500]}")


# ---------------------------------------------------------------------------
# 统一入口: 根据 type 路由
# ---------------------------------------------------------------------------
def chat(system: str, user: str, json_mode: bool = False,
         max_tokens: int = 4096, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    t = (cfg.get("type") or "openai_compat").lower()
    if t == "anthropic":
        return call_anthropic(cfg, system, user, max_tokens=max_tokens)
    return call_openai_compat(cfg, system, user, json_mode=json_mode, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# CLI: 自检 + 配置查看
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args:
        cfg = load_config()
        print("当前 LLM 配置:")
        print(json.dumps(masked(cfg) if cfg else {"(未配置)": True},
                         ensure_ascii=False, indent=2))
        print(f"\n文件位置: {CONFIG_PATH}")
        sys.exit(0)
    if args[0] == "test":
        try:
            r = chat("你是测试助手", "请说一句话证明你能连通", max_tokens=200)
            print("连通 ✓")
            print(r)
        except LLMError as e:
            print(f"失败 ✗: {e}")
            sys.exit(1)
