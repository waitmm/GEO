from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.adapters.base import AdapterResult, BaseAIAdapter, Citation
from app.core.config import get_settings


class WenxinAdapter(BaseAIAdapter):
    platform_key = "wenxin"
    entry_type = "official_api_non_web_model"

    async def run_query(
        self,
        prompt: str,
        model: Optional[str] = None,
        web_search_enabled: bool = True,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AdapterResult:
        settings = get_settings()
        selected_model = model or settings.wenxin_model
        started = time.perf_counter()

        if not settings.wenxin_api_key or not settings.wenxin_secret_key:
            return self._failed_result(
                prompt,
                selected_model,
                started,
                "missing_credentials",
                "未配置 WENXIN_API_KEY 或 WENXIN_SECRET_KEY",
            )

        try:
            access_token = self._get_access_token(settings.wenxin_api_key, settings.wenxin_secret_key)
            raw_response = self._chat(prompt, selected_model, access_token, settings.wenxin_timeout_seconds)
        except Exception as exc:
            return self._failed_result(prompt, selected_model, started, "request_failed", str(exc))

        if raw_response.get("error_code"):
            return self._failed_result(
                prompt,
                selected_model,
                started,
                str(raw_response.get("error_code")),
                raw_response.get("error_msg") or "文心接口返回错误",
                raw_response=raw_response,
            )

        answer_text = raw_response.get("result") or raw_response.get("answer") or ""
        citations = self._extract_citations(raw_response)
        usage = raw_response.get("usage") or {}
        return AdapterResult(
            platform=self.platform_key,
            entry_type=self.entry_type,
            model=selected_model,
            model_version=selected_model,
            web_search_enabled=False,
            prompt=prompt,
            answer_text=answer_text,
            citations=citations,
            raw_response=raw_response,
            status="success" if answer_text else "partial",
            latency_ms=int((time.perf_counter() - started) * 1000),
            token_usage=usage,
            cost_estimate=0,
        )

    def _get_access_token(self, api_key: str, secret_key: str) -> str:
        settings = get_settings()
        params = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": api_key,
                "client_secret": secret_key,
            }
        )
        token_url = f"{settings.wenxin_access_token_url}?{params}"
        raw = self._request_json(token_url, method="POST", payload=None, timeout=settings.wenxin_timeout_seconds)
        access_token = raw.get("access_token")
        if not access_token:
            raise RuntimeError(raw.get("error_description") or raw.get("error") or "无法获取文心 access_token")
        return access_token

    def _chat(self, prompt: str, model: str, access_token: str, timeout: int) -> dict[str, Any]:
        settings = get_settings()
        endpoint = settings.wenxin_endpoint_template.format(model=model)
        separator = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{separator}access_token={urllib.parse.quote(access_token)}"
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ]
        }
        return self._request_json(url, method="POST", payload=payload, timeout=timeout)

    def _request_json(
        self,
        url: str,
        method: str,
        payload: Optional[dict[str, Any]],
        timeout: int,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except json.JSONDecodeError as json_exc:
                raise RuntimeError(f"HTTP {exc.code}: {body}") from json_exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"接口返回非JSON内容: {body[:200]}") from exc

    def _failed_result(
        self,
        prompt: str,
        model: str,
        started: float,
        error_code: str,
        error_message: str,
        raw_response: Optional[dict[str, Any]] = None,
    ) -> AdapterResult:
        return AdapterResult(
            platform=self.platform_key,
            entry_type=self.entry_type,
            model=model,
            model_version=model,
            web_search_enabled=False,
            prompt=prompt,
            answer_text="",
            citations=[],
            raw_response=raw_response or {},
            status="failed",
            error_code=error_code,
            error_message=error_message,
            latency_ms=int((time.perf_counter() - started) * 1000),
            token_usage={},
            cost_estimate=0,
        )

    def _extract_citations(self, raw_response: dict[str, Any]) -> list[Citation]:
        citations: list[Citation] = []
        for key in ("citations", "references", "search_info"):
            value = raw_response.get(key)
            if isinstance(value, list):
                citations.extend(self._citations_from_list(value))
            elif isinstance(value, dict):
                nested = value.get("result") or value.get("results") or value.get("items")
                if isinstance(nested, list):
                    citations.extend(self._citations_from_list(nested))
        return citations

    def _citations_from_list(self, items: list[Any]) -> list[Citation]:
        citations = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not url:
                continue
            citations.append(
                Citation(
                    title=item.get("title") or item.get("name") or url,
                    url=url,
                    snippet=item.get("snippet") or item.get("summary") or item.get("content"),
                    source_name=item.get("source_name") or item.get("source"),
                )
            )
        return citations
