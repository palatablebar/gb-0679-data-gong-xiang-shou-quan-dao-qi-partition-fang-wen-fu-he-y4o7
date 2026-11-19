# 授权定义

资源orders与订单等价，customers与客户等价。principal为主体文本，不支持模糊主体；启用主体归属时principal先解析成工号主键，原始值保留在principal_original。partition为YYYY-MM；分区授权[start,end)不含end月。授权时间也为[start,end)，到期时刻立即失效。

每条授权包含主体、资源、生效窗、分区窗和allow/deny。全部条件必须同时匹配。拒绝优先，多个允许不能覆盖任何显式拒绝；无匹配默认拒绝。匹配规则ID按字典序稳定排序，冲突显示全部允许与拒绝证据。

observed为真实访问执行结果allowed或blocked；reported为上游0/1判定，留作证据。expected为实际授权复算，分区模块重建reported为执行结果便于二值对账。越权放行和误拦截分别计数，禁止用相互抵消的总数代替逐条核查。

业务ID和超大整数按文本保形；Decimal参与数量金额计算，对外序列化为字符串。哨兵集合定义在app/values.py，缺失值不能当零。所有时间带UTC偏移，先转UTC比较，业务日按指定地区划分。区间统一[start,end)。重复业务键保留第一条、完全相同行计重复；值冲突行隔离且保留原值。空文件、全空白、仅表头分开拒绝。

运行清单包括输入sha256、规则版本、参数、生成时刻与耗时。源行编号以CSV解析器的物理结束行号表示，引号内换行不增加记录数。输入超过4MB返回413，非法表头和类型返回422，失效版本复核返回409。
## 主体目录

`identities` 每项字段：`employee_no`（工号，唯一主键，必填）、`name`（姓名）、`cost_center`（成本中心）、`historical_nos`（历史工号）、`accounts`/`identifiers`（共享访问数据与授权规则里的其它标识）。姓名为空或成本中心为空即凭据不完整，对应行隔离且批次不能归档。

- 同一工号出现多条：仅当姓名与成本中心完全一致时合并，否则标记冲突。
- 不同工号共用同一标识：仅当双方姓名与成本中心完全一致时合并到字典序最小的工号，否则该标识不归属。
- 姓名本身不是标识：命中多个主体（`IDENTITY_AMBIGUOUS`）或仅一个（`IDENTITY_NAME_ONLY`）都不归属，必须由目录提供唯一标识。

输出行新增：`principal`（主键）、`principal_original`（原始标识）、`identity_status`、`identity_evidence`、`identity_name`、`identity_cost_center`、`identity_source`。
