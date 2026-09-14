# ADR-0005：对象存储选用 Seafile（WebDAV），以 ObjectStore SPI 屏蔽差异

- 状态：Accepted（2026-09-14，用户决策："MinIO 不用了用 seafs"）
- 背景：平台需要存放 URDF/CAD、仿真日志、数据集、报告等大对象。原方案（ADR-0002 中表述）为 MinIO。

## 命名假设（显式标注）

`seafs` 理解为 **Seafile**（含 SeafDAV/WebDAV 接口）。若实际指 **SeaweedFS**（S3 协议），
仅替换适配器实现，本 SPI 与数据布局不变。

## 备选方案

| 方案 | 结论 |
|---|---|
| MinIO（S3 API） | 程序化访问生态最好，但用户明确弃用 |
| **Seafile（WebDAV/REST）** | **采纳**：用户既有偏好/设施；自托管文件管理成熟；通过 SeafDAV 提供程序化访问 |
| SeaweedFS（S3） | 备选：若"seafs"实指此项，按 S3 适配器实现 |
| PG 大对象 / 本地磁盘 | 大文件与版本管理不适合入库；本地磁盘仅作开发实现 |

## 决策

- 引入 **ObjectStore SPI**（`backend/.../storage/ObjectStore.java`）：`put/get/exists/delete`，
  key 规范 `/{bucket}/{domain}/{id}/{filename}`（如 `/sim-logs/run-xxx/run.log`）。
- M0 只实现 `LocalFsObjectStore`（开发/测试，零外部依赖）。
- `SeafileWebDavObjectStore` **已于 2026-09-14 提前实现**（原计划 M2）：JDK HttpClient 实现
  MKCOL(递归建父目录)/PUT/HEAD(405 时回退 PROPFIND)/GET/DELETE(幂等)，Basic 认证，
  key 含 `..` 段拒绝（与 LocalFs 同等防护）。单测 7/7 通过（fake WebDAV，不依赖容器）。
  切换方式：`ROBOVERIFY_STORAGE_TYPE=seafile-webdav` + `ROBOVERIFY_SEAFILE_URL` 等（见 application.yml 注释）。
- `deploy/docker-compose.yml` 提供 Seafile 栈（mariadb + memcached + seafile），M0 不依赖其运行。

## 后果

- 正面：复用既有文件设施；SPI 使后续更换/增加存储（含回到 S3 系）只动适配器。
- 负面：WebDAV 无 S3 语义（无批量 API/预签名 URL），上传性能与生态弱于 S3；
  Evidence IR 的 `artifacts[].store` 枚举已用 `seafile` 值，迁移成本可控。
- 待验证：`seafileltd/seafile-mc:11.0-latest` 镜像拉取中（本机 Docker Hub 直连超时，走镜像加速）；
  SeafDAV 启用方式：容器内 `/seafile/conf/seafdav.conf` 置 `enabled = true` 后重启，
  首次 `docker compose up -d seafile` 后做 put/get/exists/delete 容器级 E2E。
  另注：`docker manifest inspect` 走直连，在本机网络下失败不代表镜像不存在，以 `docker pull` 为准。
