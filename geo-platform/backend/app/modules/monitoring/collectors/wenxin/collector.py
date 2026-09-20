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
    ConversationResetError,
    LoginRequiredError,
    PageStructureError,
)
from app.modules.monitoring.collectors.wenxin.reference_parser import resolve_reference_url
from app.modules.monitoring.collectors.wenxin.search_process import (
    final_answer_boundary,
    project_platform_search_observation,
)
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
        self._session_active = False
        self._requested_collection_mode = ""
        self._actual_sampling_mode = "UNKNOWN"
        self._session_verification_basis = "NOT_CHECKED"

    def _find_chromium_path(self) -> str | None:
        candidates = []
        # 1. 环境变量 CHROMIUM_EXECUTABLE_PATH
        env_path = os.environ.get("CHROMIUM_EXECUTABLE_PATH")
        if env_path:
            candidates.append(env_path)
        # 2. 系统 Chrome（macOS / Linux / Windows）
        system = platform.system()
        if system == "Darwin":
            candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            candidates.append("/Applications/Chromium.app/Contents/MacOS/Chromium")
        elif system == "Linux":
            candidates.extend(["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"])
        elif system == "Windows":
            candidates.extend([
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ])
        # 3. Playwright 已有的旧版 Chromium（从高版本到低版本）
        pw_cache_dir = "~/Library/Caches/ms-playwright" if system == "Darwin" else \
                        "~/.cache/ms-playwright" if system == "Linux" else \
                        "~/AppData/Local/ms-playwright"
        pw_cache = Path(os.path.expanduser(pw_cache_dir))
        if pw_cache.exists():
            for d in sorted(pw_cache.iterdir(), reverse=True):
                if d.is_dir() and "chromium" in d.name and "headless" not in d.name:
                    if system == "Darwin":
                        chrome_app = d / "chrome-mac-x64" / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing"
                    elif system == "Linux":
                        chrome_app = d / "chrome-linux64" / "chrome"
                    else:
                        chrome_app = d / "chrome-win" / "chrome.exe"
                    if chrome_app.exists():
                        candidates.append(str(chrome_app))
        for p in candidates:
            if Path(p).exists():
                return p
        return None

    async def collect(self, run) -> CollectorResult:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise ConfigurationError("未安装 Playwright，请先安装依赖并执行 playwright install chromium") from exc

        settings = get_settings()
        await self._start_browser_session(async_playwright, settings)
        try:
            return await self._collect_one(run, settings)
        finally:
            await self._end_browser_session()

    async def start_session(self) -> None:
        """启动一次浏览器会话，调用方可以在同一个窗口中多次 collect_in_session"""
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise ConfigurationError("未安装 Playwright，请先安装依赖并执行 playwright install chromium") from exc
        settings = get_settings()
        await self._start_browser_session(async_playwright, settings)

    async def collect_in_session(self, run) -> CollectorResult:
        """在当前已打开的浏览器窗口中提问并采集，必须已调用 start_session"""
        settings = get_settings()
        return await self._collect_one(run, settings)

    async def end_session(self) -> None:
        """关闭当前浏览器会话"""
        await self._end_browser_session()

    async def _start_browser_session(self, async_playwright, settings) -> None:
        profile_dir = Path(settings.wenxin_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        chrome_path = self._find_chromium_path()
        browser_options = {
            "user_data_dir": str(profile_dir),
            "headless": settings.wenxin_headless,
            "viewport": {"width": 1440, "height": 1000},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }
        if chrome_path:
            browser_options["executable_path"] = chrome_path
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(**browser_options)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._page.on("response", self._record_response)
        self._conversation_id = str(uuid.uuid4())
        self._session_active = True
        await self._page.goto(
            settings.wenxin_web_url,
            wait_until="domcontentloaded",
            timeout=settings.wenxin_browser_timeout_seconds * 1000,
        )
        await self._page.wait_for_timeout(3000)

    async def _collect_one(self, run, settings) -> CollectorResult:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        except Exception as exc:
            raise ConfigurationError("Playwright 导入失败") from exc

        self._network_events = []
        self._capture_network = True
        self._requested_collection_mode = str(run.collection_mode or "")
        self._actual_sampling_mode = "UNKNOWN"
        self._session_verification_basis = "NOT_CHECKED"
        try:
            await self._prepare_collection_mode(self._page, self._requested_collection_mode)
            await self._submit_query(self._page, run.original_query)
            run.page_query = run.original_query
            run.retrieval_query = run.original_query
            answer_text = await self._wait_answer_complete(self._page, run.original_query, settings.wenxin_browser_timeout_seconds)
            answer_html = await self._extract_answer_html(self._page)
            platform_reported_search = await self._extract_platform_reported_search(self._page)
            answer_content_boundary = final_answer_boundary()
            references = await self._extract_references(self._page)
            artifacts = await self._capture_page_artifacts(self._page)
            artifacts.append(
                {
                    "artifact_type": "wenxin_semantic_regions",
                    "filename": "semantic-regions.json",
                    "content": json.dumps(
                        {
                            "platform_reported_search": platform_reported_search,
                            "answer_content_boundary": answer_content_boundary,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "mime_type": "application/json",
                }
            )
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
                platform_reported_search=platform_reported_search,
                answer_content_boundary=answer_content_boundary,
                references=references,
                retrieval_candidates=[],
                artifacts=artifacts,
                metrics=dict(self._last_reference_metrics),
                environment=await self._environment_metadata(self._page, settings),
            )
        except PlaywrightTimeoutError as exc:
            raise AnswerTimeoutError(str(exc)) from exc
        finally:
            self._capture_network = False

    async def _end_browser_session(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._playwright = None
        self._session_active = False

    async def _prepare_collection_mode(self, page, collection_mode: str) -> None:
        if collection_mode != "single_independent":
            self._actual_sampling_mode = "single_continuous"
            self._session_verification_basis = "NOT_REQUIRED_BY_PLAN"
            return
        existing_turns = await self._conversation_turn_count(page)
        if existing_turns == 0:
            self._mark_independent_session_verified()
            return
        try:
            trigger = page.get_by_text(re.compile(r"开启新对话|新对话"), exact=False).first
            if not await trigger.is_visible(timeout=1000):
                raise ConversationResetError("当前页面存在历史对话，但未找到“新对话”入口，无法保证独立会话采集")
            await trigger.click(timeout=3000)
            await self._wait_for_fresh_conversation(page)
            self._conversation_id = str(uuid.uuid4())
            self._mark_independent_session_verified()
        except Exception:
            try:
                settings = get_settings()
                await page.goto(
                    settings.wenxin_web_url,
                    wait_until="domcontentloaded",
                    timeout=settings.wenxin_browser_timeout_seconds * 1000,
                )
                await page.wait_for_timeout(1500)
                await self._wait_for_fresh_conversation(page)
                self._conversation_id = str(uuid.uuid4())
                self._mark_independent_session_verified()
                return
            except ConversationResetError:
                raise
            except Exception as exc:
                raise ConversationResetError(
                    "独立对话采集要求每个 Prompt 先开启新对话，当前未能成功重置会话"
                ) from exc

    async def _conversation_turn_count(self, page) -> int:
        return await page.locator(
            "#conversation-flow-content .conversation-flow-question-container"
        ).count()

    async def _wait_for_fresh_conversation(self, page) -> None:
        for _ in range(8):
            if await self._conversation_turn_count(page) == 0:
                return
            await page.wait_for_timeout(400)
        raise ConversationResetError("新对话后仍检测到历史提问，已在提交 Prompt 前停止该 Run")

    def _mark_independent_session_verified(self) -> None:
        self._actual_sampling_mode = "single_independent"
        self._session_verification_basis = "PRE_SUBMIT_ZERO_TURN_DOM_GATE"

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
            "collection_mode": self._requested_collection_mode or "UNKNOWN",
            "sampling_mode": self._actual_sampling_mode,
            "session_verification_basis": self._session_verification_basis,
            "browser": "Google Chrome",
            "browser_version": browser_version,
            "os": f"{platform.system()} {platform.release()}",
            "profile_identifier": Path(settings.wenxin_profile_dir).name,
            "conversation_id": self._conversation_id,
            "network_region": os.getenv("WENXIN_NETWORK_REGION", "unknown"),
            "collector_version": "wenxin-web-v1.2-final-answer-boundary",
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
            has_reference = re.search(REFERENCE_TEXT_PATTERN, body_text) is not None
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
        container = await self._last_answer_container(page)
        if container is None:
            return ""
        for selector in [
            ".ai-entry-block.ai-markdown .cosd-markdown-content",
            ".ai-entry-block.ai-markdown",
        ]:
            try:
                locator = container.locator(selector).last
                if not await locator.is_visible(timeout=500):
                    continue
                answer = self._clean_answer_text(await locator.inner_text(timeout=2000))
                if answer:
                    return answer
            except Exception:
                continue

        # Wenxin's current container includes thinking/search steps before the
        # final Markdown. Never fall back to the whole container in that layout.
        try:
            if await container.locator(".ai-entry-block.ai-thinking-steps").count():
                return ""
            return self._clean_answer_text(await container.inner_text(timeout=2000))
        except Exception:
            return ""

    async def _last_answer_container(self, page):
        selectors = [
            "#conversation-flow-content .conversation-flow-answer-container .cs-answer-container",
            "#conversation-flow-content .conversation-flow-answer-container .answer-container",
            ".conversation-flow-answer-container",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).last
                if await locator.is_visible(timeout=500):
                    return locator
            except Exception:
                continue
        return None

    def _clean_answer_text(self, text: str) -> str:
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped in ANSWER_NOISE_MARKERS:
                continue
            if stripped in {"思考已停止", "深度思考"}:
                continue
            lines.append(stripped)
        return "\n".join(lines).strip()

    async def _extract_platform_reported_search(self, page) -> dict:
        container = await self._last_answer_container(page)
        if container is None:
            return project_platform_search_observation("")
        try:
            locator = container.locator(".ai-entry-block.ai-thinking-steps").last
            if await locator.is_visible(timeout=500):
                return project_platform_search_observation(await locator.inner_text(timeout=2000))
        except Exception:
            pass
        return project_platform_search_observation("")

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
        container = await self._last_answer_container(page)
        if container is None:
            return ""
        for selector in [
            ".ai-entry-block.ai-markdown .cosd-markdown-content",
            ".ai-entry-block.ai-markdown",
        ]:
            try:
                locator = container.locator(selector).last
                if await locator.is_visible(timeout=500):
                    return await locator.evaluate("node => node.innerHTML")
            except Exception:
                continue
        try:
            if await container.locator(".ai-entry-block.ai-thinking-steps").count():
                return ""
            return await container.evaluate("node => node.innerHTML")
        except Exception:
            pass
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
