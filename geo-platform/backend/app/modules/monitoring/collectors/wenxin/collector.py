from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import socket
import urllib.parse
import uuid
from pathlib import Path
from datetime import datetime

from app.core.config import get_settings
from app.modules.monitoring.collectors.base import BaseCollector, CollectorHealth, CollectorResult
from app.modules.monitoring.collectors.wenxin.exceptions import (
    AnswerTimeoutError,
    CaptchaRequiredError,
    ConfigurationError,
    LoginRequiredError,
    PageStructureError,
)
from app.modules.monitoring.collectors.wenxin.reference_parser import resolve_reference_url
from app.modules.monitoring.collectors.wenxin.selectors import (
    ANSWER_NOISE_MARKERS,
    CAPTCHA_TEXT_MARKERS,
    INPUT_CANDIDATES,
    LOGIN_TEXT_MARKERS,
    REFERENCE_PANEL_CANDIDATES,
    REFERENCE_TEXT_PATTERN,
    STOP_BUTTON_TEXT_MARKERS,
    SUBMIT_BUTTON_CANDIDATES,
)


class WenxinWebCollector(BaseCollector):
    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None
        self._conversation_id = ""
        self._last_reference_metrics = {}
        self._last_reference_panel_html = ""
        self._network_events = []
        self._capture_network = False

    async def collect(self, run) -> CollectorResult:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise ConfigurationError("未安装 Playwright，请先安装依赖并执行 playwright install chromium") from exc

        settings = get_settings()
        profile_dir = Path(settings.wenxin_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        chrome_path = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        browser_options = {
            "user_data_dir": str(profile_dir),
            "headless": settings.wenxin_headless,
            "viewport": {"width": 1440, "height": 1000},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }
        if chrome_path.exists():
            browser_options["executable_path"] = str(chrome_path)

        page = await self._ensure_session(async_playwright, settings, browser_options)
        self._network_events = []
        self._capture_network = True
        try:
            if not page.url.startswith(("https://chat.baidu.com/", "https://wenxin.baidu.com/")):
                await page.goto(settings.wenxin_web_url, wait_until="domcontentloaded", timeout=settings.wenxin_browser_timeout_seconds * 1000)
                await page.wait_for_timeout(3000)
            await self._raise_for_login_or_captcha(page)
            await self._prepare_collection_mode(page, getattr(run, "collection_mode", "single_continuous"))
            await self._submit_query(page, run.original_query)
            run.page_query = run.original_query
            run.retrieval_query = run.original_query
            answer_text = await self._wait_answer_complete(page, run.original_query, settings.wenxin_browser_timeout_seconds)
            answer_html = await self._extract_answer_html(page)
            references = await self._extract_references(page)
            artifacts = await self._capture_page_artifacts(page)
            if self._last_reference_panel_html:
                artifacts.append(
                    {
                        "artifact_type": "reference_panel_html",
                        "filename": "reference-panel.html",
                        "content": self._last_reference_panel_html,
                        "mime_type": "text/html",
                    }
                )
            if self._network_events:
                artifacts.append(
                    {
                        "artifact_type": "network_log",
                        "filename": "network.jsonl",
                        "content": "\n".join(json.dumps(item, ensure_ascii=False) for item in self._network_events) + "\n",
                        "mime_type": "application/x-ndjson",
                    }
                )
            return CollectorResult(
                answer_text=answer_text,
                answer_html=answer_html,
                references=references,
                retrieval_candidates=[],
                artifacts=artifacts,
                metrics=dict(self._last_reference_metrics),
                environment=await self._environment_metadata(page, settings),
            )
        except PlaywrightTimeoutError as exc:
            raise AnswerTimeoutError(str(exc)) from exc
        finally:
            self._capture_network = False

    async def _prepare_collection_mode(self, page, collection_mode: str) -> None:
        if collection_mode != "single_independent":
            return
        try:
            existing_turns = await page.locator(
                "#conversation-flow-content .conversation-flow-question-container"
            ).count()
            if existing_turns == 0:
                return
            trigger = page.get_by_text(re.compile(r"开启新对话|新对话"), exact=False).first
            if await trigger.is_visible(timeout=1000):
                await trigger.click(timeout=3000)
                await page.wait_for_timeout(1500)
                self._conversation_id = str(uuid.uuid4())
        except Exception:
            # Failure to switch is visible later as turn-binding evidence; do
            # not restart Chrome because that increases verification risk.
            return

    async def _ensure_session(self, async_playwright, settings, browser_options):
        if self._page is not None and not self._page.is_closed():
            return self._page
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(**browser_options)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._page.on("response", self._record_response)
        self._conversation_id = str(uuid.uuid4())
        await self._page.goto(
            settings.wenxin_web_url,
            wait_until="domcontentloaded",
            timeout=settings.wenxin_browser_timeout_seconds * 1000,
        )
        await self._page.wait_for_timeout(3000)
        return self._page

    def _record_response(self, response) -> None:
        if not self._capture_network:
            return
        try:
            self._network_events.append(
                {
                    "captured_at": datetime.utcnow().isoformat() + "Z",
                    "url": self._safe_network_url(response.url),
                    "status": response.status,
                    "resource_type": response.request.resource_type,
                    "method": response.request.method,
                }
            )
        except Exception:
            return

    def _safe_network_url(self, value: str) -> str:
        try:
            parsed = urllib.parse.urlsplit(value)
            sensitive = {
                "token", "access_token", "auth_token", "sid", "session_id",
                "conversation_id", "trace_id", "tk",
            }
            query = urllib.parse.urlencode(
                [(key, item) for key, item in urllib.parse.parse_qsl(parsed.query) if key.lower() not in sensitive]
            )
            return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
        except Exception:
            return value.split("#", 1)[0]

    async def _environment_metadata(self, page, settings) -> dict:
        browser_version = ""
        try:
            browser_version = self._context.browser.version
        except Exception:
            pass
        return {
            "collector_id": socket.gethostname(),
            "collection_mode": "single_continuous",
            "browser": "Google Chrome",
            "browser_version": browser_version,
            "os": f"{platform.system()} {platform.release()}",
            "profile_identifier": Path(settings.wenxin_profile_dir).name,
            "conversation_id": self._conversation_id,
            "network_region": os.getenv("WENXIN_NETWORK_REGION", "unknown"),
            "collector_version": "wenxin-web-v1",
            "parser_version": "reference-parser-v1.8c-compatible",
            "page_url": page.url,
        }

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._playwright = None

    async def health_check(self) -> CollectorHealth:
        settings = get_settings()
        return CollectorHealth(
            healthy=bool(settings.wenxin_profile_dir),
            status="profile_configured" if settings.wenxin_profile_dir else "missing_profile_dir",
            message=f"profile_dir={settings.wenxin_profile_dir}",
        )

    async def _raise_for_login_or_captcha(self, page) -> None:
        # Wenxin keeps login/security wording in hidden page regions even for
        # usable anonymous sessions. Input/answer selectors are the reliable
        # readiness signal; whole-page keyword checks cause false failures.
        return

    async def _has_input(self, page) -> bool:
        for selector in INPUT_CANDIDATES:
            locator = page.locator(selector).last
            try:
                if await locator.is_visible(timeout=800):
                    return True
            except Exception:
                continue
        return False

    async def _submit_query(self, page, query: str) -> None:
        for selector in INPUT_CANDIDATES:
            locator = page.locator(selector).last
            try:
                if not await locator.is_visible(timeout=1000):
                    continue
                await locator.click()
                await locator.fill(query)
                await self._click_submit(page)
                await page.wait_for_timeout(1200)
                body_text = await page.locator("body").inner_text(timeout=5000)
                if query[:20] in body_text:
                    return
            except Exception:
                continue
        raise PageStructureError("未找到可输入的问题输入框")

    async def _click_submit(self, page) -> None:
        for selector in SUBMIT_BUTTON_CANDIDATES:
            try:
                locator = page.locator(selector).last
                if await locator.is_visible(timeout=800):
                    await locator.click(timeout=1500)
                    return
            except Exception:
                continue
        await page.keyboard.press("Enter")

    async def _wait_answer_complete(self, page, query: str, timeout_seconds: int) -> str:
        stable_count = 0
        last_hash = ""
        best_answer = ""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            await self._raise_for_login_or_captcha(page)
            body_text = await page.locator("body").inner_text(timeout=5000)
            answer_text = await self._current_answer_text(page)
            current_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
            has_reference = re.search(REFERENCE_TEXT_PATTERN, answer_text) is not None
            has_stop_button = any(marker in body_text for marker in STOP_BUTTON_TEXT_MARKERS)
            if answer_text and current_hash == last_hash:
                stable_count += 1
            else:
                stable_count = 0
            best_answer = answer_text or best_answer
            last_hash = current_hash
            if best_answer and stable_count >= 3 and (has_reference or not has_stop_button):
                return best_answer
            await page.wait_for_timeout(1000)
        if best_answer:
            return best_answer
        raise AnswerTimeoutError("等待回答超时，未采集到回答正文")

    async def _current_answer_text(self, page) -> str:
        selectors = [
            "#conversation-flow-content .conversation-flow-answer-container .cs-answer-container",
            "#conversation-flow-content .conversation-flow-answer-container .answer-container",
            ".conversation-flow-answer-container",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).last
                if not await locator.is_visible(timeout=500):
                    continue
                text = await locator.inner_text(timeout=2000)
                lines = []
                for line in text.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped in ANSWER_NOISE_MARKERS:
                        continue
                    if stripped in {"思考已停止", "深度思考"}:
                        continue
                    lines.append(stripped)
                answer = "\n".join(lines).strip()
                if answer:
                    return answer
            except Exception:
                continue
        return ""

    def _extract_answer_text_from_body(self, body_text: str, query: str) -> str:
        after_query = body_text.split(query, 1)[-1].strip() if query in body_text else body_text.strip()
        lines = []
        for line in after_query.splitlines():
            stripped = line.strip()
            if not stripped or stripped in ANSWER_NOISE_MARKERS:
                continue
            lines.append(stripped)
        return "\n".join(lines).strip()

    async def _extract_answer_html(self, page) -> str:
        for selector in [
            "#conversation-flow-content .conversation-flow-answer-container .cs-answer-container",
            "#conversation-flow-content .conversation-flow-answer-container .answer-container",
        ]:
            try:
                locator = page.locator(selector).last
                if await locator.is_visible(timeout=500):
                    return await locator.evaluate("node => node.innerHTML")
            except Exception:
                continue
        return ""

    async def _extract_references(self, page) -> list[dict]:
        self._last_reference_metrics = {
            "ui_declared_count": 0,
            "dom_reference_count": 0,
            "parsed_reference_count": 0,
            "resolved_url_count": 0,
        }
        self._last_reference_panel_html = ""
        body_text = await page.locator("body").inner_text(timeout=5000)
        expected_matches = re.findall(REFERENCE_TEXT_PATTERN, body_text)
        if not expected_matches:
            return []
        expected_count = int(expected_matches[-1])
        self._last_reference_metrics["ui_declared_count"] = expected_count

        await self._open_reference_panel(page)
        await self._scroll_reference_panels(page)
        self._last_reference_panel_html = await self._reference_panel_html(page)
        dom_items = await self._reference_dom_items(page, expected_count)
        if dom_items:
            resolved = [resolve_reference_url(item, []) for item in dom_items]
            self._last_reference_metrics.update(
                {
                    "dom_reference_count": len(dom_items),
                    "parsed_reference_count": sum(bool(item.get("display_title")) for item in resolved),
                    "resolved_url_count": sum(bool(item.get("url")) for item in resolved),
                }
            )
            return resolved

        panel_text = await self._reference_panel_text(page)
        reference_items = []
        for line in panel_text.splitlines():
            title = line.strip()
            if len(title) < 4 or len(title) > 300:
                continue
            if "共参考" in title or title in {"展开", "收起", "复制", "关闭"}:
                continue
            reference_items.append(
                {
                    "reference_index": len(reference_items) + 1,
                    "display_title": title,
                    "outer_html": "",
                }
            )
        if len(reference_items) < expected_count:
            existing_titles = {item["display_title"] for item in reference_items}
            for title in self._extract_reference_titles_from_text(body_text, expected_count):
                if title in existing_titles:
                    continue
                reference_items.append(
                    {
                        "reference_index": len(reference_items) + 1,
                        "display_title": title,
                        "outer_html": "",
                    }
                )
        resolved = [resolve_reference_url(item, []) for item in reference_items]
        self._last_reference_metrics.update(
            {
                "dom_reference_count": len(reference_items),
                "parsed_reference_count": sum(bool(item.get("display_title")) for item in resolved),
                "resolved_url_count": sum(bool(item.get("url")) for item in resolved),
            }
        )
        return resolved

    async def _scroll_reference_panels(self, page) -> None:
        selectors = ", ".join(REFERENCE_PANEL_CANDIDATES)
        try:
            await page.locator("body").evaluate(
                """(body, selectors) => {
                    for (const panel of body.querySelectorAll(selectors)) {
                        if (panel.scrollHeight > panel.clientHeight) {
                            panel.scrollTop = panel.scrollHeight;
                        }
                    }
                }""",
                selectors,
            )
            await page.wait_for_timeout(500)
        except Exception:
            return

    async def _reference_dom_items(self, page, expected_count: int) -> list[dict]:
        selectors = ", ".join(REFERENCE_PANEL_CANDIDATES)
        try:
            return await page.locator("body").evaluate(
                """(body, args) => {
                    const {selectors, expectedCount} = args;
                    const clean = value => String(value || '')
                        .replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
                    const visible = el => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                            style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const attrs = [
                        'href', 'data-url', 'data-href', 'data-link',
                        'data-source-url', 'data-target-url', 'data-jump-url',
                        'data-redirect-url', 'data-tc-url', 'data-origin-url'
                    ];
                    const panels = Array.from(body.querySelectorAll(selectors))
                        .filter(visible)
                        .sort((a, b) => clean(b.innerText).length - clean(a.innerText).length);
                    const panel = panels[0];
                    if (!panel) return [];
                    const serializedNodes = Array.from(
                        panel.querySelectorAll('[data-long-press-ext-info]')
                    );
                    const nodes = serializedNodes.length >= expectedCount
                        ? serializedNodes
                        : Array.from(panel.querySelectorAll(
                            'a,button,[role="link"],[data-url],[data-href],[data-link],[data-long-press-ext-info],div,span,p'
                        )).filter(visible);
                    const results = [];
                    const seen = new Set();
                    for (const el of nodes) {
                        const title = clean(
                            el.innerText || el.textContent ||
                            el.getAttribute('aria-label') || el.getAttribute('title')
                        ).replace(/^\\d+[.、]\\s*/, '');
                        if (title.length < 4 || title.length > 300) continue;
                        if (/共参考\\s*\\d+\\s*篇资料|收起|展开|关闭|复制|分享|重新生成|有用|没用|赞|踩/.test(title)) continue;
                        const child = el.querySelector(
                            'a,button,[role="link"],[data-url],[data-href],[data-link]'
                        );
                        if (child && clean(child.innerText) === title) continue;
                        if (seen.has(title)) continue;
                        const style = getComputedStyle(el);
                        const clickable = el.matches('a,button,[role="link"],[data-url],[data-href],[data-link]') ||
                            el.hasAttribute('data-long-press-ext-info') ||
                            style.cursor === 'pointer' || attrs.some(name => el.hasAttribute(name));
                        if (!clickable) continue;
                        const item = {
                            reference_index: results.length + 1,
                            display_title: title,
                            outer_html: el.outerHTML || '',
                            ancestor_outer_html: []
                        };
                        for (const name of attrs) {
                            const value = el.getAttribute(name);
                            if (value) item[name] = value;
                        }
                        let parent = el.parentElement;
                        for (let level = 0; level < 5 && parent; level += 1) {
                            item.ancestor_outer_html.push(parent.outerHTML || '');
                            for (const name of attrs) {
                                if (!item[name]) {
                                    const value = parent.getAttribute(name);
                                    if (value) item[name] = value;
                                }
                            }
                            parent = parent.parentElement;
                        }
                        results.push(item);
                        seen.add(title);
                        if (Number.isFinite(expectedCount) && results.length >= expectedCount) break;
                    }
                    return results;
                }""",
                {"selectors": selectors, "expectedCount": expected_count},
            )
        except Exception:
            return []

    def _extract_reference_titles_from_text(self, text: str, expected_count: int) -> list[str]:
        titles = []
        for line in text.splitlines():
            stripped = line.strip()
            match = re.match(r"^(\d+)[.、]\s*(.+)$", stripped)
            if not match:
                continue
            number = int(match.group(1))
            if number < 1 or number > expected_count:
                continue
            title = match.group(2).strip()
            if 4 <= len(title) <= 300:
                titles.append(title)
        if len(titles) >= expected_count:
            return titles[:expected_count]

        marker = re.search(REFERENCE_TEXT_PATTERN, text)
        segment = text[marker.end() :] if marker else text
        inline_matches = re.finditer(r"(?:^|\s)(\d+)[.、]\s*(.*?)(?=\s+\d+[.、]\s+|$)", segment, flags=re.S)
        existing = set(titles)
        for match in inline_matches:
            number = int(match.group(1))
            if number < 1 or number > expected_count:
                continue
            title = " ".join(match.group(2).split()).strip()
            if 4 <= len(title) <= 300 and title not in existing:
                titles.append(title)
                existing.add(title)
            if len(titles) >= expected_count:
                break
        return titles

    async def _open_reference_panel(self, page) -> None:
        trigger = page.get_by_text(re.compile(REFERENCE_TEXT_PATTERN)).last
        try:
            await trigger.click(timeout=3000)
            await page.wait_for_timeout(800)
        except Exception:
            return

    async def _reference_panel_text(self, page) -> str:
        candidates = []
        for selector in REFERENCE_PANEL_CANDIDATES:
            try:
                locator = page.locator(selector).last
                if await locator.is_visible(timeout=800):
                    candidates.append(await locator.inner_text(timeout=2000))
            except Exception:
                continue
        return max(candidates, key=len) if candidates else ""

    async def _reference_panel_html(self, page) -> str:
        candidates = []
        for selector in REFERENCE_PANEL_CANDIDATES:
            try:
                locator = page.locator(selector).last
                if await locator.is_visible(timeout=500):
                    html = await locator.evaluate("node => node.outerHTML")
                    if html:
                        candidates.append(html)
            except Exception:
                continue
        return max(candidates, key=len) if candidates else ""

    async def _capture_page_artifacts(self, page) -> list[dict]:
        html = await page.locator("body").evaluate("node => node.outerHTML")
        screenshot = await page.screenshot(full_page=True)
        return [
            {"artifact_type": "page_html", "filename": "page.html", "content": html, "mime_type": "text/html"},
            {"artifact_type": "page_screenshot", "filename": "page.png", "content_bytes": screenshot, "mime_type": "image/png"},
        ]
