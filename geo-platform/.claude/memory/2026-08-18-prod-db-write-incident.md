# 事故记录：2026-08-18 生产库被测试请求破坏

## 事故
调试 `PATCH /api/projects/3` 时，直接用 curl 向**生产数据库**发送了带 `competitors` 的写请求。后端 `update_project` 是"先删除全部竞品再重建"语义，测试 payload 只带 1 个竞品，导致项目 3 原有的 3 个竞品被覆盖删除。用户发现后已从 `recommendation_entities` 历史记录恢复名称+别名，但 URL 永久丢失（更早已被 `:` 切分 bug 截断）。

## 为什么发生
1. 我在生产库上直接测试破坏性写接口，没有先备份。
2. 后端"先删后建"缺少 fail-closed 校验。
3. 前端竞品解析用 `split(":")` 把 `https://` 截断（已修复）。

## 已修复
- 后端 `update_project`：删除前先完整校验 payload，空名称/非法项 fail-closed，绝不先删后验（tests/test_v0_project_update.py 4 个测试锁死）。
- 前端：竞品行解析 URL 部分重新拼接。
- 新增 `scripts/backup_db.py` 备份脚本。

## 规则（永久）
**任何对生产库 geo_v0.db 的破坏性操作（写/删/改测试、数据清理、migration）之前，必须先跑 `python3 scripts/backup_db.py`。调试 API 一律用测试库或先备份。**
