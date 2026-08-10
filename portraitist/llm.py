"""LLM 网关：统一 OpenAI 兼容接口，支持远程 API / 本地 LM Studio 切换。

设计约束（DESIGN.md §2.5）：本网关只负责文本生成与 JSON 提取，
绝不让 LLM 输出量表分数——画像证据由 evidence.py 锚定用户陈述。
"""

from __future__ import annotations

import json
import re

import requests


class LLMError(Exception):
    """LLM 调用失败。"""


def parse_json_response(text: str) -> dict:
    """容错解析 LLM 输出的 JSON（可能被 ```json 包裹或夹杂说明文字）。"""
    if not text:
        raise LLMError("空响应")
    t = text.strip()
    # 剥掉 markdown 代码块
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    # 直接尝试
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # 找第一个 { 到最后一个 }
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError(f"无法解析为 JSON: {text[:200]}")


class LLMGateway:
    """OpenAI 兼容 chat/completions 客户端。"""

    def __init__(self, config: dict):
        backend = config.get("backend", "remote")
        section = config.get(backend)
        if not section:
            raise LLMError(f"配置缺少 backend 节: {backend}")
        self.base_url = section["base_url"].rstrip("/")
        self.api_key = section.get("api_key", "")
        self.timeout = section.get("timeout", 120)
        self.backend = backend
        self.chat_model = config.get("chat_model", "deepseek-chat")
        self.report_model = config.get("report_model", self.chat_model)

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        thinking: bool | None = None,
    ) -> str:
        """调用 chat/completions。

        thinking: True=强制思考模式（quality优先）；False=关闭思考（latency优先）；
        None=模型默认。
        注意：DeepSeek 文档——思考模式下 temperature/top_p 等参数不生效。
        """
        payload = {
            "model": model or self.chat_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if thinking is True:
            payload["thinking"] = {"type": "enabled"}
        elif thinking is False:
            payload["thinking"] = {"type": "disabled"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise LLMError(f"LLM 请求失败 ({self.backend}): {e}") from e
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"LLM 响应结构异常: {data}") from e

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> dict:
        return parse_json_response(
            self.chat(
                system, user, model=model, temperature=temperature,
                max_tokens=max_tokens, thinking=True,
            )
        )
