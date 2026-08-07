import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.modules.monitoring.collectors.wenxin.reference_parser import (
    parse_malformed_link_pair,
    parse_standard_link_pair,
    resolve_reference_url,
    title_similarity,
)
from app.modules.monitoring.collectors.wenxin.collector import WenxinWebCollector
from app.modules.monitoring.collectors.wenxin.url_normalizer import (
    canonicalize_url,
    extract_first_url,
    is_static_resource,
    normalize_serialized_text,
)


def main() -> None:
    assert normalize_serialized_text("&quot;https%3A%2F%2Fexample.com%2Fa%3Fx%3D1&quot;") == '"https://example.com/a?x=1"'
    assert normalize_serialized_text(r"{\u0022linkUrl\u0022:\u0022https://example.com\u0022}")
    assert canonicalize_url("https://www.example.com/a?utm_source=x&b=1") == "https://example.com/a?b=1"
    assert is_static_resource("https://t7.baidu.com/logo.png")
    assert not is_static_resource("https://example.com/article")
    assert extract_first_url("logInfo tail https%3A%2F%2Fexample.com%2Farticle%3Futm_medium%3Dx") == "https://example.com/article?utm_medium=x"

    standard = parse_standard_link_pair('{"linkUrl":"https://example.com/a","linkTitle":"八木屋二维码介绍"}')
    assert standard and standard["url"] == "https://example.com/a"

    malformed = parse_malformed_link_pair('linkUrl=https%3A%2F%2Fexample.com%2Fb,linkTitle=%E5%85%AB%E6%9C%A8%E5%B1%8B')
    assert malformed and malformed["title"] == "八木屋"

    assert title_similarity("八木屋二维码工具介绍", "八木屋二维码工具") > 0.72

    resolved = resolve_reference_url(
        {"reference_index": 1, "display_title": "八木屋二维码工具介绍", "outer_html": ""},
        [{"title": "八木屋二维码工具", "url": "https://www.bamuwu.com/article?utm_source=test"}],
    )
    assert resolved["resolution_method"] == "retrieval-candidate-title-match"
    assert resolved["domain"] == "bamuwu.com"

    direct = resolve_reference_url(
        {"reference_index": 2, "display_title": "直接链接", "href": "https://example.com/direct"},
        [],
    )
    assert direct["resolution_method"] == "dom-direct-url"

    encoded_parent = resolve_reference_url(
        {
            "reference_index": 3,
            "display_title": "八木屋二维码工具",
            "outer_html": "<span>八木屋二维码工具</span>",
            "ancestor_outer_html": [
                '<div data-log="{&quot;linkUrl&quot;:&quot;https%3A%2F%2Fbamuwu.com%2Ftool%3Futm_source%3Dbaidu&quot;,&quot;linkTitle&quot;:&quot;%E5%85%AB%E6%9C%A8%E5%B1%8B%E4%BA%8C%E7%BB%B4%E7%A0%81%E5%B7%A5%E5%85%B7&quot;}"></div>'
            ],
        },
        [],
    )
    assert encoded_parent["canonical_url"] == "https://bamuwu.com/tool"
    assert encoded_parent["resolution_method"].startswith("serialized-same-reference")

    wenxin_long_press = resolve_reference_url(
        {
            "reference_index": 4,
            "display_title": "草料无法生成APP下载类二维码",
            "outer_html": '<li data-long-press-ext-info="{&quot;link&quot;:&quot;https://cli.im/app&quot;,&quot;linkTitle&quot;:&quot;草料无法生成APP下载类二维码&quot;}"></li>',
        },
        [],
    )
    assert wenxin_long_press["canonical_url"] == "https://cli.im/app"
    assert canonicalize_url("https://cli.im/app%E3%80%82%E7%9B%AE%E5%89%8D") == "https://cli.im/app"
    collector = WenxinWebCollector()
    first_window = [{"reference_index": index, "display_title": f"引用{index}", "serialized": "{}"} for index in range(1, 32)]
    second_window = [{"reference_index": index, "display_title": f"引用{index}", "serialized": "{}"} for index in range(2, 33)]
    merged = collector._merge_reference_items([first_window, second_window], 32)
    assert len(merged) == 32
    assert [item["reference_index"] for item in merged] == list(range(1, 33))
    html_items = collector._reference_items_from_html(
        '<ol data-show-ext="{&quot;total_num&quot;:2}">'
        '<li data-long-press-ext-info="{&quot;link&quot;:&quot;https://example.com/a&quot;,&quot;linkTitle&quot;:&quot;引用标题一&quot;}">'
        '<span class="_index_x">1.</span><span class="_text_x">引用标题一</span></li>'
        '<li data-long-press-ext-info="{&quot;link&quot;:&quot;https://example.com/b&quot;,&quot;linkTitle&quot;:&quot;引用标题二&quot;}">'
        '<span class="_index_x">2.</span><span class="_text_x">引用标题二</span></li>'
        '</ol>',
        2,
    )
    assert len(html_items) == 2
    assert html_items[0]["reference_index"] == 1
    assert html_items[1]["href"] == "https://example.com/b"
    print("reference parser smoke ok")


if __name__ == "__main__":
    main()
