"""Citation Passage Intelligence V0 — Golden Case analysis engine.

P0.1 Content Acquisition → P0.2 Answer Claims → P0.3 Passage Segmentation
→ P0.4 Alignment → P0.5 Answer Need Map → P0.6 Brand Gap.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime
import hashlib
import html as _html
import json
import os
import platform
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable

from sqlalchemy.orm import Session

from app.models import (
    AnswerClaim,
    BrowserMonitorRun,
    PassageAlignment,
    ReferenceSource,
    RetrievalCandidate,
    SourceDocument,
)
from app.modules.monitoring.collectors.wenxin.url_normalizer import canonicalize_url, domain_from_url
from app.modules.optimization.service import _infer_platform_from_domain, DOMAIN_PLATFORM_MAP
from app.services.serialization import dumps, loads
from app.services.url_identity import url_identity_fields
from app.services.public_web import PublicWebError, guard_browser_context, public_get


# ---------------------------------------------------------------------------
# P0.1 Content Acquisition
# ---------------------------------------------------------------------------

FETCH_TIMEOUT = 8
USER_AGENT = "GEOAuditBot/0.2 (+https://github.com/waitmm/GEO)"

_HTML_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_MULTI_NL = re.compile(r"\n{3,}")
_MULTI_SP = re.compile(r"[ \t]{2,}")


def _normalize_url_for_fetch(url: str) -> str:
    """Normalize URL for fetching."""
    u = url.strip()
    if not u.startswith("http"):
        u = "https://" + u
    # Force HTTPS
    if u.startswith("http://"):
        u = "https://" + u[7:]
    parsed = urlparse(u)
    domain = parsed.netloc.lower()
    return f"https://{domain}{parsed.path}{'?'+parsed.query if parsed.query else ''}"


def _canonicalize_acquired_url(url: str) -> str:
    """Canonical URL used for source analysis; raw observed URL stays in original_url."""
    return canonicalize_url(url)


def _find_browser_executable_for_fetch() -> str | None:
    candidates: list[str] = []
    env_path = os.environ.get("CHROMIUM_EXECUTABLE_PATH")
    if env_path:
        candidates.append(env_path)

    system = platform.system()
    pw_cache_dir = "~/Library/Caches/ms-playwright" if system == "Darwin" else (
        "~/.cache/ms-playwright" if system == "Linux" else "~/AppData/Local/ms-playwright"
    )
    pw_cache = Path(os.path.expanduser(pw_cache_dir))
    if pw_cache.exists():
        for d in sorted(pw_cache.iterdir(), reverse=True):
            if d.is_dir() and "chromium" in d.name and "headless" not in d.name:
                if system == "Darwin":
                    candidates.append(str(d / "chrome-mac-x64" / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing"))
                elif system == "Linux":
                    candidates.append(str(d / "chrome-linux64" / "chrome"))
                else:
                    candidates.append(str(d / "chrome-win" / "chrome.exe"))

    if system == "Darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
    elif system == "Linux":
        candidates.extend(["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"])
    elif system == "Windows":
        candidates.extend([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ])

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _clean_text_from_html(html: str) -> str:
    clean = _SCRIPT_STYLE.sub(" ", html)
    clean = _HTML_TAG.sub(" ", clean)
    clean = _html.unescape(clean)
    clean = _MULTI_SP.sub(" ", clean)
    clean = _MULTI_NL.sub("\n\n", clean)
    return clean.strip()[:200000]


def _with_browser_fallback_reason(browser_reason: str, fallback_result: dict) -> dict:
    fallback_result["fetch_method"] = "HTTP兜底抓取"
    if fallback_result.get("fetch_status") == "FETCH_FAILED":
        fallback_reason = fallback_result.get("failure_reason") or "未返回具体错误"
        fallback_result["failure_reason"] = f"浏览器抓取失败：{browser_reason[:120]}；HTTP兜底失败：{fallback_reason[:120]}"
    return fallback_result


_SOURCE_BROWSER_OPTIONS = {
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "locale": "zh-CN",
    "viewport": {"width": 1440, "height": 900},
    "ignore_https_errors": False,
    "service_workers": "block",
    "accept_downloads": False,
    "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"},
}


def _launch_browser_context_for_fetch(playwright):
    executable_path = _find_browser_executable_for_fetch()
    launch_options = {
        "headless": True,
        "chromium_sandbox": True,
        "args": ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
    }
    if executable_path:
        launch_options["executable_path"] = executable_path
    browser = playwright.chromium.launch(**launch_options)
    try:
        context = browser.new_context(**_SOURCE_BROWSER_OPTIONS)
    except BaseException:
        browser.close()
        raise
    return browser, context, "后台浏览器抓取"


def fetch_page_playwright(urls: list[str], progress_callback: Callable[[int, int], None] | None = None) -> list[dict]:
    """Fetch multiple URLs using Playwright with full page rendering."""
    results = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, ExitStack() as resources:
            try:
                browser, context, fetch_method = _launch_browser_context_for_fetch(p)
            except Exception as exc:
                fallback_results = []
                for index, url in enumerate(urls, start=1):
                    fallback_results.append(_with_browser_fallback_reason(str(exc), fetch_page(url)))
                    if progress_callback:
                        progress_callback(index, len(urls))
                return fallback_results
            resources.callback(browser.close)
            for index, url in enumerate(urls):
                if index:
                    context = browser.new_context(**_SOURCE_BROWSER_OPTIONS)
                network = guard_browser_context(context)
                page = context.new_page()
                normalized = _normalize_url_for_fetch(url)
                result = {
                    "url": url,
                    "canonical_url": _canonicalize_acquired_url(normalized),
                    "domain": domain_from_url(normalized),
                    "fetch_status": "pending", "failure_reason": "", "title": "",
                    "raw_html": "", "clean_text": "", "fetch_time": datetime.utcnow(),
                    "fetch_method": fetch_method,
                }
                for attempt in range(2):  # Retry once
                    try:
                        page.goto(normalized, wait_until="domcontentloaded", timeout=25000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception:
                            pass
                        # Scroll to load lazy content
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(500)
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(300)
                        html = page.content()
                        final_url = page.url or normalized
                        title = page.title() or ""
                        # Get all visible text
                        body = page.inner_text("body") if page.locator("body").count() > 0 else ""
                        clean = _MULTI_NL.sub("\n\n", body.strip())[:200000]
                        if len(clean) < 50:
                            clean = _clean_text_from_html(html)
                        result["raw_html"] = html[:500000]
                        result["canonical_url"] = _canonicalize_acquired_url(final_url)
                        result["final_url"] = final_url
                        result["domain"] = domain_from_url(final_url)
                        result["title"] = title
                        result["clean_text"] = clean
                        result["fetch_status"] = "SUCCESS" if len(clean) > 200 and not network["blocked"] else "PARTIAL"
                        if len(clean) >= 200000:
                            result["fetch_status"] = "PARTIAL"
                            result["failure_reason"] = "正文达到保存上限，不能声明完整页面"
                        if network["blocked"]:
                            result["failure_reason"] = "页面资源受限：" + ",".join(sorted(set(network["blocked"])))
                        break
                    except Exception as e:
                        if network["main_failure"] or attempt == 1:
                            result["fetch_status"] = "FETCH_FAILED"
                            result["failure_reason"] = network["main_failure"] or type(e).__name__
                            break
                result["network_policy"] = "PUBLIC_DNS_PINNED_TLS_VERIFIED_V1"
                result["network_requests"] = network["requests"]
                result["acquisition_receipt"] = _acquisition_receipt(result, network['documents'])
                context.close()
                results.append(result)
                if progress_callback:
                    progress_callback(len(results), len(urls))
    except ImportError:
        for index, url in enumerate(urls, start=1):
            results.append(_with_browser_fallback_reason("未安装 Playwright", fetch_page(url)))
            if progress_callback:
                progress_callback(index, len(urls))
    return results


def fetch_page(url: str) -> dict:
    """Fetch a URL and extract clean text."""
    normalized = _normalize_url_for_fetch(url)
    domain = domain_from_url(normalized)
    result = {
        "url": url, "canonical_url": _canonicalize_acquired_url(normalized), "domain": domain,
        "fetch_status": "pending", "failure_reason": "", "title": "",
        "raw_html": "", "clean_text": "", "fetch_time": datetime.utcnow(), "fetch_method": "HTTP兜底抓取",
    }
    try:
        resp = public_get(normalized, timeout=FETCH_TIMEOUT)
        result["network_policy"] = "PUBLIC_DNS_PINNED_TLS_VERIFIED_V1"
        if resp.status >= 400:
            raise PublicWebError(f"PUBLIC_HTTP_{resp.status}")
        charset = re.search(r'charset=["\']?([\w-]+)', resp.headers.get('content-type', ''), re.I)
        try:
            html = resp.body.decode(charset.group(1) if charset else 'utf-8')
        except (UnicodeDecodeError, LookupError):
            html = resp.body.decode('gb18030', errors='replace')
        result["raw_html"] = html[:500000]
        result["canonical_url"] = _canonicalize_acquired_url(resp.url)
        result["final_url"] = resp.url
        result["domain"] = domain_from_url(resp.url)
        tm = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if tm:
            result["title"] = _html.unescape(tm.group(1).strip())
        result["clean_text"] = _clean_text_from_html(html)
        result["fetch_status"] = "SUCCESS" if len(result["clean_text"]) > 100 else "PARTIAL"
        if len(result["clean_text"]) >= 200000:
            result["fetch_status"] = "PARTIAL"
            result["failure_reason"] = "正文达到保存上限，不能声明完整页面"
        result["acquisition_receipt"] = _acquisition_receipt(result, list(resp.receipts))
    except Exception as e:
        result["fetch_status"] = "FETCH_FAILED"
        result["failure_reason"] = str(e) if isinstance(e, PublicWebError) else type(e).__name__
    return result


def _acquisition_receipt(result: dict, documents: list[dict]) -> dict:
    """Transport provenance, not a statement that the page's claims are true."""
    if not documents or result.get('fetch_status') != 'SUCCESS':
        return {}
    final_url = result.get('final_url', '')
    final = next((d for d in reversed(documents) if d['url'] == final_url), None)
    if not final or not 200 <= final['status'] < 300:
        return {}
    return {
        'contract_version': 'source-acquisition.v1',
        'requested_url': result['url'], 'final_url': final_url,
        'acquired_at': result['fetch_time'].isoformat(),
        'method': result['fetch_method'], 'network_policy': result['network_policy'],
        'documents': documents, 'content_hash': hashlib.sha256(result['clean_text'].strip().encode()).hexdigest(),
        'scope': 'TRANSPORT_AND_EXTRACTED_CONTENT_ONLY',
    }


