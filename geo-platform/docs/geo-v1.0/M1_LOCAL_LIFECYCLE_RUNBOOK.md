# GEO M1.1 本机生命周期与迁移手册

## 1. 变更分类与范围

本切片分类为 `IMPLEMENTATION_CHANGE`。它只补齐代码发布、SQLite/WAL
一致性备份、隔离恢复、升级和回滚操作，不改变 GEO 业务语义、数据准入、
Evidence、Truth 或交付等级。

本轮未访问外部平台，文心采样、网页抓取和模型调用均为 0；也未在公司电脑
安装任何内容。

## 2. 版本与拓扑指纹（2026-10-29）

| 对象 | 指纹 | 关系/事实 |
|---|---|---|
| 旧本机基线 | `50a4a57` | `e7b09e6` 的祖先，两者之间 25 个提交 |
| 容量审计候选 | `e7b09e6` | `ed23679` 的直接父提交 |
| 当前控制候选 | `ed23679` | 只比 `e7b09e6` 增加 4 个控制/状态文档 |
| 旧仓库内 runtime 副本 | `/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta`：`50a4a57` | plist 中模型调用为 0；不是当前 Application Support 安装 |
| Application Support 安装 | `/Users/bmwqr/Library/Application Support/GEO Beta`：`068d379` | 两个配置开关文件均为 1；本切片未修改 |

`50a4a57..e7b09e6` 不是一个可忽略的小补丁：实际包含 95 个文件、5622 行
新增和 957 行删除，覆盖 MANUAL_IMPORT、采样重试、时间范围、Evidence Pack
容量审计、前后端体验及本机控制器。升级前必须把完整候选作为一个不可变
release 验收，不能只复制最后一个提交。

这里存在两个不同安装根，不能混称为“当前版本”。只读检查发现 Application
Support 安装的 `daily-model-calls` 与 `scheduled-sampling-enabled` 文件均为
`1`；仓库内旧 runtime 的 VERSION 则是 `50a4a57`，launchd plist 中模型开关
为 `0`。本切片没有判断哪一个当前占用 8032，也没有
擅自改写活动配置；新 install、restore、upgrade、rollback 会统一强制写入
`0`，之后必须再走独立业务授权。

## 3. 目标目录

```text
GEO_BETA_HOME/
  current -> releases/<release-id>
  releases/<release-id>/       # 不可变的准备完成 release
  data/geo-beta.db             # 唯一活动 SQLite
  evidence/                    # 冻结证据文件
  config/                      # 非密钥运行开关
  backups/                     # pre-upgrade/rollback 留档
  logs/ run/
```

长期运行目录不得是 `/private/tmp`。准备完成的 release 必须含：

- `scripts/local_beta.sh`；
- `geo-platform/backend/.venv/bin/python`；
- `geo-platform/frontend/dist/index.html`。

安装工具不会联网补依赖；缺少任一项立即阻断。

prepared release 还必须在原机器生成 `PREPARED_RELEASE_FINGERPRINT.json`：

```bash
python3 geo-platform/backend/scripts/m1_beta_ops.py fingerprint \
  --source PREPARED_SOURCE --source-sha EXACT_GIT_SHA \
  --schema-revision 20261022_01 --write
```

指纹同时包含所有获准交付文件的相对路径、大小、权限和 SHA-256；安装会在复制前后
重新计算并逐项比对。生成指纹后修改、增加或删除任何交付文件都会 fail-closed。
根目录运行数据、应用目录 `geo-platform/backend/runtime`、`.env`、访问凭证和浏览器
登录态明确排除；排除规则按明确相对路径执行，不会误删 `.venv` 或其他依赖包内部
名为 `data` 的合法目录。

install/upgrade 会核对 OS、CPU 架构和 Python major/minor。当前 bundle 复制
`.venv`，因此只承诺同 OS/架构使用；不是跨 macOS/Linux 或跨架构可移植包。
Node 版本被记录为前端构建指纹，但已构建的运行时不依赖目标机 Node。
install/upgrade 还要求命令里的 SHA/revision 与 prepared fingerprint 完全一致，
不能在安装时临时改口径。

## 4. 唯一操作入口

从仓库根目录执行：

```bash
./scripts/m1_beta_ops.sh install HOME PREPARED_SOURCE RELEASE_ID SOURCE_SHA SCHEMA_REVISION
./scripts/m1_beta_ops.sh start HOME
./scripts/m1_beta_ops.sh status HOME
./scripts/m1_beta_ops.sh stop HOME
./scripts/m1_beta_ops.sh backup HOME NEW_BACKUP_DIR
./scripts/m1_beta_ops.sh restore BACKUP_DIR NEW_EMPTY_HOME
./scripts/m1_beta_ops.sh upgrade HOME PREPARED_SOURCE RELEASE_ID SOURCE_SHA SCHEMA_REVISION
./scripts/m1_beta_ops.sh rollback HOME BACKUP_DIR PREVIOUS_RELEASE_ID
```

