from __future__ import annotations

import random
import time
from typing import Any, Optional

from app.adapters.base import AdapterResult, BaseAIAdapter, Citation


class MockAdapter(BaseAIAdapter):
    platform_key = "mock"
    entry_type = "system_mock"

    async def run_query(
        self,
        prompt: str,
        model: Optional[str] = None,
        web_search_enabled: bool = True,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AdapterResult:
        started = time.perf_counter()
        metadata = metadata or {}
        brand = metadata.get("brand_name", "DemoBrand")
        competitors = metadata.get("competitors", ["CompetitorA", "CompetitorB"])
        competitor = random.choice(competitors) if competitors else "CompetitorA"
        include_brand = random.random() > 0.25
        include_competitor = random.random() > 0.15

        recommended = []
        if include_brand:
            recommended.append(brand)
        if include_competitor:
            recommended.append(competitor)
        if not recommended:
            recommended.append("a neutral vendor")

        answer = (
            f"For the question '{prompt}', the mock AI answer recommends "
            f"{', '.join(recommended)}. "
            f"{brand} is mentioned as a good fit when official docs, FAQ pages, "
            "case studies, and third-party reviews provide clear evidence."
        )
        citations = [
            Citation(
                title=f"{brand} official site",
                url=metadata.get("website_url") or f"https://www.{brand.lower()}.com",
                snippet="Official product and FAQ information.",
                source_name=f"{brand} official",
            ),
            Citation(
                title="Industry comparison article",
                url=f"https://example.com/reviews/{competitor.lower()}-vs-{brand.lower()}",
                snippet="A third-party comparison source used for mock evidence.",
                source_name="Example Reviews",
            ),
        ]

        latency_ms = int((time.perf_counter() - started) * 1000) + random.randint(80, 220)
        return AdapterResult(
            platform=self.platform_key,
            entry_type=self.entry_type,
            model=model or "mock-model",
            model_version="v0",
            web_search_enabled=web_search_enabled,
            prompt=prompt,
            answer_text=answer,
            citations=citations,
            raw_response={"mock": True, "recommended": recommended},
            status="success",
            latency_ms=latency_ms,
            token_usage={"prompt_tokens": len(prompt), "completion_tokens": len(answer)},
            cost_estimate=0,
        )