def acquire_cited_sources(db: Session, run_ids: list[int]) -> dict:
    """Acquire content for all cited URLs in given runs.

    Uses Playwright browser for JS-rendered pages, falls back to urllib.
    """
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    # Deduplicate by canonical URL
    seen = set()
    unique_urls = []
    for ref in refs:
        url = ref.canonical_url or ref.url
        if url and url not in seen:
            seen.add(url)
            unique_urls.append((url, ref.domain, "CITED"))

    # Filter out already-acquired URLs (check both original_url and url)
    new_urls = []
    for url, domain, src_type in unique_urls:
        existing = db.query(SourceDocument).filter(
            (SourceDocument.original_url == url) | (SourceDocument.url == url)
        ).first()
        if not existing:
            new_urls.append(url)

    created, failed = 0, 0
    if new_urls:
        # Try Playwright first
        results = fetch_page_playwright(new_urls)
        for i, (url, domain, src_type) in enumerate([(u, d, s) for u, d, s in unique_urls if u in new_urls]):
            result = results[i] if i < len(results) else fetch_page(url)
            identity = url_identity_fields(url, result.get("canonical_url", url))
            doc = SourceDocument(
                url=identity["canonical_url"] or result.get("canonical_url", url), original_url=url,
                **identity,
                domain=domain, source_type=src_type,
                fetch_status=result["fetch_status"], failure_reason=result["failure_reason"],
                title=result["title"], raw_html=result.get("raw_html", "")[:500000],
                clean_text=result["clean_text"][:200000],
                clean_text_hash=hashlib.sha256((result["clean_text"] or "").encode()).hexdigest()[:16],
                fetch_time=result["fetch_time"],
            )
            db.add(doc)
            if result["fetch_status"] == "SUCCESS":
                created += 1
            else:
                failed += 1
        db.commit()
    return {"unique_urls": len(unique_urls), "created": created, "failed": failed}