`upgrade` 与 `rollback` 完成后服务保持停止，操作员检查报告后显式执行
`start`。这避免升级脚本自行恢复队列并产生外部调用。

旧 controller 若没有“等待 backend/worker 真实退出”的能力，普通 backup 会
fail-closed，不接受它生成 stopped marker。首次升级使用 prepared candidate
中的新 controller 停止旧服务；不能用手写 marker 绕过。

## 5. 安全 Gate

### SQLite/WAL

- 禁止 `cp`/`install` 活动 `.db` 文件。
- 统一使用 SQLite online backup API，能纳入已提交 WAL frame。
- 备份和恢复均执行 `integrity_check`、`foreign_key_check` 与 SHA-256 校验。
- 完整备份要求 `run/services-stopped` 标记；控制器只有在 backend/worker
  都停止后才创建该标记。

### 队列隔离

部署 preflight 会检查 Worker 消费的所有队列表。任何 `QUEUED`、`RUNNING`、
`retrying`、`EVIDENCE_QUEUED`、`AUTO_FETCH_QUEUED` 或
`RESERVED_IN_FLIGHT` 都阻断备份/升级/回滚/启动。关闭 UI 开关不能替代这个
检查，因为历史任务本身可能已带有外部授权。

### Evidence 路径

备份逐条读取 `single_prompt_prepared_source_snapshots`，同时校验数据库
`artifact_hash`、文件 hash 和 `clean_text` hash。恢复不会沿用旧 Mac 的绝对
路径，而是把文件写入新 home 的 `evidence/prepared-sources-restored/`，更新
恢复副本中的 path，并再次核对 hash 和一对一绑定。

### 密钥与授权

备份只记录非密钥开关用于审计，不复制 `.env`、浏览器登录 profile 或访问
凭证。内部模型账本通过 SQLite Online Backup 归档到 `audit-ledgers/`，包括
`DELIVERY_UNKNOWN` 等历史状态；恢复时只放入 `backups/audit-ledgers/` 作为只读
审计材料，不恢复为活动授权账本。恢复后 `daily-model-calls=0`、
`scheduled-sampling-enabled=0`；旧实验账本不能自动成为新机器的日常授权。

## 6. 升级与回滚顺序

升级固定顺序：

1. 停 backend 与 worker，建立 stopped marker；
2. 数据库完整性与活动队列 preflight；
3. SQLite online backup + Evidence/hash 清单；
4. 以候选 release 恢复到隔离临时 home；
5. 在隔离 DB 上执行候选 Alembic 和 schema validation；
6. 隔离成功后才迁移已停止的活动 DB；
7. 原子切换 `current`，强制关闭外部能力；
8. 服务保持停止，人工审查 `UPGRADE_REPORT.json` 后启动。

回滚固定使用明确的 backup 与已安装 release ID，并校验 stopped marker、备份版本、
数据库 revision 和 release manifest 一致。旧活动 data/evidence 不会
删除，而是移动到 `backups/pre-rollback-live-*`；恢复 DB 的证据绝对路径会
重定位到最终 home 后再做完整性检查。

macOS launchd 标签为单实例共享标签。控制器在停止、重启或查看已加载服务前，
必须核对 launchd 中的数据库 URL 和工作目录属于当前 `GEO_BETA_HOME`；若标签属于
另一安装目录则拒绝操作，不能误停其他 Beta 实例或为错误 HOME 写 stopped marker。

## 7. 公司电脑 D1 前置（尚未执行）

部署前必须记录目标机 OS/架构、Python/Node 运行时、磁盘、备份位置、常开
策略、浏览器能力、用户与目录权限。当前 release 控制器固定监听
`127.0.0.1`，适合本机使用。

不能为了局域网访问削弱 `release_access`：非 loopback 请求必须是 HTTPS，
并且需要 `GEO_RELEASE_ACCESS_CONFIG` 的明确账号/项目权限。若未来允许员工
访问，应使用受控 HTTPS 反向代理，并单独设计/验收可信代理头、证书、
防火墙和访问配置。未经目标网络授权与真实验收，本候选 **不是 LAN-ready**。

## 8. 当前阻塞

1. 当前工作树没有 backend `.venv`，不能直接作为 prepared release；需要从
   同一候选生成离线可安装包并保留 SHA/revision。
2. 源码候选与活动本机安装不一致，必须先在隔离副本完成完整回归。
3. 公司电脑事实、网络授权、HTTPS 反向代理及服务账号尚未提供。
4. 本轮没有、也不得把现有开启状态或历史实验余额解释为新机器外部调用授权。
