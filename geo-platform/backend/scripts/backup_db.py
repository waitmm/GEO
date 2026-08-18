"""数据库备份脚本。

用法：python scripts/backup_db.py
在主库同目录生成带时间戳的备份副本（被 .gitignore 排除，不进 Git）。
任何破坏性操作（PATCH/DELETE 测试、数据迁移、清理脚本）前必须先执行本脚本。
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "geo_v0.db"


def main() -> int:
    if not DB_PATH.exists():
        print(f"主库不存在：{DB_PATH}")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = DB_PATH.with_name(f"geo_v0.db.backup-{stamp}")
    shutil.copy2(DB_PATH, backup)
    print(f"已备份：{DB_PATH} -> {backup} ({DB_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