def acquire_brand_asset(db: Session, url: str) -> dict:
    """Acquire a single brand asset URL."""
    existing = db.query(SourceDocument).filter(SourceDocument.url == url).first()
    if existing:
        return {"status": "EXISTS", "doc_id": existing.id}
    result = fetch_page(url)
    identity = url_identity_fields(url, result.get("canonical_url", url))
    doc = SourceDocument(
        url=identity["canonical_url"] or url, original_url=url, **identity,
        domain=urlparse(url).netloc.lower(), source_type="BRAND_ASSET",
        fetch_status=result["fetch_status"], failure_reason=result["failure_reason"],
        title=result["title"], raw_html=result["raw_html"][:500000],
        clean_text=result["clean_text"][:200000],
        clean_text_hash=hashlib.sha256(result["clean_text"].encode()).hexdigest()[:16],
        fetch_time=result["fetch_time"],
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"status": result["fetch_status"], "doc_id": doc.id, "title": result["title"]}


# ---------------------------------------------------------------------------
# P0.3 Answer Atomic Unit — rule-based Chinese sentence splitting
# ---------------------------------------------------------------------------

_CN_SENT = re.compile(r"[。！？?!\n]+")
_LIST_LINE = re.compile(r"^\s*[（(]?[0-9一二三四五六七八九十]+[)）.、．]\s*")
_CITATION_ANCHOR = re.compile(r"\[(\d+)\]")


