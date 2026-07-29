import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db
from app.modules.monitoring.importers import import_wenxin_plugin_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a Wenxin browser-plugin JSON result into monitoring runs.")
    parser.add_argument("json_path", help="Path to the plugin-exported JSON file.")
    parser.add_argument("--project-id", type=int, required=True, help="Existing project id.")
    parser.add_argument("--prompt-id", type=int, default=None, help="Existing prompt id. If omitted, a prompt is created from payload.query.")
    args = parser.parse_args()

    payload_path = Path(args.json_path)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    init_db()
    db = SessionLocal()
    try:
        run = import_wenxin_plugin_payload(db, args.project_id, payload, args.prompt_id)
        print(
            "wenxin plugin import ok",
            {
                "run_id": run.id,
                "status": run.status,
                "reference_count": run.detected_reference_count,
                "resolved_reference_count": run.resolved_reference_count,
            },
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
