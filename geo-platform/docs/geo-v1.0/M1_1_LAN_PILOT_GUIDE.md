# GEO M1.1 局域网试用指南

## 访问入口

- 主地址：`https://BMWQRdeMacBook-Pro.local:8443`
- IP 备用地址：`https://192.168.3.185:8443`
- 适用范围：与部署 Mac 同一 `192.168.3.0/24` 局域网

部署 Mac 必须保持开机、联网且未进入会停止后台进程的深度睡眠。服务不对公网开放，应用后端只监听 `127.0.0.1:8032`。

## 同事首次使用

1. 从部署管理员处取得 `geo-beta-ca.crt`，先核对 SHA-256 指纹：
   `2D:35:4C:A3:F2:0B:28:F6:69:96:43:C7:7D:24:90:2D:A0:4C:50:23:30:35:F9:A7:15:54:5C:2F:CA:D7:67:76`。
2. 将该证书加入操作系统受信任根证书；不要忽略或绕过浏览器证书警告。
3. 向管理员领取自己专用的访问凭证，不要共用或转发。
4. 打开主地址，在“GEO 项目登录”中粘贴访问凭证。
5. 普通爱短链试用账号只允许访问 Project 1；出现 403 时联系管理员核对项目范围。

macOS 可用“钥匙串访问”导入证书，并仅信任已核对指纹的 `GEO M1 Internal Pilot CA`。Windows 可通过“管理用户证书”导入“受信任的根证书颁发机构”。

## 当前运行边界

- Monitor、历史结果、范围冻结、人工导入、导出和反馈可用。
- 本次部署没有发起任何文心、DeepSeek 或网页抓取调用。
- AI 新生成和自动采样当前均由服务端保持关闭；启用需要独立运行授权。
- 现有历史结果仍可查看，不得将历史结果误认为本次新生成。

## 管理员操作

```bash
GEO_HOME="$HOME/Library/Application Support/GEO Beta"

# 状态
GEO_BETA_HOME="$GEO_HOME" "$GEO_HOME/current/scripts/local_beta.sh" status

# 启动 / 停止 / 重启
GEO_BETA_HOME="$GEO_HOME" "$GEO_HOME/current/scripts/local_beta.sh" start
GEO_BETA_HOME="$GEO_HOME" "$GEO_HOME/current/scripts/local_beta.sh" stop
GEO_BETA_HOME="$GEO_HOME" "$GEO_HOME/current/scripts/local_beta.sh" restart
```

重要位置：

- 数据库：`~/Library/Application Support/GEO Beta/data/geo-beta.db`
- 日志：`~/Library/Application Support/GEO Beta/logs/`
- 当前版本：`~/Library/Application Support/GEO Beta/VERSION`
- 邀请凭证（仅管理员可读）：`~/Library/Application Support/GEO Beta/config/invitation-keys.txt`
- 供同事安装的 CA 公钥证书：`~/Library/Application Support/GEO Beta/config/tls/geo-beta-ca.crt`
- 升级前备份：`~/Library/Application Support/GEO Beta/backups/`

不要发送 `geo-beta-ca.key`、`server.key`、`backend.env` 或完整管理员凭证。