def extract_answer_claims(db: Session, run_ids: list[int]) -> dict:
    """Rule-based answer claim extraction for all given runs.

    Splits on Chinese punctuation, lists, and citation anchors.
    """
    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(run_ids)).all()
    total = 0
    for run in runs:
        # Clear existing claims for this run
        db.query(AnswerClaim).filter(AnswerClaim.run_id == run.id).delete()
        text = run.answer_text or ""
        if not text.strip():
            continue
        # Split into sentences
        raw_parts = _CN_SENT.split(text)
        claims = []
        for part in raw_parts:
            part = part.strip()
            if not part or len(part) < 4:
                continue
            # Further split on list markers
            sub_parts = _LIST_LINE.split(part) if _LIST_LINE.match(part) else [part]
            for sp in sub_parts:
                sp = sp.strip()
                if not sp or len(sp) < 3:
                    continue
                claims.append(sp)

        # Detect citation anchors and classify claim type
        for i, claim_text in enumerate(claims):
            anchors = _CITATION_ANCHOR.findall(claim_text)
            anchor_ids = [int(a) for a in anchors if a.isdigit()]
            citation_anchor = min(anchor_ids) if anchor_ids else None

            # Rule-based claim type classification
            ctype = ""
            for need_name, patterns in _NEED_PATTERNS.items():
                if any(re.search(p, claim_text) for p in patterns):
                    ctype = need_name
                    break

            claim = AnswerClaim(
                run_id=run.id, claim_index=i + 1, raw_text=claim_text[:2000],
                claim_type=ctype,
                citation_anchor=citation_anchor,
                citation_ids_json=dumps(anchor_ids),
                answer_position=i + 1,
                epistemic_status="FACT", provenance="RULE_DERIVED",
            )
            db.add(claim)
            total += 1
    db.commit()
    return {"runs_processed": len(runs), "claims_extracted": total}


# ---------------------------------------------------------------------------
# P0.4 Passage Segmentation
# ---------------------------------------------------------------------------

