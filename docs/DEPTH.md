# 深度登记 数据共享授权到期与分区访问复核

规模：中型。使用者：企业数据共享审计专员。核心规则：拒绝规则优先于允许，授权必须同时命中资源、分区和生效窗；显式拒绝不得被宽授权覆盖。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 访问采信 | 查看并运行访问采信 | `/api/accesses` | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py` |
| M2 资源映射 | 查看并运行资源映射 | `/api/resources` | `app/modules/m2_resources/rules.py` | `tests/test_m2.py` |
| M3 授权定版 | 查看并运行授权定版 | `/api/grants` | `app/modules/m3_grants/rules.py` | `tests/test_m3.py` |
| M4 冲突裁决 | 查看并运行冲突裁决 | `/api/conflicts` | `app/modules/m4_conflicts/rules.py` | `tests/test_m4.py` |
| M5 分区判定 | 查看并运行分区判定 | `/api/partitions` | `app/modules/m5_partitions/rules.py` | `tests/test_m5.py` |
| M6 访问对账 | 查看并运行访问对账 | `/api/audit` | `app/modules/m6_audit/rules.py` | `tests/test_m6.py` |
| M7 审计归档 | 查看并运行审计归档 | `/api/seals` | `app/modules/m7_seals/rules.py` | `tests/test_m7.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码 | 默认解码失败 | 回退GB18030 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_legacy_encoding_real_sample` |
| TRAP-02 | BOM | 首列名多字符 | utf-8-sig | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_bom_real_sample` |
| TRAP-03 | 带引号换行 | 拆成两条 | csv逻辑行 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_quoted_newline_is_one_record` |
| TRAP-05 | 列数不匹配 | 静默错列 | 隔离原行 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_bad_columns_real_sample` |
| TRAP-08 | 前导零ID | 编码变形 | 全程字符串 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_identifier_preserved_real_sample` |
| TRAP-14 | 重复键冲突 | 后写覆盖 | 保留首条并隔离冲突行 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_duplicate_conflict_real_sample` |
| TRAP-18 | 空态三态 | 一律成功 | 分别错误码 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_three_empty_states` |
| TRAP-26 | 旧版本提交 | 覆盖新结果 | 版本条件更新 | `app/store.py` | `tests/test_e2e.py::test_stale_review_409` |
| TRAP-07 | 上游结果空值 | 误报拒绝 | 隔离缺失 | `app/values.py` | `tests/test_m3.py::test_real_missing_decision_not_zero` |
| TRAP-19 | 允许与拒绝重叠 | 后写覆盖 | 拒绝优先且排序证据 | `app/modules/m4_conflicts/rules.py` | `tests/test_m4.py::test_deny_priority_counterexample` |
| TRAP-23 | 授权到期点 | 多放行一次 | 半开生效窗 | `app/modules/m3_grants/rules.py` | `tests/test_m3.py::test_expiry_endpoint_excluded` |
| TRAP-27 | 同一员工多标识 | 精确匹配把受权访问判成拒绝 | 别名/历史工号/账号统一归属到工号主键 | `app/identity.py` | `tests/test_identity.py::test_historical_no_account_and_email_share_one_principal` |
| TRAP-28 | 同名不同成本中心 | 只凭姓名把两人并成一个主体 | 姓名不是唯一标识，仅姓名即隔离 | `app/identity.py` | `tests/test_identity.py::test_same_name_different_cost_center_not_merged` |
| TRAP-29 | 授权规则用旧标识 | 归属后命中不到授权 | 授权主体与访问主体用同一张表解析 | `app/modules/m3_grants/rules.py` | `tests/test_identity.py::test_grant_on_historical_no_matches_employee` |
| TRAP-30 | 共享账号指向两人 | 静默选边 | 冲突隔离且禁止归档 | `app/identity.py` | `tests/test_identity.py::test_shared_account_pointing_to_two_people_conflicts` |
| TRAP-31 | 凭据不完整 | 照样导出证据 | 凭据不全/未归属禁止归档 | `app/archive.py` | `tests/test_identity.py::test_incomplete_credentials_never_archive` |
| TRAP-32 | 切换归属策略 | 覆盖旧结论或丢原始标识 | 同批次换出，版本存档 | `app/store.py` | `tests/test_identity.py::test_switch_to_historical_policy_keeps_old_version` |

## 主体归属

`identity_policy` 默认 `strict_shared_credentials`：只有当两条目录记录的共同凭据（姓名 + 成本中心）完全一致时才合并同一工号的多标识记录。历史工号只是标识之一，命中它可唯一归属，但不得在凭据冲突时替人「选边」。

- 主键：工号。访问行与授权规则的 `principal` 先解析成主键，授权命中、对账、导出与页面均只看主键；原始标识保存在 `principal_original` 和归属结论的 `referenced` 里。
- 不能唯一归属的情况一律隔离：同名多人（`IDENTITY_AMBIGUOUS`）、仅姓名（`IDENTITY_NAME_ONLY`）、未登记（`IDENTITY_UNRESOLVED`）、标识指向多人（`IDENTITY_CONFLICT`）、缺成本中心等（`IDENTITY_INCOMPLETE`）。
- 归档门禁：主体结论 `complete=false` 或授权存在归属异常时，`/api/seals` 标记 `ready=false`，`/api/runs/<id>/archive` 返回 409，不产生证据文件。
- 策略切换：`POST /api/runs/<id>/identity` 在同一批次内切换 `strict_shared_credentials` / `historical_no_first`，成功后版本 +1 并把旧版写入 `run_versions`；任何失败（版本过期、未知策略、结论不覆盖原始标识）都整体回滚，旧结论与原始标识原样保留。相同策略重复提交不改动批次。
- 重跑：批次摘要含主体目录指纹，同输入同策略重跑只复用同一批次，不新增结论。

## 对账规则

输入原始逻辑行=最终采纳来源行+隔离来源行+重复行+空白行+分段表头。派生记录用_sources保存完整来源，因此分组不丢行。业务预期合计与上游申报合计之差等于逐行差异之和。结果按输入摘要、规则版本、参数及主体目录指纹产生唯一批次，事务写入；同源重跑只复用已有批次。

## 已知不覆盖

4MB以上文件需预先按业务键分批；不模拟生产支付与外部回调。人工复核只变更批次状态，不改写原始记录。主体目录随参数传入，不连接 HR 主数据；目录本身不完整时只能阻止归档，不能自动补全。
