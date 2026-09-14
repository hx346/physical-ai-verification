# ADR-0005：对象存储选用 SeaweedFS（S3 协议），以 ObjectStore SPI 屏蔽差异

- 状态：Accepted（2026-09-14 用户决策："MinIO 不用了用 seafs"；同日二次确认 "seafs" = **SeaweedFS**）
- 背景：平台需要存放 URDF/CAD、仿真日志、数据集、报告等大对象。原方案（ADR-0002 中表述）为 MinIO。

## 命名歧义（已消解）

初判 "seafs" 为 Seafile 并先行实现了 WebDAV 适配器（保留，见下）；用户确认为 **SeaweedFS**（S3 协议）。
SPI 预留的"仅换适配器"分支生效，业务与数据布局零改动。

## 备选方案

| 方案 | 结论 |
|---|---|
| MinIO（S3 API） | 程序化访问生态最好，但用户明确弃用 |
| **SeaweedFS（S3 网关）** | **采纳**：用户决策；S3 协议兼容（可随时切回 S3 系任何实现）；Go 单二进制、镜像小（~40MB）、单进程可跑全栈（master+volume+filer+S3），扩容可拆 |
| Seafile（WebDAV/SeafDAV） | 备选实现已完成并单测通过（`SeafileWebDavObjectStore`），保留不删；compose 栈已移除 |
| PG 大对象 / 本地磁盘 | 大文件与版本管理不适合入库；本地磁盘仅作开发实现 |

## 决策

- **ObjectStore SPI**（`backend/.../storage/ObjectStore.java`）：`put/get/exists/delete`，
  key 规范 `/{bucket}/{domain}/{id}/{filename}`（如 `/sim-logs/run-xxx/run.log`）。
- **主实现 `SeaweedS3ObjectStore`**（type=`seaweed-s3`）：JDK HttpClient + 自研 SigV4
  （`S3Signer`，零 AWS SDK 依赖；**以 AWS 官方测试向量为黄金标准验证通过**）。
  桶懒创建（幂等）、DELETE 幂等（S3 语义）、`..` key 拒绝。
- 部署：`deploy/docker-compose.yml` 单容器 `weed server -s3`（demo/单机形态，扩容时拆多容器）；
  凭据 `deploy/seaweedfs/s3.json`（demo 密钥 roboverify/roboverify-secret）。
- 切换：`ROBOVERIFY_STORAGE_TYPE=seaweed-s3` + `ROBOVERIFY_S3_*`（见 `deploy/.env.example`），
  E2E 验证脚本 `deploy/demo/verify-seaweedfs.sh`（python stdlib 独立 SigV4 与 Java 实现交叉验证）。
- `LocalFsObjectStore`（type=local）为开发/测试默认。

## 后果

- 正面：S3 协议是事实标准——未来回 MinIO/R2/OSS 只改 endpoint；镜像小下载快；
  SeaweedFS 单二进制运维成本低；无 SDK 依赖（Boot 4.1 生态兼容风险为零）。
- 负面：自研 SigV4 需自行维护（仅覆盖本 SPI 的简单请求：无 multipart/listing/presigned；
  大文件分片上传需求出现时再评估引入官方 SDK）；SeaweedFS 社区版无多租户细粒度 IAM。
- Evidence IR 的 `artifacts[].store` 枚举值应使用 `seaweedfs`（s3 系）。