_BLOCK_HEADING = re.compile(r"^[#]+ (.+)$", re.MULTILINE)


def segment_document(doc: SourceDocument) -> list[dict]:
    """Segment clean_text into ContentBlocks."""
    text = doc.clean_text or ""
    blocks = []
    pos = 0
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        char_start = text.find(para, pos) if pos < len(text) else pos
        char_end = char_start + len(para)
        pos = char_end

        # Determine block type
        if _BLOCK_HEADING.match(para) or (len(para) < 80 and para.endswith(("：", ":", "】", "]"))):
            btype = "HEADING"
        elif re.match(r"^\s*[0-9]+[.、）)]", para) or re.match(r"^\s*[（(][0-9]+[)）]", para):
            btype = "LIST"
        else:
            btype = "PARAGRAPH"

        blocks.append({
            "block_index": len(blocks) + 1,
            "block_type": btype,
            "text": para[:3000],
            "char_start": char_start,
            "char_end": char_end,
        })
    return blocks


def segment_all_documents(db: Session, doc_ids: list[int] | None = None) -> dict:
    """Segment fetched source documents.

    ``doc_ids`` keeps current-chain reruns scoped to the active Prompt/Run
    lineage. Omitting it preserves the legacy maintenance behavior.
    """
    query = db.query(SourceDocument).filter(SourceDocument.fetch_status.in_(["SUCCESS", "PARTIAL"]))
    if doc_ids is not None:
        query = query.filter(SourceDocument.id.in_([int(item) for item in doc_ids]))
    docs = query.all()
    count = 0
    for doc in docs:
        blocks = segment_document(doc)
        doc.content_blocks_json = dumps(blocks)
        count += 1
    db.commit()
    return {"documents_segmented": count}


# ---------------------------------------------------------------------------
# P0.5 Alignment Engine — exact + near-duplicate
# ---------------------------------------------------------------------------

def _normalize_for_match(text: str) -> str:
    """Normalize text for deterministic matching."""
    t = text.lower().strip()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[《》「」『』\"\"'']", "", t)
    t = re.sub(r"[，。！？、；：""'']", "", t)
    return t


