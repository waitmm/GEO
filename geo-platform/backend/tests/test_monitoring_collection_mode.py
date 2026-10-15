from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, BrowserMonitorRun, MonitoringBatch, Project, Prompt
from app.modules.monitoring.collectors.wenxin.collector import WenxinWebCollector
from app.modules.monitoring.collectors.wenxin.exceptions import ConversationResetError, RateLimitedError
from app.modules.monitoring.services import create_browser_task, queue_due_daily_prompt_tasks


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_create_browser_task_defaults_to_single_independent(db):
    project = Project(id=1, organization_id=1, name="Mode", brand_name="Brand")
    prompt = Prompt(id=1, project_id=1, prompt_text="抖音跳转链接", title="抖音跳转链接")
    db.add_all([project, prompt])
    db.commit()

    task = create_browser_task(db, project, [prompt], run_count=2, execute_now=False)
    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == task.id).all()

    assert len(runs) == 2
    assert all(run.collection_mode == "single_independent" for run in runs)


def test_daily_prompt_queue_uses_single_independent(db):
    project = Project(id=1, organization_id=1, name="Daily", brand_name="Brand")
    prompt = Prompt(
        id=1,
        project_id=1,
        prompt_text="抖音跳转链接",
        title="抖音跳转链接",
        enabled=True,
        daily_tracking_enabled=True,
        daily_schedule_time="00:00",
        daily_sample_count=2,
    )
    db.add_all([project, prompt])
    db.commit()

    tasks, queued_run_count = queue_due_daily_prompt_tasks(db, project, execute_now=False)
    batch = db.query(MonitoringBatch).one()

    assert len(tasks) == 1
    assert queued_run_count == 2
    assert batch.collection_mode == "single_independent"


class _FakeLocator:
    def __init__(self, visible: bool, counts: list[int] | None = None) -> None:
        self._visible = visible
        self._counts = list(counts or [])

    @property
    def first(self) -> "_FakeLocator":
        return self

    async def count(self) -> int:
        if self._counts:
            return self._counts.pop(0)
        return 0

    async def is_visible(self, timeout: int = 0) -> bool:
        return self._visible

    async def click(self, timeout: int = 0) -> None:
        return None


class _FakePage:
    def __init__(self, counts: list[int], trigger_visible: bool = True) -> None:
        self._counts = counts
        self._trigger_visible = trigger_visible
        self.goto_calls = 0

    def locator(self, selector: str) -> _FakeLocator:
        if selector == "#conversation-flow-content .conversation-flow-question-container":
            return _FakeLocator(True, self._counts)
        return _FakeLocator(True)

    def get_by_text(self, pattern, exact: bool = False) -> _FakeLocator:
        return _FakeLocator(self._trigger_visible)

    async def goto(self, *args, **kwargs) -> None:
        self.goto_calls += 1

    async def wait_for_timeout(self, timeout: int) -> None:
        return None


def test_prepare_collection_mode_raises_when_conversation_cannot_reset():
    collector = WenxinWebCollector()
    page = _FakePage([2, 2, 2, 2, 2, 2, 2, 2, 2], trigger_visible=False)

    with pytest.raises(ConversationResetError):
        asyncio.run(collector._prepare_collection_mode(page, "single_independent"))


def test_prepare_collection_mode_records_verified_zero_turn_gate():
    collector = WenxinWebCollector()
    page = _FakePage([0])

    asyncio.run(collector._prepare_collection_mode(page, "single_independent"))

    assert collector._actual_sampling_mode == "single_independent"
    assert collector._session_verification_basis == "PRE_SUBMIT_ZERO_TURN_DOM_GATE"


def test_collect_one_checks_independent_session_before_submitting(monkeypatch):
    collector = WenxinWebCollector()
    collector._page = object()
    calls: list[str] = []

    async def prepare(page, mode):
        calls.append(f"prepare:{mode}")

    async def submit(page, query):
        calls.append(f"submit:{query}")
        raise ConversationResetError("stop after order check")

    monkeypatch.setattr(collector, "_prepare_collection_mode", prepare)
    monkeypatch.setattr(collector, "_submit_query", submit)
    run = SimpleNamespace(collection_mode="single_independent", original_query="长链接缩短")

    with pytest.raises(ConversationResetError):
        asyncio.run(collector._collect_one(run, SimpleNamespace()))

    assert calls == ["prepare:single_independent", "submit:长链接缩短"]


def test_environment_reports_actual_verified_sampling_mode(tmp_path):
    collector = WenxinWebCollector()
    collector._requested_collection_mode = "single_independent"
    collector._actual_sampling_mode = "single_independent"
    collector._session_verification_basis = "PRE_SUBMIT_ZERO_TURN_DOM_GATE"
    collector._context = SimpleNamespace(browser=SimpleNamespace(version="test-browser"))
    page = SimpleNamespace(url="https://chat.baidu.com/")
    settings = SimpleNamespace(wenxin_profile_dir=str(tmp_path / "profile"))

    metadata = asyncio.run(collector._environment_metadata(page, settings))

    assert metadata["collection_mode"] == "single_independent"
    assert metadata["sampling_mode"] == "single_independent"
    assert metadata["session_verification_basis"] == "PRE_SUBMIT_ZERO_TURN_DOM_GATE"


def test_wenxin_http_429_is_a_stable_rate_limit_error():
    collector = WenxinWebCollector()
    collector._network_events = [{"status": 429, "url": "https://chat.baidu.com/api/chat"}]

    with pytest.raises(RateLimitedError, match="HTTP 429") as error:
        asyncio.run(collector._raise_for_rate_limit(object()))

    assert error.value.error_type == "rate_limited"


