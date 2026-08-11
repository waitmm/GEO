"""Citation Primary Content Extraction V1.

Pipeline:
  1. Page Type Classification → ARTICLE|VIDEO|QA|FORUM|OTHER
  2. Type-specific Region Locator → candidate DOM region
  3. Dense Block Merge → merged text blocks
  4. Multi Extractor → Trafilatura + Readability-like + DOM Heuristic
  5. Candidate Overlap + Scoring → best candidate selection
  6. Boundary Repair → trim nav/recommendation tails
  7. Sanity Gate → reject challenge/login/nav-only pages
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from html import unescape as _html_unescape
from json import loads as _json_loads
from typing import Any


# ---------------------------------------------------------------------------
# P0-1: Page Type Classification
# ---------------------------------------------------------------------------

CONTENT_TYPE_LABELS = {"ARTICLE": "文章", "VIDEO": "视频", "QA": "问答", "FORUM": "论坛", "OTHER": "其他"}


def classify_page_type(html: str, url: str = "") -> str:
    """Classify page into ARTICLE|VIDEO|QA|FORUM|OTHER."""
    domain = _extract_domain(url)
    signals = []

    # --- Structured Data ---
    ld_json = _extract_ld_json(html)
    if ld_json:
        ld_type = _ld_type(ld_json)
        if ld_type:
            signals.append(("ld_json", ld_type, 3))

    # --- OpenGraph ---
    og_type = _og_type(html)
    if og_type:
        signals.append(("og", og_type, 2))

    # --- URL signals ---
    if any(k in url.lower() for k in ["/video/", "/v/", "bilibili.com/video", "douyin.com/video"]):
        signals.append(("url", "VIDEO", 2))
    if any(k in url.lower() for k in ["/question/", "/q/", "zhihu.com/question"]):
        signals.append(("url", "QA", 2))
    if any(k in url.lower() for k in ["bbs.", "forum", "thread", "/t/", "molelink.cn"]):
        signals.append(("url", "FORUM", 1))

    # --- DOM signals ---
    dom_signals = _dom_type_signals(html)
    for ds, weight in dom_signals:
        signals.append(("dom", ds, weight))

    # --- Aggregate ---
    scores = Counter()
    for source, stype, weight in signals:
        scores[stype] += weight

    if scores:
        best = scores.most_common(1)[0]
        if best[1] >= 3:
            return best[0]
    return "ARTICLE"  # default


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0].split("?")[0]


def _extract_ld_json(html: str) -> list[dict]:
    results = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        try:
            data = _json_loads(m.group(1))
            if isinstance(data, dict):
                results.append(data)
            elif isinstance(data, list):
                results.extend(data)
        except Exception:
            pass
    return results


_LD_TYPE_MAP = {
    "Article": "ARTICLE", "NewsArticle": "ARTICLE", "BlogPosting": "ARTICLE",
    "VideoObject": "VIDEO", "QAPage": "QA", "Question": "QA",
    "DiscussionForumPosting": "FORUM",
}


def _ld_type(ld_items: list[dict]) -> str | None:
    for item in ld_items:
        t = item.get("@type", "")
        if isinstance(t, list):
            for tt in t:
                if tt in _LD_TYPE_MAP:
                    return _LD_TYPE_MAP[tt]
        elif t in _LD_TYPE_MAP:
            return _LD_TYPE_MAP[t]
    return None


def _og_type(html: str) -> str | None:
    m = re.search(r'<meta[^>]+property="og:type"[^>]+content="([^"]+)"', html, re.IGNORECASE)
    if m:
        og = m.group(1).lower()
        if "video" in og:
            return "VIDEO"
        if "article" in og:
            return "ARTICLE"
    return None


def _dom_type_signals(html: str) -> list[tuple[str, int]]:
    signals = []
    # Video indicators
    video_cues = ["video-info", "video-title", "video-desc", "player-container", "bilibili-player"]
    if any(c in html.lower() for c in video_cues):
        signals.append(("VIDEO", 2))
    # QA indicators
    if "question" in html.lower() and html.lower().count("answer") >= 2:
        signals.append(("QA", 2))
    # Forum: repeated post structure
    if html.lower().count('class="post"') >= 3 or html.lower().count('class="reply"') >= 3:
        signals.append(("FORUM", 2))
    # Article default
    if any(t in html.lower() for t in ["<article", "<main", 'class="article', 'class="post-content', 'class="entry-content']):
        signals.append(("ARTICLE", 2))
    if re.search(r"<p[ >].{50,}</p>", html):
        signals.append(("ARTICLE", 1))
    return signals


# ---------------------------------------------------------------------------
# P0-2: Type-specific Region Locator
# ---------------------------------------------------------------------------

_MAIN_PATTERNS = [
    re.compile(r'<(article|main)[^>]*>(.*?)</\1>', re.DOTALL | re.IGNORECASE),
    re.compile(r'<div[^>]*(?:id|class)\s*=\s*["\'](?:article|content|post|entry|detail|main|正文)[^"\']*["\'][^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE),
]

_VIDEO_REGION_PATTERNS = [
    re.compile(r'<(?:div|section)[^>]*(?:class|id)\s*=\s*["\'][^"\']*(?:video-info|video-desc|video-intro|desc-info)[^"\']*["\'][^>]*>(.*?)</(?:div|section)>', re.DOTALL | re.IGNORECASE),
]

_QA_PATTERNS = [
    re.compile(r'<(?:div|section)[^>]*(?:class|id)\s*=\s*["\'][^"\']*(?:question|answer-list|answers)[^"\']*["\'][^>]*>(.*?)</(?:div|section)>', re.DOTALL | re.IGNORECASE),
]


def locate_region(html: str, content_type: str) -> str:
    """Return the HTML of the most likely primary content region."""
    patterns = list(_MAIN_PATTERNS)
    if content_type == "VIDEO":
        patterns = _VIDEO_REGION_PATTERNS + patterns
    elif content_type == "QA":
        patterns = _QA_PATTERNS + patterns

    candidates = []
    for pat in patterns:
        for m in pat.finditer(html):
            inner = m.group(2) if pat is _MAIN_PATTERNS[0] else m.group(1)
            text_len = len(_strip_html(inner))
            if text_len > 100:
                candidates.append((text_len, inner))

    if candidates:
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]
    return html  # fallback to full HTML


# ---------------------------------------------------------------------------
# P0-3: Dense Block Merge
# ---------------------------------------------------------------------------

_BLOCK_TAGS = re.compile(r"<(p|div|section|li|td|h[1-6]|blockquote|pre|article)[ >]", re.IGNORECASE)
_NAV_CLASS = re.compile(r"(nav|menu|sidebar|footer|header|comment|recommend|related|share|login|ad|banner|toolbar)", re.IGNORECASE)
_INLINE_TAGS = re.compile(r"</?(a|span|strong|em|b|i|code|img|br|wbr)[^>]*>", re.IGNORECASE)


def _strip_html(html: str) -> str:
    s = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html_unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def build_dense_blocks(region_html: str) -> list[dict]:
    """Build merged dense text blocks from region HTML."""
    # Split region into block-level elements
    parts = re.split(r"(<(?:p|div|section|li|h[1-6]|blockquote)[^>]*>)", region_html, flags=re.IGNORECASE)
    blocks = []
    current = ""
    current_class = ""

    for part in parts:
        tag_match = re.match(r"<(p|div|section|li|h[1-6]|blockquote)[^>]*>", part, re.IGNORECASE)
        if tag_match:
            if current.strip():
                blocks.append(_block_info(current, current_class))
            current = ""
            current_class = part
            continue

        closing = re.match(r"</(p|div|section|li|h[1-6]|blockquote)>", part, re.IGNORECASE)
        if closing:
            if current.strip():
                blocks.append(_block_info(current, current_class))
            current = ""
            current_class = ""
            continue

        current += part

    if current.strip():
        blocks.append(_block_info(current, current_class))

    # Merge adjacent text blocks
    merged = []
    for blk in blocks:
        if merged and not _is_noise_block(blk) and not _is_noise_separator(merged[-1]):
            # Merge if both are content blocks
            gap = abs(blk["char_end"] - merged[-1]["char_end"]) if merged else 0
            if gap < 500 and blk["link_density"] < 0.5:
                merged[-1]["text"] += "\n" + blk["text"]
                merged[-1]["text_length"] += blk["text_length"]
                merged[-1]["char_end"] = blk["char_end"]
                continue
        merged.append(blk)

    return merged


def _is_noise_block(blk: dict) -> bool:
    if blk["link_density"] > 0.7 and blk["text_length"] < 200:
        return True
    if _NAV_CLASS.search(blk.get("class_attr", "")):
        return True
    return False


def _is_noise_separator(blk: dict) -> bool:
    if blk["text_length"] < 30 and blk["short_line_ratio"] > 0.8:
        return True
    return False


def _block_info(html_fragment: str, class_attr: str) -> dict:
    text = _strip_html(html_fragment)
    links = re.findall(r"<a[^>]*>(.*?)</a>", html_fragment, re.DOTALL | re.IGNORECASE)
    link_text = _strip_html(" ".join(links))
    link_len = len(link_text)
    total_len = max(len(text), 1)
    sentences = [s for s in re.split(r"[。！？!?]+", text) if s.strip()]
    lines = [l for l in text.split("\n") if l.strip()]
    short = sum(1 for l in lines if len(l) < 20)

    return {
        "text": text,
        "text_length": len(text),
        "link_text_length": link_len,
        "link_density": link_len / total_len,
        "sentence_count": len(sentences),
        "punctuation_count": len(re.findall(r"[，。！？、；：""'']", text)),
        "short_line_ratio": short / max(len(lines), 1),
        "class_attr": class_attr,
        "char_end": 0,
    }


# ---------------------------------------------------------------------------
# P0-4: Multi Extractor — simple Readability-like + DOM Heuristic
# ---------------------------------------------------------------------------

def extract_readability_like(html: str) -> dict:
    """Simple Readability-like extractor based on text density."""
    blocks = build_dense_blocks(html)
    if not blocks:
        return {"text": "", "length": 0, "score": 0}

    # Score each block
    for blk in blocks:
        score = 0
        if blk["text_length"] > 100:
            score += 2
        if blk["text_length"] > 500:
            score += 3
        if blk["sentence_count"] >= 3:
            score += 2
        if blk["link_density"] < 0.3:
            score += 2
        if blk["link_density"] < 0.1:
            score += 1
        if blk["punctuation_count"] > 5:
            score += 1
        if blk["short_line_ratio"] < 0.3:
            score += 2
        # Penalize nav/recommendation
        if _NAV_CLASS.search(blk.get("class_attr", "")):
            score -= 3
        if blk["link_density"] > 0.6 and blk["text_length"] < 300:
            score -= 2
        blk["score"] = max(0, score)

    # Select blocks with score >= 4, merge, cap at 50K chars
    selected = [b["text"] for b in blocks if b.get("score", 0) >= 4]
    text = "\n\n".join(selected)[:50000]
    return {
        "text": text,
        "length": len(text),
        "score": sum(b.get("score", 0) for b in blocks),
        "block_count": len(selected),
    }


def extract_dom_heuristic(html: str, content_type: str = "ARTICLE") -> dict:
    """DOM-based heuristic extraction using paragraph and heading detection."""
    region = locate_region(html, content_type)
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", region, re.DOTALL | re.IGNORECASE)
    headings = re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", region, re.DOTALL | re.IGNORECASE)

    clean_paras = [_strip_html(p).strip() for p in paragraphs if len(_strip_html(p).strip()) > 20]
    clean_headings = [_strip_html(h).strip() for h in headings if len(_strip_html(h).strip()) > 5]

    text = ""
    for h in clean_headings[:10]:
        text += h + "\n"
    for p in clean_paras[:100]:
        text += p + "\n\n"

    return {
        "text": text.strip()[:50000],
        "length": len(text.strip()[:50000]),
        "paragraph_count": len(clean_paras),
        "heading_count": len(clean_headings),
    }


def extract_from_html(html: str, url: str = "", content_type: str | None = None) -> dict:
    """Main entry point: extract primary content from HTML.

    Returns the full extraction result dict.
    """
    if content_type is None:
        content_type = classify_page_type(html, url)

    region = locate_region(html, content_type)

    # Generate candidates
    candidates = []
    # DOM Heuristic (always)
    dom = extract_dom_heuristic(html, content_type)
    if dom["length"] > 50:
        candidates.append({"extractor": "dom_heuristic", **dom})

    # Readability-like
    rl = extract_readability_like(region)
    if rl["length"] > 50:
        candidates.append({"extractor": "readability_like", **rl})

    # Trafilatura (if available)
    try:
        from trafilatura import extract as traf_extract
        traf_text = traf_extract(html, include_comments=False, include_tables=False) or ""
        if len(traf_text) > 50:
            candidates.append({"extractor": "trafilatura", "text": traf_text, "length": len(traf_text)})
    except ImportError:
        pass

    # Dense Block candidate
    dense_blocks = build_dense_blocks(region)
    dense_text = "\n\n".join(b["text"] for b in dense_blocks if b["text_length"] > 50 and b["link_density"] < 0.6)
    if len(dense_text) > 50:
        candidates.append({"extractor": "dense_blocks", "text": dense_text, "length": len(dense_text)})

    if not candidates:
        return _empty_result(content_type, "EMPTY", "LOW")

    # --- P0-5: Candidate Overlap ---
    if len(candidates) >= 2:
        for i, ca in enumerate(candidates):
            for j, cb in enumerate(candidates):
                if j <= i:
                    continue
                overlap = _text_overlap(ca["text"], cb["text"])
                ca.setdefault("overlaps", {})[cb["extractor"]] = overlap
                cb.setdefault("overlaps", {})[ca["extractor"]] = overlap

    # --- P0-6: Candidate Scoring ---
    scored = _score_candidates(candidates, content_type, html)
    best = scored[0]

    # --- P0-7: Conflict check ---
    confidence = "HIGH"
    if len(scored) >= 2:
        gap = scored[0]["_score"] - scored[1]["_score"]
        if gap < 2:
            confidence = "MEDIUM"
        if scored[0]["_score"] < 3:
            confidence = "LOW"
    if len(candidates) == 1:
        confidence = "MEDIUM"

    # --- P0-8: Boundary Repair ---
    text = best["text"]
    boundary_repaired = False
    repaired_text = _repair_boundary(text)
    if repaired_text != text:
        boundary_repaired = True
        text = repaired_text

    # --- P0-9: Sanity Gate ---
    status = "FULL"
    if _has_challenge(html):
        status = "SUSPECT"
        text = ""
    elif len(text) < 100 and content_type not in ("VIDEO",):
        status = "PARTIAL" if len(text) > 30 else "EMPTY"
    elif content_type == "VIDEO" and len(text) < 300:
        status = "DESCRIPTION_ONLY"

    return {
        "content_type": content_type,
        "primary_content": text[:50000],
        "primary_content_length": len(text),
        "extraction_status": status,
        "extraction_confidence": confidence,
        "selected_extractor": best["extractor"],
        "candidate_count": len(candidates),
        "boundary_repaired": boundary_repaired,
    }


def _empty_result(content_type: str, status: str, confidence: str) -> dict:
    return {
        "content_type": content_type,
        "primary_content": "",
        "primary_content_length": 0,
        "extraction_status": status,
        "extraction_confidence": confidence,
        "selected_extractor": "none",
        "candidate_count": 0,
        "boundary_repaired": False,
    }


# ---------------------------------------------------------------------------
# P0-5: Text Overlap
# ---------------------------------------------------------------------------

def _text_overlap(a: str, b: str) -> float:
    """Compute 3-gram overlap between two texts."""
    if not a or not b:
        return 0.0

    def ngrams(s, n=3):
        s = re.sub(r"\s+", "", s)
        return {s[i:i + n] for i in range(0, len(s) - n + 1)}

    ng_a = ngrams(a)
    ng_b = ngrams(b)
    if not ng_a or not ng_b:
        return 0.0
    return len(ng_a & ng_b) / min(len(ng_a), len(ng_b))


# ---------------------------------------------------------------------------
# P0-6: Candidate Scoring
# ---------------------------------------------------------------------------

def _score_candidates(candidates: list[dict], content_type: str, html: str) -> list[dict]:
    for c in candidates:
        score = 0
        t = c["text"]
        length = c["length"]

        # Text density
        if length > 500:
            score += 3
        elif length > 200:
            score += 2

        # Sentence completeness
        sentences = len(re.findall(r"[。！？!?]+", t))
        if sentences >= 5:
            score += 2
        if sentences >= 10:
            score += 1

        # Punctuation density
        punct = len(re.findall(r"[，。！？、；：""'']", t))
        punct_ratio = punct / max(length, 1)
        if punct_ratio > 0.02:
            score += 2

        # Low short-line ratio
        lines = [l for l in t.split("\n") if l.strip()]
        short = sum(1 for l in lines if len(l) < 20)
        short_ratio = short / max(len(lines), 1)
        if short_ratio < 0.3 and len(lines) > 5:
            score += 2

        # Extractor agreement
        overlaps = c.get("overlaps", {})
        if overlaps:
            avg_overlap = sum(overlaps.values()) / len(overlaps)
            if avg_overlap > 0.6:
                score += 3
            elif avg_overlap > 0.3:
                score += 1

        # Link density (from blocks)
        ld = c.get("link_density", 0)
        if ld < 0.2:
            score += 1
        if ld > 0.5:
            score -= 1

        # Proximity to heading
        if c.get("heading_count", 0) > 0:
            score += 1

        # Type-specific
        if content_type == "VIDEO" and length < 500:
            score += 1  # short descriptions are expected for video

        c["_score"] = max(0, score)
    candidates.sort(key=lambda x: -x["_score"])
    return candidates


# ---------------------------------------------------------------------------
# P0-8: Boundary Repair
# ---------------------------------------------------------------------------

_TAIL_NOISE = re.compile(
    r"(\n\s*)?(相关阅读|相关推荐|猜你喜欢|下一篇|上一篇|热门推荐|全部评论|评论\s*\d+|更多内容|推荐阅读|为你推荐|热门文章|编辑于|发布于|声明：|免责声明|举报|反馈).*$",
    re.DOTALL | re.IGNORECASE,
)

_HEAD_NOISE = re.compile(
    r"^\s*(首页|栏目|登录|注册|当前位置|breadcrumb|导航|搜索).*?\n",
    re.IGNORECASE,
)


def _repair_boundary(text: str) -> str:
    """Trim tail recommendations and head navigation."""
    # Tail repair
    m = _TAIL_NOISE.search(text)
    if m:
        tail_pos = m.start()
        # Check if the tail really looks like noise
        after_tail = text[tail_pos:]
        lines_after = [l for l in after_tail.split("\n") if l.strip()]
        if lines_after:
            short_count = sum(1 for l in lines_after if len(l) < 40)
            if short_count / len(lines_after) > 0.5:
                text = text[:tail_pos].strip()

    # Head repair
    m = _HEAD_NOISE.match(text)
    if m:
        text = text[m.end():].strip()

    return text


# ---------------------------------------------------------------------------
# P0-9: Sanity Gate
# ---------------------------------------------------------------------------

_CHALLENGE_PATTERNS = [
    "验证码", "安全验证", "请点击", "访问异常", "登录后查看", "请完成验证",
    "请输入验证码", "人机验证", "滑块验证", "行为验证",
    "captcha", "verify", "please verify", "are you a robot",
]


def _has_challenge(html: str) -> bool:
    lower = html.lower()[:5000]
    for pat in _CHALLENGE_PATTERNS:
        if pat.lower() in lower:
            return True
    return False


# ---------------------------------------------------------------------------
# P0-10: Batch processing for SourceDocuments
# ---------------------------------------------------------------------------

def process_all_source_documents(db) -> dict:
    """Run primary content extraction on all SUCCESS/PARTIAL source documents."""
    from app.models import SourceDocument
    from app.modules.optimization.passage_service import segment_document

    docs = db.query(SourceDocument).filter(
        SourceDocument.fetch_status.in_(["SUCCESS", "PARTIAL"]),
        SourceDocument.raw_html.isnot(None),
        SourceDocument.raw_html != "",
    ).all()

    results = {"processed": 0, "full": 0, "partial": 0, "empty": 0, "suspect": 0}
    for doc in docs:
        if doc.clean_text and "抖音跳转" not in (doc.raw_html or "")[:200]:
            # Skip if already has good content
            pass
        result = extract_from_html(doc.raw_html or "", doc.url or "")
        doc.clean_text = result["primary_content"] or doc.clean_text
        results["processed"] += 1
        results[result["extraction_status"].lower()] = results.get(result["extraction_status"].lower(), 0) + 1

        # Re-segment
        from app.modules.optimization.passage_service import segment_document as sd
        blocks = sd(doc) if hasattr(doc, "clean_text") else []
        doc.content_blocks_json = _json_dumps(blocks)
    db.commit()
    return results


def _json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
