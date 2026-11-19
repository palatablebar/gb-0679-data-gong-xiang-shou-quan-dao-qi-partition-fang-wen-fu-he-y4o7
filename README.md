# 数据共享授权到期与分区访问复核

供企业数据共享审计专员核对原始记录、处理差异并封存证据。

## 启动

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

打开 http://localhost:18248 。首次进入自动运行仓内脏样例。工具条可重跑、切换样例或上传CSV。SQLite保存在命名卷records中，重建服务保留批次。

## 模块

- 1. 访问采信：`/accesses`，`/api/accesses`。
- 2. 资源映射：`/resources`，`/api/resources`。
- 3. 授权定版：`/grants`，`/api/grants`。
- 4. 冲突裁决：`/conflicts`，`/api/conflicts`。
- 5. 分区判定：`/partitions`，`/api/partitions`。
- 6. 访问对账：`/audit`，`/api/audit`。
- 7. 审计归档：`/seals`，`/api/seals`。

## 核心规则

拒绝规则优先于允许，授权必须同时命中资源、分区和生效窗；显式拒绝不得被宽授权覆盖。

## 主体归属

同一员工在访问数据与授权规则里可能用当前工号、历史工号、账号或邮箱等不同标识出现。每批运行会给出一份唯一的主体归属结论，授权命中、对账差异与导出都以此为准；原始标识始终保留。

裁决采「严格共同凭据合并」：只有姓名与成本中心完全一致时才合并同一工号的多标识记录。历史工号可作为唯一标识命中原主体，但不得在凭据冲突时替人选边——错误合并同名不同成本中心的人无法事后证明选边依据。同名多人、仅凭姓名、共享账号指向多人、缺成本中心的记录一律隔离；批次主体结论不完整（或授权主体无法唯一归属）时禁止归档。

可切换 `historical_no_first` 作对照，但需显式提交；切换成功会新增版本并保留旧版，失败则不改动旧结论与原始标识。相同输入同策略重跑复用同一批次，不新增结论。

## 演示

1. 打开首页，核对当次计算、差异和隔离原因。
2. 切换模块查看源行及裁决依据。
3. 重跑相同样例，批次号与行数保持一致。
4. 复核后导出一份证据CSV。版本已变化的复核提交返回409。

## 输入与输出

输入列见 `docs/DATA-DICTIONARY.md`。项目包含dirty.csv、clean.csv、legacy.csv、identity.csv，统一走实际导入路径。上传限制4MB，拒绝不带时区的时间。业务键按字符串保留，Decimal参与计算，空值不会当零。

`POST /api/runs` 接收sample或csv；`GET /api/runs`返回历史批次；`POST /api/runs/<id>/review`需要version与decision；`GET /api/runs/<id>/archive`返回唯一证据导出（主体结论不完整时409）。`GET /api/runs/<id>/identities`查看每批主体归属结论与历次版本，`POST /api/runs/<id>/identity`切换归属策略。

## 范围

样例均为虚构。单机复核工具不连接生产系统；不提供登录、远端数据库或自动支付。内存计算按4MB输入上限控制，SQLite事务保证结果完整写入。

## 目录

app为服务与规则，sample_data为输入，tests为测试，docs为定义与深度登记。
