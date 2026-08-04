# Wenxin Reference Parser Change Log - 2026-08-03

## Scope

- File changed: `backend/app/modules/monitoring/collectors/wenxin/collector.py`
- Purpose: reduce false `partial_success` results caused by incomplete reference extraction.
- User-facing area: Batch / Sample Runs reference counts and final run status.

## Problem

Several runs were marked `partial_success` even though the parsed references all had URLs.

Examples from existing artifacts:

- Run `#47`: UI declared 32 references, result saved 31 references, but `page.html` contained references `1-32`.
- Run `#51`: UI declared 33 references, result saved 29 references, but `page.html` contained references `1-33`.
- Run `#49`: UI declared 29 references, result saved 26 references, and all 26 saved references had URLs.

The issue was not URL resolution. The DOM extraction selected a broad visible panel and scanned all `[data-long-press-ext-info]` nodes, which could mix note-list/video cards or stale references from earlier prompts in the same browser window.

## Change

- `_reference_dom_items` now first searches concrete reference lists:
  - `ol[class*="_reference_"]`
  - `ol[class*="reference"]`
  - `ol[data-show-ext]`
- Candidate lists are scored against the current `expected_count` by:
  - `data-show-ext.total_num`
  - maximum rendered reference index
  - unique rendered index count
  - DOM order as a tie-breaker
- The selected list is parsed by `li` reference items and sorted by original reference index.
- The old broad panel scan remains as a fallback if no matching reference list is found.
- Reference extraction now tries the in-answer reference list before opening and scrolling the reference panel. This avoids Wenxin virtualizing the panel and dropping middle reference rows during extraction.
- The concrete reference-list path deduplicates only by original reference index, not by title, because Wenxin can return different reference rows with identical titles.

## Rollback

To roll back this change only:

1. Restore `_reference_dom_items` in `backend/app/modules/monitoring/collectors/wenxin/collector.py` to the previous implementation that selected the longest visible panel and scanned `a/button/[data-long-press-ext-info]/div/span/p`.
2. Remove this changelog file if no longer needed.
3. Run:

```bash
cd geo-platform/backend
python3 -m py_compile app/modules/monitoring/collectors/wenxin/collector.py
```

## Verification

- Use existing artifacts with known false partials: `47`, `49`, `51`.
- Also use new false partials after the first parser fix: `55`, `56`, `57`, `58`, `59`, `61`.
- Expected after fix for new runs: `dom_reference_count`, `parsed_reference_count`, and `resolved_url_count` should match `ui_declared_count` when the HTML contains a complete numbered reference list.
