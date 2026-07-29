from urllib.parse import urlparse

from app.models import Competitor, Project


def normalize_domain(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.lower().removeprefix("www.")


def find_first_position(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    positions = [lowered.find(term.lower()) for term in terms if term and lowered.find(term.lower()) >= 0]
    return min(positions) if positions else -1


def extract_mentions(
    answer_text: str,
    citation_urls: list[str],
    project: Project,
    competitors: list[Competitor],
) -> dict:
    brand_terms = [project.brand_name]
    try:
        from app.services.serialization import loads

        brand_terms.extend(loads(project.brand_aliases_json, []))
    except Exception:
        pass

    brand_first_position = find_first_position(answer_text, brand_terms)
    brand_mentioned = brand_first_position >= 0
    recommendation_words = ["recommend", "recommended", "good fit", "candidate", "supplier", "solution"]
    brand_recommended = brand_mentioned and any(word in answer_text.lower() for word in recommendation_words)

    competitor_hits = []
    cited_competitor_domains = []
    for competitor in competitors:
        names = [competitor.name]
        position = find_first_position(answer_text, names)
        if position >= 0:
            competitor_hits.append({"name": competitor.name, "first_position": position, "count": answer_text.count(competitor.name)})
        competitor_domain = normalize_domain(competitor.website_url) if competitor.website_url else ""
        if competitor_domain and any(competitor_domain in normalize_domain(url) for url in citation_urls):
            cited_competitor_domains.append(competitor_domain)

    official_domain = normalize_domain(project.website_url) if project.website_url else ""
    cited_official_domain = bool(official_domain) and any(official_domain in normalize_domain(url) for url in citation_urls)

    return {
        "brand_mentioned": brand_mentioned,
        "brand_recommended": brand_recommended,
        "brand_first_position": brand_first_position,
        "competitors": competitor_hits,
        "cited_official_domain": cited_official_domain,
        "cited_competitor_domains": cited_competitor_domains,
        "sentiment": "positive" if brand_recommended else "neutral",
    }
