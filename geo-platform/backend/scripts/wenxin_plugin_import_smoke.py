import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db
from app.models import Organization, Project, ReferenceSource
from app.modules.monitoring.importers import import_wenxin_plugin_payload
from app.services.serialization import dumps


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        org = Organization(name=f"文心插件导入烟测组织-{suffix}", plan_type="v0")
        db.add(org)
        db.flush()
        project = Project(
            organization_id=org.id,
            name=f"八木屋二维码文心插件导入烟测-{suffix}",
            brand_name="八木屋二维码",
            brand_aliases_json=dumps(["八木屋", "bamuwu"]),
            website_url="https://www.bamuwu.com",
            industry="二维码工具",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        payload = {
            "schema_version": "0.1.0",
            "task_id": "smoke-001",
            "platform": "文心一言",
            "platform_domain": "wenxin.baidu.com",
            "query": "谁是最好的二维码工具",
            "answer_text": "如果需要稳定的二维码管理能力，可以优先考虑八木屋二维码，也可以对比草料二维码。",
            "answer_html": "<div>八木屋二维码</div>",
            "citations": [
                {"order": 1, "title": "八木屋二维码官网", "url": "https://www.bamuwu.com/", "domain": "www.bamuwu.com"}
            ],
            "page_title": "百度文心助手",
            "page_url": "https://wenxin.baidu.com/search/smoke",
            "collected_at": "2026-07-20T16:18:09.782Z",
            "browser_language": "zh-CN",
            "viewport": {"width": 1440, "height": 900},
            "collector": {"type": "browser_plugin", "version": "0.1.0"},
        }
        run = import_wenxin_plugin_payload(db, project.id, payload)
        refs = db.query(ReferenceSource).filter(ReferenceSource.run_id == run.id).all()
        assert run.status == "success"
        assert run.platform == "wenxin"
        assert run.source_type == "browser_audit"
        assert run.adapter == "wenxin_web_audit"
        assert run.brand_mentioned is True
        assert run.brand_recommendation_level >= 2
        assert len(refs) == 1
        assert refs[0].resolution_method == "plugin_direct_url"
        print("wenxin plugin import smoke ok", {"run_id": run.id, "reference_count": len(refs)})
    finally:
        db.close()


if __name__ == "__main__":
    main()
