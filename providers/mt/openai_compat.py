"""OpenAI 兼容 Chat 翻译引擎（一个类覆盖硅基流动/GLM/混元/DeepSeek…）。

协议：POST {base_url}/chat/completions
     Authorization: Bearer <key>；body: model/messages/temperature
配置驱动（registry 预设只改 base_url/model/prompt），零新代码接新家。
用 urllib（标准库）而非引入 httpx——依赖最小化，worker 单线程调用
天然无并发竞争。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .errors import TranslateError, from_http_status

_TIMEOUT_S = 15.0


class OpenAICompatTranslator:
    """translate(text, src, tgt, is_stale) -> str（Translator 协议实现）。"""

    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.siliconflow.cn/v1",
                 prompt: str | None = None, temperature: float = 0.3):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.prompt = prompt or (
            "You are a real-time simultaneous interpreter. Translate the "
            "user's text from {src} to {tgt}. Output ONLY the translation, "
            "no explanations, no quotes, keep it concise and natural for "
            "live subtitles.")

    # ---------- Translator 协议 ----------
    def translate(self, text: str, source_lang: str, target_lang: str,
                  is_stale=None) -> str:
        if not text.strip():
            return ""
        sys_prompt = self.prompt.format(
            src=source_lang if source_lang != "auto" else "the detected language",
            tgt=target_lang)
        body = json.dumps({
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": 512,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_txt = ""
            try:
                body_txt = e.read().decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                pass
            raise from_http_status(e.code, body_txt) from None
        except urllib.error.URLError as e:
            if "timed out" in str(e).lower():
                raise TranslateError("timeout", str(e)) from None
            raise TranslateError("network", str(e)) from None
        except TimeoutError:
            raise TranslateError("timeout", "request timeout") from None
        # 解析
        try:
            out = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise TranslateError("permanent", f"bad response: {str(data)[:200]}") from None
        # 剥 <think> 段（推理模型兜底）与首尾空白
        if "</think>" in out:
            out = out.rsplit("</think>", 1)[-1]
        return out.strip()

    def test_connection(self) -> tuple[bool, str]:
        """GET {base_url}/models 验 key 与网络（UI「测试连接」用）。"""
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                n = len(json.loads(resp.read().decode("utf-8")).get("data", []))
                return True, f"连接正常（{n} 个模型可用）"
        except urllib.error.HTTPError as e:
            return False, from_http_status(e.code).user_message()
        except Exception as e:  # noqa: BLE001
            return False, f"网络异常: {e}"