def test_wenxin_preserves_concise_quota_page_reason():
    collector = WenxinWebCollector()
    reason = collector._rate_limit_reason_from_text("提示\n今日提问次数已用完，请明日再试\n帮助")

    assert reason == "今日提问次数已用完，请明日再试"


def test_generic_failure_text_is_not_guessed_as_rate_limit():
    collector = WenxinWebCollector()

    assert collector._rate_limit_reason_from_text("服务暂时不可用，请稍后再试") == ""


class _SemanticRegionLocator:
    def __init__(self, *, text="", html="", visible=True, children=None, count_value=None, status=None):
        self.text = text
        self.html = html
        self.visible = visible
        self.children = children or {}
        self.count_value = count_value
        self.status = status

    @property
    def last(self):
        return self

    def locator(self, selector):
        return self.children.get(selector, _SemanticRegionLocator(visible=False, count_value=0))

    async def is_visible(self, timeout=0):
        return self.visible

    async def inner_text(self, timeout=0):
        return self.text

    async def evaluate(self, expression):
        return self.html

    async def get_attribute(self, name):
        return self.status if name == "data-status" else None

    async def count(self):
        if self.count_value is not None:
            return self.count_value
        return 1 if self.visible else 0


class _SemanticRegionPage:
    def __init__(self, container):
        self.container = container

    def locator(self, selector):
        if selector == "#conversation-flow-content .conversation-flow-answer-container .cs-answer-container":
            return self.container
        return _SemanticRegionLocator(visible=False, count_value=0)


def _semantic_region_page(*, include_final=True):
    final = _SemanticRegionLocator(
        text="这是完全独立的最终回答正文，不包含平台搜索过程。",
        html="<p>这是完全独立的最终回答正文，不包含平台搜索过程。</p>",
        visible=include_final,
    )
    thinking = _SemanticRegionLocator(
        text="搜索3个关键词 共参考28篇资料\n搜索关键词“抖音跳转链接”、“生成方法”、“使用规则”",
        visible=True,
    )
    container = _SemanticRegionLocator(
        text="搜索3个关键词\n搜索关键词“抖音跳转链接”、“生成方法”、“使用规则”\n这是完全独立的最终回答正文，不包含平台搜索过程。",
        html="<div>mixed</div>",
        children={
            ".ai-entry-block.ai-markdown .cosd-markdown-content": final,
            ".ai-entry-block.ai-markdown": final,
            ".ai-entry-block.ai-thinking-steps": thinking,
        },
        status="COMPLETE",
    )
    return _SemanticRegionPage(container)


def test_wenxin_collects_final_answer_and_search_process_as_separate_regions():
    collector = WenxinWebCollector()
    page = _semantic_region_page()

    answer = asyncio.run(collector._current_answer_text(page))
    answer_html = asyncio.run(collector._extract_answer_html(page))
    search = asyncio.run(collector._extract_platform_reported_search(page))

    assert answer == "这是完全独立的最终回答正文，不包含平台搜索过程。"
    assert "搜索关键词" not in answer
    assert answer_html == "<p>这是完全独立的最终回答正文，不包含平台搜索过程。</p>"
    assert search["terms"] == ["抖音跳转链接", "生成方法", "使用规则"]
    assert search["consumption_policy"] == "OBSERVATION_ONLY"


def test_wenxin_never_falls_back_to_mixed_container_when_final_region_is_missing():
    collector = WenxinWebCollector()
    page = _semantic_region_page(include_final=False)

    assert asyncio.run(collector._current_answer_text(page)) == ""
    assert asyncio.run(collector._extract_answer_html(page)) == ""


def test_wenxin_never_treats_generic_generating_placeholder_as_answer():
    collector = WenxinWebCollector()
    container = _SemanticRegionLocator(text="正在思考", status="GENERATING")
    page = _SemanticRegionPage(container)

    assert asyncio.run(collector._current_answer_text(page)) == ""
    assert asyncio.run(collector._answer_generation_complete(page)) is False


def test_wenxin_reference_title_containing_copy_is_not_treated_as_button_noise():
    collector = WenxinWebCollector()
    page_html = """
    <ol data-show-ext="{&quot;total_num&quot;:2}">
      <li data-long-press-ext-info="{&quot;link&quot;:&quot;https://example.com/one&quot;,&quot;linkTitle&quot;:&quot;普通引用标题&quot;}">
        <span class="_index_fixture">1.</span><span class="_text_fixture">普通引用标题</span>
      </li>
      <li data-long-press-ext-info="{&quot;link&quot;:&quot;https://example.com/two&quot;,&quot;linkTitle&quot;:&quot;3.02 复制打开抖音的链接规则&quot;}">
        <span class="_index_fixture">2.</span><span class="_text_fixture">3.02 复制打开抖音的链接规则</span>
      </li>
    </ol>
    """

    items = collector._reference_items_from_html(page_html, expected_count=2)

    assert [item["reference_index"] for item in items] == [1, 2]
    assert items[1]["display_title"] == "3.02 复制打开抖音的链接规则"
    assert collector._has_complete_reference_indexes(items, expected_count=2) is True


def test_wenxin_reference_merge_restores_item_missing_from_live_dom():
    collector = WenxinWebCollector()
    dom_items = [{"reference_index": 1, "display_title": "普通引用标题", "href": "https://example.com/one"}]
    html_items = [
        *dom_items,
        {
            "reference_index": 2,
            "display_title": "3.02 复制打开抖音的链接规则",
            "href": "https://example.com/two",
            "serialized": "source metadata",
        },
    ]

    merged = collector._merge_reference_items([dom_items, html_items], expected_count=2)

    assert [item["reference_index"] for item in merged] == [1, 2]
    assert collector._has_complete_reference_indexes(merged, expected_count=2) is True
