# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 主体归属

- `POST /api/runs` 的 `parameters` 可带 `identities`（主体目录列表）和 `identity_policy`；缺省使用仓内目录与严格策略。显式传空列表或 `identity_enabled=false` 关闭归属（关闭后禁止归档）。
- 每个阶段响应和 `GET /api/runs/<id>` 都带 `identity`：`policy`、`decision`（裁决结论与理由）、`conclusions`（每批唯一主键结论）、`unresolved`（未归属原始标识）、`conflicts`（目录冲突）、`original_identifiers`、`metrics`。
- `GET /api/runs/<id>/identities` 返回同一份结论及历次策略切换留下的版本。
- `POST /api/runs/<id>/identity`，正文 `{"version":1,"policy":"historical_no_first"}`：在同批次内切换策略。成功则版本 +1 且旧版归档，返回 `changed`、`previous_version`、`run`；版本过期返回 409，未知策略返回 422，切换会遗漏或改写原始标识时返回 409 且不写入任何变更。
- 归档：`ready=false`（主体凭据不完整、存在未归属/冲突主体，或授权主体无法唯一归属）时，`/api/runs/<id>/archive` 返回 409，不生成证据文件。
- 重跑：批次摘要包含主体目录指纹与策略，相同输入重跑复用批次，不新增结论。
