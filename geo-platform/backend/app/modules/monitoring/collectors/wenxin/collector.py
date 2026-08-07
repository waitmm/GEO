from __future__ import annotations

import asyncio
import hashlib
import html as html_lib
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
    BrowserProfileLockedError,
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
from app.modules.monitoring.collectors.wenxin.url_normalizer import canonicalize_url, clean_resolved_url, domain_from_url, is_static_resource


class WenxinWebCollector(BaseCollector):
    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None
        self._conversation_id = ""
        self._last_reference_metrics = {}
        self._last_reference_panel_html = ""
        self._network_events = []
        self._network_body_tasks = []
        self._search_result_payloads = []
        self._capture_network = False
        self._session_active = False

    def _find_chromium_path(self) -> str | None:
        candidates = []
        # 1. 环境变量 CHROMIUM_EXECUTABLE_PATH
        env_path = os.environ.get("CHROMIUM_EXECUTABLE_PATH")
        if env_path:
            candidates.append(env_path)
        # 2. Playwright Chromium avoids macOS handing a launch to an existing
        # user Chrome session, which breaks persistent-context collection.
        system = platform.system()
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
        # 3. 系统 Chrome（macOS / Linux / Windows）作为兜底。
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
        """在当前已打开的浏览器窗口中采集一条独立 Prompt。"""
        settings = get_settings()
        await self._ensure_active_session(settings)
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
            "args": ["--no-first-run", "--disable-dev-shm-usage"],
        }
        if chrome_path:
            browser_options["executable_path"] = chrome_path
        self._playwright = await async_playwright().start()
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(**browser_options)
        except Exception as exc:
            await self._end_browser_session()
            self._raise_browser_launch_error(exc, profile_dir)
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

    async def _ensure_active_session(self, settings) -> None:
        if self._page is not None and not self._page.is_closed():
            return
        await self._end_browser_session()
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise ConfigurationError("未安装 Playwright，请先安装依赖并执行 playwright install chromium") from exc
        await self._start_browser_session(async_playwright, settings)

    async def _collect_one(self, run, settings) -> CollectorResult:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        except Exception as exc:
            raise ConfigurationError("Playwright 导入失败") from exc

        self._network_events = []
        self._network_body_tasks = []
        self._search_result_payloads = []
        self._capture_network = True
        actual_query = run.original_query
        try:
            if not self._page.url.startswith(("https://chat.baidu.com/", "https://wenxin.baidu.com/")):
                await self._page.goto(
                    settings.wenxin_web_url,
                    wait_until="domcontentloaded",
                    timeout=settings.wenxin_browser_timeout_seconds * 1000,
                )
                await self._page.wait_for_timeout(3000)
            await self._raise_for_login_or_captcha(self._page)
            await self._prepare_collection_mode(self._page, run.collection_mode)
            await self._submit_query(self._page, actual_query)
            run.page_query = actual_query
            run.retrieval_query = actual_query
            answer_text = await self._wait_answer_complete(self._page, actual_query, settings.wenxin_browser_timeout_seconds)
            await self._drain_network_body_tasks()
            answer_html = await self._extract_answer_html(self._page)
            references = await self._extract_references(self._page)
            retrieval_candidates = await self._extract_retrieval_candidates(self._page, actual_query)
            artifacts = await self._capture_page_artifacts(self._page)
            for index, payload in enumerate(self._search_result_payloads, start=1):
                artifacts.append(
                    {
                        "artifact_type": "search_result_response",
                        "filename": f"searchresult-{index}.json",
                        "content": payload.get("body") or "",
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
                references=references,
                retrieval_candidates=retrieval_candidates,
                artifacts=artifacts,
                metrics={**self._last_reference_metrics, "retrieval_candidate_count": len(retrieval_candidates)},
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
        profile_dir = Path(browser_options.get("user_data_dir") or settings.wenxin_profile_dir)
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(**browser_options)
        except Exception as exc:
            await self._end_browser_session()
            self._raise_browser_launch_error(exc, profile_dir)
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

    def _raise_browser_launch_error(self, exc: Exception, profile_dir: Path) -> None:
        message = str(exc)
        lock_markers = (
            "正在现有的浏览器会话中打开",
            "ProcessSingleton",
            "SingletonLock",
            "another browser is running",
            "user data directory is already in use",
            "Target page, context or browser has been closed",
        )
        if any(marker.lower() in message.lower() for marker in lock_markers):
            raise BrowserProfileLockedError(
                f"文心浏览器 Profile 正被占用，请先关闭使用该目录的 Chrome 后重试：{profile_dir}"
            ) from exc
        raise exc

    def _record_response(self, response) -> None:
        if not self._capture_network:
            return
        try:
            event = {
                "captured_at": datetime.utcnow().isoformat() + "Z",
                "url": self._safe_network_url(response.url),
                "status": response.status,
                "resource_type": response.request.resource_type,
                "method": response.request.method,
            }
            self._network_events.append(event)
            if self._should_capture_search_result_body(response):
                self._network_body_tasks.append(asyncio.create_task(self._record_search_result_body(response, event)))
        except Exception:
            return

    def _should_capture_search_result_body(self, response) -> bool:
        try:
            parsed = urllib.parse.urlsplit(response.url)
            return (
                response.status == 200
                and parsed.netloc == "chat.baidu.com"
                and parsed.path == "/csaitab/searchresult"
            )
        except Exception:
            return False

    async def _record_search_result_body(self, response, event: dict) -> None:
        try:
            body = await response.text()
        except Exception:
            return
        if not body:
            return
        self._search_result_payloads.append({**event, "body": body[:2_000_000]})

    async def _drain_network_body_tasks(self) -> None:
        if not self._network_body_tasks:
            return
        tasks = list(self._network_body_tasks)
        self._network_body_tasks = []
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
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
        await page.wait_for_timeout(500)
        for selector in INPUT_CANDIDATES:
            try:
                locator = page.locator(selector).last
                await locator.wait_for(state="visible", timeout=1500)
                await locator.scroll_into_view_if_needed(timeout=1500)
                await locator.click(timeout=2000)
                tag_name = await locator.evaluate("node => node.tagName.toLowerCase()")
                if tag_name == "textarea" or tag_name == "input":
                    await locator.fill("")
                    await locator.evaluate(
                        """(node, value) => {
                            node.value = value;
                            node.dispatchEvent(new Event('input', { bubbles: true }));
                            node.dispatchEvent(new Event('change', { bubbles: true }));
                        }""",
                        query,
                    )
                    current_value = await locator.input_value(timeout=1000)
                    if current_value != query:
                        await locator.fill(query)
                else:
                    await locator.evaluate(
                        """(node, value) => {
                            node.textContent = value;
                            node.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                        }""",
                        query,
                    )
                await self._click_submit(page)
                await page.wait_for_timeout(2000)
                return
            except Exception as exc:
                last_error = exc
                continue
        try:
            await page.locator("body").click(timeout=2000)
            await page.keyboard.insert_text(query)
            await self._click_submit(page)
            await page.wait_for_timeout(2000)
            return
        except Exception as exc:
            last_error = exc
        raise PageStructureError(f"未找到可输入的问题输入框: {last_error}")

    async def _click_submit(self, page) -> None:
        for selector in SUBMIT_BUTTON_CANDIDATES:
            try:
                locator = page.locator(selector).last
                await locator.wait_for(state="visible", timeout=1000)
                await locator.click(timeout=2000)
                return
            except Exception:
                continue
        try:
            await page.keyboard.press("Meta+Enter")
        except Exception:
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

    def _strip_reference_block(self, text: str) -> str:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if not lines:
            return ""
        start = next((index for index, line in enumerate(lines[:4]) if re.match(REFERENCE_TEXT_PATTERN, line)), -1)
        if start < 0:
            return "\n".join(lines).strip()

        match = re.match(REFERENCE_TEXT_PATTERN, lines[start])
        if not match:
            return "\n".join(lines).strip()

        expected_count = int(match.group(1) or 0)
        index = start + 1
        consumed = 0
        while index < len(lines) and consumed < expected_count:
            line = lines[index]
            if re.match(r"^\d+[.．、]\s*$", line):
                index += 2
                consumed += 1
                continue
            if re.match(r"^\d+[.．、]\s*\S+", line):
                index += 1
                consumed += 1
                continue
            if consumed == 0:
                break
            index += 1
        return "\n".join(lines[index:]).strip()

    def _is_substantial_answer(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text or "")
        if len(compact) < 20:
            return False
        if re.match(r"^(理解问题|检索\d+篇结果|调用工具|搜索.+篇资料)$", compact):
            return False
        return True

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
                answer = self._strip_reference_block("\n".join(lines).strip())
                if self._is_substantial_answer(answer):
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

        initial_dom_items = await self._reference_dom_items(page, expected_count)
        initial_html_items = self._reference_items_from_html(await page.content(), expected_count)
        initial_items = self._merge_reference_items([initial_dom_items, initial_html_items], expected_count)
        if self._has_complete_reference_indexes(initial_items, expected_count):
            resolved = [resolve_reference_url(item, []) for item in initial_items[:expected_count]]
            self._last_reference_metrics.update(
                {
                    "dom_reference_count": len(resolved),
                    "parsed_reference_count": sum(bool(item.get("display_title")) for item in resolved),
                    "resolved_url_count": sum(bool(item.get("url")) for item in resolved),
                }
            )
            return resolved

        await self._open_reference_panel(page)
        panel_dom_items = await self._reference_dom_items(page, expected_count)
        panel_html_items = self._reference_items_from_html(await page.content(), expected_count)
        await self._scroll_reference_panels(page)
        self._last_reference_panel_html = await self._reference_panel_html(page)
        scrolled_dom_items = await self._reference_dom_items(page, expected_count)
        scrolled_html_items = self._reference_items_from_html(await page.content(), expected_count)
        dom_items = self._merge_reference_items(
            [
                initial_dom_items,
                initial_html_items,
                panel_dom_items,
                panel_html_items,
                scrolled_dom_items,
                scrolled_html_items,
            ],
            expected_count,
        )
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

    def _reference_items_from_html(self, page_html: str, expected_count: int) -> list[dict]:
        candidates = []
        lists = re.findall(r'<ol\b[^>]*data-show-ext="([^"]+)"[^>]*>(.*?)</ol>', page_html or "", flags=re.S)
        for order, (raw_ext, list_html) in enumerate(lists):
            try:
                show_ext = json.loads(html_lib.unescape(raw_ext))
            except json.JSONDecodeError:
                show_ext = {}
            total_num = int(show_ext.get("total_num") or show_ext.get("totalNum") or 0)
            items = []
            for fallback_index, match in enumerate(
                re.finditer(r'<li\b[^>]*data-long-press-ext-info="([^"]+)"[^>]*>(.*?)</li>', list_html, flags=re.S),
                start=1,
            ):
                raw_info = html_lib.unescape(match.group(1))
                try:
                    ext_info = json.loads(raw_info)
                except json.JSONDecodeError:
                    ext_info = {}
                item_html = match.group(0)
                index_match = re.search(r'<[^>]*class="[^"]*_index_[^"]*"[^>]*>\s*(\d+)', item_html)
                reference_index = int(index_match.group(1)) if index_match else fallback_index
                title = (ext_info.get("linkTitle") or ext_info.get("title") or "").strip()
                if not title:
                    text_match = re.search(r'<[^>]*class="[^"]*_text_[^"]*"[^>]*>(.*?)</[^>]+>', item_html, flags=re.S)
                    if text_match:
                        title = re.sub(r"<[^>]+>", "", html_lib.unescape(text_match.group(1))).strip()
                title = re.sub(r"\s+", " ", html_lib.unescape(title)).strip()
                if len(title) > 500:
                    title = title[:500]
                if len(title) < 4:
                    continue
                url = ext_info.get("link") or ext_info.get("linkUrl") or ext_info.get("url") or ext_info.get("href") or ""
                items.append(
                    {
                        "reference_index": reference_index,
                        "display_title": title,
                        "href": url,
                        "outer_html": item_html,
                        "serialized": raw_info,
                        "ancestor_outer_html": [list_html],
                    }
                )
            if items:
                score = (1000 if total_num == expected_count else 0) + len(items) + order / 1000
                candidates.append((score, items))
        if not candidates:
            return []
        return max(candidates, key=lambda item: item[0])[1]

    def _merge_reference_items(self, item_groups: list[list[dict]], expected_count: int) -> list[dict]:
        by_index: dict[int, dict] = {}
        by_title: dict[str, dict] = {}
        for group in item_groups:
            for item in group:
                title = (item.get("display_title") or "").strip()
                if not title:
                    continue
                try:
                    index = int(item.get("reference_index") or 0)
                except (TypeError, ValueError):
                    index = 0
                if 1 <= index <= expected_count:
                    current = by_index.get(index)
                    if current is None or self._reference_item_score(item) > self._reference_item_score(current):
                        by_index[index] = item
                    continue
                by_title.setdefault(title, item)

        next_index = 1
        for item in by_title.values():
            while next_index in by_index and next_index <= expected_count:
                next_index += 1
            if next_index > expected_count:
                break
            by_index[next_index] = {**item, "reference_index": next_index}

        return [by_index[index] for index in sorted(by_index)]

    def _has_complete_reference_indexes(self, items: list[dict], expected_count: int) -> bool:
        if expected_count <= 0:
            return False
        indexes = {int(item.get("reference_index") or 0) for item in items}
        return all(index in indexes for index in range(1, expected_count + 1))

    def _reference_item_score(self, item: dict) -> int:
        url_keys = [
            "href",
            "data-url",
            "data-href",
            "data-link",
            "data-source-url",
            "data-target-url",
            "data-jump-url",
            "data-redirect-url",
            "url",
        ]
        score = sum(20 for key in url_keys if item.get(key))
        score += 10 if item.get("serialized") else 0
        score += min(len(item.get("outer_html") or ""), 1000) // 100
        return score

    async def _extract_retrieval_candidates(self, page, query: str) -> list[dict]:
        try:
            raw_items = await page.locator("body").evaluate(
                """(body) => {
                    const clean = value => String(value || '')
                        .replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
                    const parseJson = value => {
                        try { return JSON.parse(value || '{}'); } catch { return {}; }
                    };
                    const textOf = (root, selectors) => {
                        for (const selector of selectors) {
                            const node = root.querySelector(selector);
                            const text = clean(node?.innerText || node?.textContent || '');
                            if (text) return text;
                        }
                        return '';
                    };
                    const attrOf = (root, names) => {
                        for (const name of names) {
                            const node = root.matches?.(`[${name}]`) ? root : root.querySelector(`[${name}]`);
                            const value = clean(node?.getAttribute(name) || '');
                            if (value && value !== '#') return value;
                        }
                        return '';
                    };
                    const cards = Array.from(body.querySelectorAll('[data-show-ext]'))
                        .filter(node => {
                            const ext = parseJson(node.getAttribute('data-show-ext'));
                            return ext.value === 'all_net_search_result' || ext.component_name === 'searchResult';
                        });
                    const results = [];
                    const seen = new Set();
                    for (const card of cards) {
                        const ext = parseJson(card.getAttribute('data-show-ext'));
                        const title = textOf(card, [
                            '.cosc-title-slot',
                            '.cosc-title',
                            'h3',
                            '[class*="title"]'
                        ]).replace(/^\\d+[.、]\\s*/, '');
                        const snippet = textOf(card, [
                            'p[class*="cos-line-clamp"]',
                            'p[class*="content"]',
                            '[class*="content"]'
                        ]);
                        const source = textOf(card, ['.cosc-source-text', '[class*="source-text"]']);
                        const url = attrOf(card, ['href', 'data-url', 'data-href', 'data-link', 'data-target-url']);
                        if (title.length < 4 || title.length > 300) continue;
                        if (/共参考\\s*\\d+\\s*篇资料|复制|分享|重新生成|有用|没用/.test(title)) continue;
                        const key = `${title}|${snippet.slice(0, 80)}`;
                        if (seen.has(key)) continue;
                        seen.add(key);
                        results.push({
                            rank: Number(ext.abspos || ext.relativepos || results.length + 1),
                            title,
                            snippet,
                            source,
                            url,
                            outer_html: card.outerHTML || ''
                        });
                    }
                    return results.sort((a, b) => a.rank - b.rank);
                }"""
            )
        except Exception:
            return []

        api_items = self._search_result_items_from_payloads(query)
        raw_items = self._merge_retrieval_items(raw_items or [], api_items)

        candidates: list[dict] = []
        seen_keys: set[str] = set()
        for index, item in enumerate(raw_items or [], start=1):
            title = (item.get("title") or "").strip()
            snippet = (item.get("snippet") or "").strip()
            url = clean_resolved_url(item.get("url") or "")
            if url and is_static_resource(url):
                url = ""
            key = f"{title}|{url or snippet[:80]}"
            if not title or key in seen_keys:
                continue
            seen_keys.add(key)
            candidates.append(
                {
                    "retrieval_query": query,
                    "rank": int(item.get("rank") or index),
                    "title": title,
                    "url": url,
                    "canonical_url": canonicalize_url(url) if url else "",
                    "domain": domain_from_url(url) if url else (item.get("source") or ""),
                    "snippet": snippet,
                    "evidence_path": "page.html#all_net_search_result",
                }
            )
        return candidates

    def _merge_retrieval_items(self, dom_items: list[dict], api_items: list[dict]) -> list[dict]:
        merged = [dict(item) for item in dom_items]
        by_title = {self._retrieval_title_key(item.get("title") or ""): item for item in merged}
        for item in api_items:
            key = self._retrieval_title_key(item.get("title") or "")
            if not key:
                continue
            existing = by_title.get(key)
            if existing:
                if item.get("url") and not existing.get("url"):
                    existing["url"] = item.get("url") or ""
                    existing["source"] = item.get("source") or existing.get("source") or ""
                    existing["api_rank"] = item.get("rank")
                if item.get("snippet") and not existing.get("snippet"):
                    existing["snippet"] = item.get("snippet") or ""
                continue
            merged.append(item)
            by_title[key] = item
        return sorted(merged, key=lambda item: int(item.get("rank") or item.get("api_rank") or 9999))

    def _retrieval_title_key(self, value: str) -> str:
        value = self._clean_retrieval_text(value)
        value = re.sub(r"\s+", "", value).strip().lower()
        return value[:120]

    def _clean_retrieval_text(self, value: str) -> str:
        value = re.sub(r"<[^>]+>", "", html_lib.unescape(value or ""))
        value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value)
        return re.sub(r"\s+", " ", value).strip()

    def _search_result_items_from_payloads(self, query: str) -> list[dict]:
        items: list[dict] = []
        for payload in self._search_result_payloads:
            body = payload.get("body") or ""
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                continue
            items.extend(self._search_result_items_from_node(data, query))
        seen: set[str] = set()
        unique: list[dict] = []
        for item in items:
            title = (item.get("title") or "").strip()
            url = clean_resolved_url(item.get("url") or "")
            if url and is_static_resource(url):
                continue
            key = f"{self._retrieval_title_key(title)}|{canonicalize_url(url) if url else ''}"
            if not title or not url or key in seen:
                continue
            seen.add(key)
            unique.append({**item, "url": url})
        return unique

    def _search_result_items_from_node(self, node, query: str) -> list[dict]:
        results: list[dict] = []
        if isinstance(node, dict):
            item = self._search_result_item_from_dict(node, query)
            if item:
                results.append(item)
            for value in node.values():
                results.extend(self._search_result_items_from_node(value, query))
        elif isinstance(node, list):
            for value in node:
                results.extend(self._search_result_items_from_node(value, query))
        elif isinstance(node, str) and ("http" in node and ("title" in node or "url" in node)):
            try:
                nested = json.loads(html_lib.unescape(node))
            except json.JSONDecodeError:
                nested = None
            if nested is not None:
                results.extend(self._search_result_items_from_node(nested, query))
        return results

    def _search_result_item_from_dict(self, data: dict, query: str) -> dict | None:
        title = self._first_text_value(
            data,
            [
                "title",
                "titleText",
                "displayTitle",
                "display_title",
                "name",
                "resultTitle",
                "result_title",
            ],
        )
        url = self._first_url_value(
            data,
            [
                "url",
                "mu",
                "link",
                "linkUrl",
                "link_url",
                "href",
                "sourceUrl",
                "source_url",
                "targetUrl",
                "target_url",
                "jumpUrl",
                "jump_url",
                "originUrl",
                "origin_url",
                "realUrl",
                "real_url",
                "displayUrl",
                "display_url",
            ],
        )
        if not title or not url:
            return None
        title = self._clean_retrieval_text(title)
        if len(title) < 4 or len(title) > 500:
            return None
        snippet = self._first_text_value(
            data,
            ["abstract", "summary", "desc", "description", "content", "snippet"],
        )
        source = self._first_text_value(data, ["source", "siteName", "site_name", "author", "provider"])
        rank = self._first_int_value(data, ["rank", "abspos", "relativepos", "position", "index", "order"])
        return {
            "retrieval_query": query,
            "rank": rank or 9999,
            "title": title[:300],
            "snippet": self._clean_retrieval_text(snippet or ""),
            "source": self._clean_retrieval_text(source or ""),
            "url": url,
            "outer_html": "",
        }

    def _first_text_value(self, data: dict, keys: list[str]) -> str:
        lower_keys = {key.lower() for key in keys}
        for key, value in data.items():
            if key.lower() not in lower_keys:
                continue
            if isinstance(value, (str, int, float)):
                return str(value).strip()
            if isinstance(value, dict):
                nested = self._first_text_value(value, ["text", "content", "value"])
                if nested:
                    return nested
        return ""

    def _first_url_value(self, data: dict, keys: list[str]) -> str:
        lower_keys = {key.lower() for key in keys}
        for key, value in data.items():
            if key.lower() not in lower_keys or not isinstance(value, str):
                continue
            value = html_lib.unescape(value).strip()
            if value.startswith(("http://", "https://")):
                return value
        return ""

    def _first_int_value(self, data: dict, keys: list[str]) -> int | None:
        lower_keys = {key.lower() for key in keys}
        for key, value in data.items():
            if key.lower() not in lower_keys:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

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
                    const parseJson = value => {
                        try { return JSON.parse(value || '{}'); } catch { return {}; }
                    };
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
                    const buildItem = (el, fallbackIndex) => {
                        const extInfo = parseJson(el.getAttribute('data-long-press-ext-info'));
                        const indexText = clean(
                            el.querySelector('[class*="_index_"]')?.innerText ||
                            el.querySelector('[class*="_index_"]')?.textContent || ''
                        );
                        const parsedIndex = Number((indexText.match(/\\d+/) || [])[0]);
                        let title = clean(
                            el.querySelector('[class*="_text_"]')?.innerText ||
                            el.querySelector('[class*="_text_"]')?.textContent ||
                            extInfo.linkTitle ||
                            el.innerText || el.textContent ||
                            el.getAttribute('aria-label') || el.getAttribute('title')
                        ).replace(/^\\d+[.、]\\s*/, '');
                        if (title.length > 500) title = title.slice(0, 500);
                        if (title.length < 4) return null;
                        if (/共参考\\s*\\d+\\s*篇资料|收起|展开|关闭|复制|分享|重新生成|有用|没用|赞|踩/.test(title)) return null;
                        const item = {
                            reference_index: Number.isFinite(parsedIndex) && parsedIndex > 0 ? parsedIndex : fallbackIndex,
                            display_title: title,
                            outer_html: el.outerHTML || '',
                            serialized: el.getAttribute('data-long-press-ext-info') || '',
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
                        return item;
                    };
                    const referenceLists = Array.from(body.querySelectorAll(
                        'ol[class*="_reference_"], ol[class*="reference"], ol[data-show-ext]'
                    )).map((list, order) => {
                        const nodes = Array.from(list.querySelectorAll(
                            'li[class*="_reference-item_"], li[data-long-press-ext-info]'
                        ));
                        const indexes = nodes.map(node => {
                            const text = clean(
                                node.querySelector('[class*="_index_"]')?.innerText ||
                                node.querySelector('[class*="_index_"]')?.textContent || ''
                            );
                            return Number((text.match(/\\d+/) || [])[0]);
                        }).filter(Number.isFinite);
                        const showExt = parseJson(list.getAttribute('data-show-ext'));
                        const totalNum = Number(showExt.total_num || showExt.totalNum || 0);
                        const maxIndex = indexes.length ? Math.max(...indexes) : 0;
                        const uniqueCount = new Set(indexes).size || nodes.length;
                        const score =
                            (totalNum === expectedCount ? 1000 : 0) +
                            (maxIndex === expectedCount ? 500 : 0) +
                            (uniqueCount === expectedCount ? 200 : 0) -
                            Math.abs(uniqueCount - expectedCount) +
                            order / 1000;
                        return {list, nodes, order, totalNum, maxIndex, uniqueCount, score};
                    }).filter(candidate => candidate.nodes.length > 0);
                    referenceLists.sort((a, b) => b.score - a.score);
                    const referenceList = referenceLists[0];
                    if (referenceList && (referenceList.totalNum === expectedCount || referenceList.maxIndex === expectedCount)) {
                        const results = [];
                        const seenIndexes = new Set();
                        for (const el of referenceList.nodes) {
                            const item = buildItem(el, results.length + 1);
                            if (!item) continue;
                            if (seenIndexes.has(item.reference_index)) continue;
                            results.push(item);
                            seenIndexes.add(item.reference_index);
                        }
                        return results.sort((a, b) => a.reference_index - b.reference_index);
                    }
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
                        const item = buildItem(el, results.length + 1);
                        if (!item) continue;
                        const child = el.querySelector(
                            'a,button,[role="link"],[data-url],[data-href],[data-link]'
                        );
                        if (child && clean(child.innerText) === item.display_title) continue;
                        if (seen.has(item.display_title)) continue;
                        const style = getComputedStyle(el);
                        const clickable = el.matches('a,button,[role="link"],[data-url],[data-href],[data-link]') ||
                            el.hasAttribute('data-long-press-ext-info') ||
                            style.cursor === 'pointer' || attrs.some(name => el.hasAttribute(name));
                        if (!clickable) continue;
                        results.push(item);
                        seen.add(item.display_title);
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
            if len(title) >= 4:
                titles.append(title[:500])
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
            if len(title) >= 4 and title not in existing:
                truncated = title[:500]
                titles.append(truncated)
                existing.add(truncated)
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
        artifacts = []
        try:
            html = await page.locator("body").evaluate("node => node.outerHTML")
            artifacts.append({"artifact_type": "page_html", "filename": "page.html", "content": html, "mime_type": "text/html"})
        except Exception as exc:
            artifacts.append({"artifact_type": "page_html_error", "filename": "page-html-error.txt", "content": str(exc), "mime_type": "text/plain"})
        screenshot = await self._capture_reference_screenshot(page)
        if screenshot:
            artifacts.append(
                {
                    "artifact_type": "reference_sources_screenshot",
                    "filename": "reference-sources.png",
                    "content_bytes": screenshot,
                    "mime_type": "image/png",
                }
            )
        return artifacts

    async def _capture_reference_screenshot(self, page) -> bytes | None:
        expected_count = int(self._last_reference_metrics.get("ui_declared_count") or 0)
        selectors = [
            'ol[data-show-ext]',
            'ol[class*="_reference_"]',
            'ol[class*="reference"]',
            *REFERENCE_PANEL_CANDIDATES,
        ]
        best = None
        best_score = -1
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except Exception:
                continue
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if not await candidate.is_visible(timeout=300):
                        continue
                    text = await candidate.inner_text(timeout=800)
                    item_count = await candidate.locator("[data-long-press-ext-info], li").count()
                    score = len(text or "") + item_count * 100
                    if expected_count and item_count == expected_count:
                        score += 10000
                    if score > best_score:
                        best = candidate
                        best_score = score
                except Exception:
                    continue
        if best is None:
            return None
        try:
            return await best.screenshot(timeout=10000)
        except Exception:
            return None