def _jaccard_similarity(a: str, b: str) -> float:
    """Character-level Jaccard similarity."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def align_claims_to_passages(db: Session, run_ids: list[int]) -> dict:
    """Align answer claims to source document passages.

    L1 EXACT_OVERLAP: 15+ consecutive character match
    L2 NEAR_DUPLICATE: Jaccard similarity >= 0.70 after normalization
    L3 UNRESOLVED: no match found
    """
    claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(run_ids)).all()
    docs = db.query(SourceDocument).filter(SourceDocument.fetch_status.in_(["SUCCESS", "PARTIAL"])).all()
    refs = {ref.id: ref for ref in db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()}
    refs_by_run: dict[int, list[ReferenceSource]] = defaultdict(list)
    for ref in refs.values():
        refs_by_run[ref.run_id].append(ref)

    # Clear existing alignments
    db.query(PassageAlignment).filter(PassageAlignment.run_id.in_(run_ids)).delete()

    aligned = 0
    for claim in claims:
        claim_text = claim.raw_text
        anchor_ids = loads(claim.citation_ids_json, [])
        matched = False
        candidate_ref_ids = anchor_ids or [ref.id for ref in refs_by_run.get(claim.run_id, [])]

        for ref_id in candidate_ref_ids:
            ref = refs.get(ref_id)
            if not ref:
                continue
            ref_url = ref.canonical_url or ref.url
            # Find matching source document
            doc = next((d for d in docs if d.url == ref_url or d.canonical_url == ref_url), None)
            if not doc:
                continue
            blocks = loads(doc.content_blocks_json, [])
            if not blocks:
                continue

            norm_claim = _normalize_for_match(claim_text)
            if len(norm_claim) < 10:
                continue

            # L1: exact substring overlap (15+ chars)
            for blk in blocks:
                blk_text = blk.get("text", "")
                if len(blk_text) < 15:
                    continue
                # Check consecutive 15-char substring
                for i in range(0, len(claim_text) - 14):
                    fragment = claim_text[i:i + 15]
                    if fragment in blk_text:
                        al = PassageAlignment(
                            answer_claim_id=claim.id, run_id=claim.run_id,
                            citation_id=ref.id, source_document_id=doc.id,
                            passage_index=blk.get("block_index"),
                            alignment_level="L1_EXACT_OVERLAP",
                            alignment_method="exact_substring_15chars",
                            score=1.0,
                            evidence=f"Exact match: '{fragment}' found in passage",
                            epistemic_status="FACT", provenance="RULE_DERIVED",
                            review_status="PENDING",
                        )
                        db.add(al)
                        aligned += 1
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break

            # L2: near-duplicate (Jaccard >= 0.70)
            if not matched:
                best_score = 0.0
                best_blk = None
                for blk in blocks:
                    norm_blk = _normalize_for_match(blk.get("text", ""))
                    if len(norm_blk) < 20:
                        continue
                    score = _jaccard_similarity(norm_claim, norm_blk)
                    if score > best_score:
                        best_score = score
                        best_blk = blk
                if best_score >= 0.70 and best_blk:
                    al = PassageAlignment(
                        answer_claim_id=claim.id, run_id=claim.run_id,
                        citation_id=ref.id, source_document_id=doc.id,
                        passage_index=best_blk.get("block_index"),
                        alignment_level="L2_NEAR_DUPLICATE",
                        alignment_method=f"jaccard_similarity_{best_score:.2f}",
                        score=round(best_score, 3),
                        evidence=f"Jaccard similarity {best_score:.2f}",
                        epistemic_status="FACT", provenance="RULE_DERIVED",
                        review_status="PENDING",
                    )
                    db.add(al)
                    aligned += 1
                    matched = True

        # L3: UNRESOLVED — no match found
        if not matched:
            al = PassageAlignment(
                answer_claim_id=claim.id, run_id=claim.run_id,
                citation_id=claim.citation_anchor or (candidate_ref_ids[0] if candidate_ref_ids else None),
                alignment_level="L5_UNRESOLVED",
                alignment_method="no_match",
                score=0.0,
                evidence="No passage match found for this claim",
                epistemic_status="INFERENCE", provenance="RULE_DERIVED",
                review_status="PENDING",
            )
            db.add(al)

    db.commit()
    return {"claims_processed": len(claims), "alignments_created": aligned}


# ---------------------------------------------------------------------------
# P0.7 Answer Need Map
# ---------------------------------------------------------------------------

_NEED_PATTERNS = {
    "操作步骤": ["步骤", "打开", "点击", "选择", "复制", "输入", "生成", "设置", "创建", "发布", "分享", "跳转", "进入", "填写"],
    "问题解释": ["是什么", "指的是", "即", "定义", "含义", "概念", "原理", "流程"],
    "平台限制": ["限制", "不能", "禁止", "不允许", "规则", "规范", "审核", "拦截", "违规", "封号", "屏蔽"],
    "工具推荐": ["工具", "平台", "软件", "应用", "推荐", "方案", "使用.*工具", "通过.*生成", "借助"],
    "方案比较": ["对比", "比较", "区别", "哪个好", "优缺点", "选择"],
    "定义": ["什么是", "定义", "即", "泛指"],
    "注意事项": ["注意", "避免", "建议", "提醒", "警惕", "风险"],
    "数据引用": ["商加加", "爱短链", "短链", "二维码", "卡片"],
}


def generate_answer_need_map(db: Session, run_ids: list[int]) -> dict:
    """Generate Answer Need Map — what information does AI repeatedly answer?"""
    claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(run_ids)).all()
    run_count = len(set(c.run_id for c in claims))

    needs = defaultdict(lambda: {"claim_count": 0, "run_ids": set(), "sample_claims": []})

    for claim in claims:
        text = claim.raw_text
        for need_name, patterns in _NEED_PATTERNS.items():
            if any(re.search(p, text) for p in patterns):
                needs[need_name]["claim_count"] += 1
                needs[need_name]["run_ids"].add(claim.run_id)
                if len(needs[need_name]["sample_claims"]) < 3:
                    needs[need_name]["sample_claims"].append(text[:120])

    result = []
    for name, data in sorted(needs.items(), key=lambda x: -x[1]["claim_count"]):
        result.append({
            "need_name": name,
            "claim_count": data["claim_count"],
            "run_count": len(data["run_ids"]),
            "coverage": f"{len(data['run_ids'])}/{run_count}",
            "sample_claims": data["sample_claims"],
        })
    return {"answer_need_map": result, "total_claims": len(claims), "total_runs": run_count}


# ---------------------------------------------------------------------------
# P0.8 Brand Information Gap
# ---------------------------------------------------------------------------

def analyze_brand_information_gap(
    db: Session,
    brand_url: str,
    answer_need_map: list[dict],
    run_ids: list[int],
) -> dict:
    """Compare AI answer needs vs brand asset content to identify gaps."""
    doc = db.query(SourceDocument).filter(SourceDocument.url == brand_url).first()
    if not doc or not doc.clean_text:
        return {"status": "BRAND_CONTENT_UNAVAILABLE", "gaps": []}

    brand_text = doc.clean_text
    gaps = []
    for need in answer_need_map:
        need_name = need["need_name"]
        patterns = _NEED_PATTERNS.get(need_name, [])
        # Check if brand content covers this need
        brand_match = any(re.search(p, brand_text) for p in patterns)
        ai_frequency = need["claim_count"]
        if not brand_match and ai_frequency >= 3:
            gaps.append({
                "need_name": need_name,
                "ai_claim_count": ai_frequency,
                "ai_run_coverage": need["coverage"],
                "brand_has_content": False,
                "severity": "HIGH" if ai_frequency >= 8 else "MEDIUM",
            })

    return {
        "brand_url": brand_url,
        "brand_title": doc.title,
        "total_gaps": len(gaps),
        "gaps": sorted(gaps, key=lambda g: -g["ai_claim_count"]),
        "note": "Brand content comparison is rule-based pattern matching (V0). Not a definitive content audit.",
    }


# ---------------------------------------------------------------------------
# Main Golden Case Pipeline
# ---------------------------------------------------------------------------

def run_golden_case_pipeline(db: Session, run_ids: list[int], brand_url: str) -> dict:
    """Execute the full Golden Case pipeline for runs 173-184."""
    results = {}

    # Step 1: Acquire cited sources
    results["acquisition"] = acquire_cited_sources(db, run_ids)

    # Step 2: Acquire brand asset
    results["brand_asset"] = acquire_brand_asset(db, brand_url)

    # Step 3: Extract answer claims
    results["claims"] = extract_answer_claims(db, run_ids)

    # Step 4: Segment documents
    results["segmentation"] = segment_all_documents(db)

    # Step 5: Align claims to passages
    results["alignment"] = align_claims_to_passages(db, run_ids)

    # Step 6: Answer Need Map
    need_map = generate_answer_need_map(db, run_ids)
    results["need_map"] = need_map

    # Step 7: Brand Information Gap
    results["brand_gap"] = analyze_brand_information_gap(
        db, brand_url, need_map["answer_need_map"], run_ids,
    )

    # Summary
    results["summary"] = {
        "runs_processed": len(run_ids),
        "sources_acquired": results.get("acquisition", {}).get("created", 0),
        "sources_failed": results.get("acquisition", {}).get("failed", 0),
        "claims_extracted": results.get("claims", {}).get("claims_extracted", 0),
        "alignments_created": results.get("alignment", {}).get("alignments_created", 0),
        "brand_gaps_found": results.get("brand_gap", {}).get("total_gaps", 0),
        "passage_analysis_eligibility": "CITATION_ONLY",
        "eligibility_note": "Candidate-citation URL overlap is ~3% — cannot construct reliable RETRIEVED_NOT_CITED. Downgrading to CITED vs BRAND_ASSET comparison.",
    }

    return results
