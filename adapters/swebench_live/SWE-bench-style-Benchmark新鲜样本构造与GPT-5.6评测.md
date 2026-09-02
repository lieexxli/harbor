# SWE-bench style Benchmark新鲜样本构造与GPT-5.6评测

> **一句话**：从 GitHub 爬取 2026.04–06 的新鲜 issue-PR 对，经过环境自动构建、
> gold patch 执行验证、LLM 语义质检、多模型交叉验证和轨迹审计，
> 产出 **22 个可复现、隔离运行且保留完整审计材料的评测任务**。
>
> 基于微软 SWE-bench-Live + 开源评测框架 Harbor 二次开发。
> 文中所有数字可在本地仓库 / HF 备份（`lieeli/swe-live-eval-backup-2026-07-03`）/
> Google Drive 备份中指认出处（见文末速查表）。

---

## 0. 全景图

### 六阶段流水线

```
[SWE-bench-Live fork]                          [Harbor fork]
①爬取构造 → ②环境构建 → ③执行验证  →  ④适配+质检 → ⑤交叉验证 → ⑥轨迹审计
 curation     RepoLaunch    validation.py     harbor check   harbor run    harbor analyze
```

### 样本漏斗

```
5548 仓库 → 2789 仓库 → 4670 对 → 2459 对 → 1968 池
                                              │
                                    资源所限抽样 100 试做
                                    （1868 留池，随时扩批）
                                              │
                              97 setup → 62 organize → 47 validated
                                              │
                                     +试点批   → 51 合并
                                              │
                          check / run / analyze 三关剔 29（逐条有台账）
                                              │
                                        ★ 22 最终数据集
```

三个要点：

- **1968 → 100 是抽样，不是淘汰**——环境构建每条样本都烧 LLM 调用和算力，先抽一批试做；
- 真正的质量筛选强度：爬取段 4670 → 1968（约 42% 留存）、构建与质检段 **100+ → 22（约22% 成活率）**；
- 除抽样外，**每一级剔除都有可审计的记录**。

### 分工一览

| 阶段 | 方法论 | 本项目做的 |
|---|---|---|
| ①②③ 爬取 / 环境 / 验证 | 微软 SWE-bench-Live 原作者 | 工程加固 + 流程扩展（两个 fork 40+ 提交） |
| ④⑤⑥ 适配 / 质检 / 审计 | **本项目自己的设计** | adapter、四维 rubric、泄露治理、交叉验证、轨迹审计 |

> **上游解决了"怎么造样本"，本项目补上了"怎么保证样本是好的、分数是干净的"。**

---

## 1. 背景：为什么做这件事

### SWE-bench 是什么

- 普林斯顿 2023 年提出，目前最主流的代码智能体评测基准；
- 每个样本 = 真实 GitHub 仓库的一个 issue + 修复它的 PR；
- 给模型 issue 和 bug 版代码库，让它产出补丁，用 PR 附带的测试判分：
  - **FAIL_TO_PASS（F2P）**：修复前失败、修复后应通过 → 证明 bug 修好了；
  - **PASS_TO_PASS（P2P）**：修复前后都应通过 → 证明没破坏别的；
  - 两组全过才算 **resolved**。

### 问题链条

| 问题 | 解法 | 由谁解决 |
|---|---|---|
| 老样本已进训练数据（**训练污染**） | 持续用最新 issue-PR 构造样本 | SWE-bench-Live |
| 新样本环境没法人工搭 | LLM agent 自动配环境（**RepoLaunch**） | SWE-bench-Live |
| 公开榜单很快又被爬走 | **质量自主可控**的新鲜评测集 | 本项目 |
| agent 运行时能联网查答案（**运行泄露**） | 网络隔离 + 轨迹审计 | 本项目（第 7 节） |

### 本项目的两个目标

1. 建一个可以随时对任意模型做干净跑分的**新鲜评测集**；
2. 把评测数据集构造的**全生命周期**完整走一遍：爬取 → 构造 → 验证 → 质检 → 评测 → 审计 → 治理。

---

## 2. 阶段①：样本爬取与构造（curation）

> **一句话**：样本不是人出的题，是从真实开发活动里挖出来的——
> 用"关联 issue 且改了测试"的 merged PR，天然自带题面和判分依据。

**输入 → 输出**：GitHub Python 仓库 → 1968 条结构化任务池（抽样 100 试做）

### 七步流水线（`curation/run.sh`，每步产物落盘、可断点续跑）

| # | 步骤 | 做什么 | 产出 |
|---|---|---|---|
| 1 | 爬仓库 | Python、star 2000–100000 | **5548** |
| 2 | 过滤仓库 | 按活跃度过滤；剔除非代码仓库、测试框架类仓库 | **2789** |
| 3 | 爬 PR | 时间窗口内的 merged PR，只留**"关联 issue 且改了测试"**的 | — |
| 4 | 组装样本 | 拆出 problem_statement / base_commit / **gold patch** / **test patch** | **4670** |
| 5 | LLM 语义过滤 | judge 四分类（见下） | **2459** |
| 6 | 按 OS 拆分 | Linux / Windows | 2422 + 37 |
| 7 | GPU 过滤 + 抽样 | 剔除 GPU 仓库 → 分层抽样 100 试做 | **1968 → 100** |

### 两个关键设计

- **第 3 步是 SWE-bench 方法论的核心筛选**：关联 issue = 有题面，改了测试 = 有判分依据；
- **第 5 步的 LLM judge 故意宽容**：四分类（①题面太模糊 / ②测试超出题面 / ③题面把解法写出来了 / ④正常），
  prompt 明确要求"拿不准就判④"——样本获取成本高，**这层宁可漏杀**，严格把关留给后面的执行验证和语义质检。

### 抽样策略（本项目设计）

- 难度启发式打分（patch 文件数 / 行数 / hunk 数 / 测试规模）→ easy 25 / medium 40 / hard 35；
- 单仓库上限 3 条，避免被少数大仓库主导。

### 本项目的工程改造（fork 29 提交，让单人单 token 也能跑通）

- 仓库指标查询：Search API（30 次/分）+ 2 次 REST → **一次 GraphQL**；
- `.diff` 下载：匿名（约 60 次/时）→ **认证请求（5000 次/时）**；
- 限流等待：固定休眠 → 读 `X-RateLimit-Reset` **精确等待**，"HTTP 200 但 body 是 RATE_LIMIT"也识别为重试；
- closed-issue 查询加 since 过滤：大仓库 11 分钟 → **约 90 秒**；
- 各环节 checkpoint 增量落盘（断点续跑）、LLM 过滤线程池并发、输出目录时间戳防覆盖；
- 时间窗口（2026.04–06，保证晚于被测模型训练截止）也是本项目按需求加的。

---

## 3. 阶段②：运行环境自动构建（RepoLaunch）

> **一句话**：配环境本身就是一个 agent 任务——这是上游最核心的创新，
> 解决了 SWE-bench 类数据集规模化的最大瓶颈（原版 500 个环境是人工搭的）。

**输入 → 输出**：100 条任务 → 62 个可跑测试的 Docker 镜像 + 判分"四件套"

### 两个 LangGraph 状态机工作流

**setup：把测试跑起来**

```
定位相关文件 → 选基础镜像 → 起 bash 会话 → setup agent 装依赖/排错
                                              ↓
                     commit 成镜像 ← 通过 ← verify agent 独立验证
                                       ↑ 不通过（最多重试 3 轮）
```

**organize：产出标准化判分产物（"四件套"）**

| 产物 | 作用 |
|---|---|
| rebuild_cmds | 改代码后的重建命令 |
| test_cmds | 跑全量测试的命令 |
| **log_parser** | Python 代码：测试输出 → `{测试名: pass/fail/skip}` 结构化字典 |
| 单测命令（可选） | 跑单个测试 |

- **log_parser 是自动判分的基石**：任何一次测试运行都能变成可比对的结构化结果；
- **PyPI time machine**（容易被忽略的精巧设计）：本地代理 PyPI 只供 base_commit
  之前发布的包版本——否则"今天装的依赖"和"当年的代码"不兼容，环境不可复现；
- **输出不只是镜像，是"镜像 + 四件套"**——后续 validation / evaluation / Harbor 判分全部消费这套产物。

### 本项目的工程加固（fork 约 15 提交，批量跑才暴露的问题）

| 类别 | 问题 | 修复 |
|---|---|---|
| LLM 供给 | 单一 API 被 429 打断长任务 | 多 provider 池 + 按样本固定路由 + 限流降级 |
| Docker 并发 | 高并发 commit 触发 containerd lease 竞争 | 串行化 + 重试 |
| agent 稳健性 | LLM 返回不可解析 action 直接崩溃 | 崩溃保护 + 异常返回值容错 |

### 结果与失败归因

- setup **97/100** → organize **62/97**，62 个镜像发布至 Docker Hub；
- 35 个 organize 失败写了归因报告：**主因**是 LLM 协议遵循不足（拿到结果但没按格式提交），
  **次因**是样本自身环境问题（外部 API key、可选依赖、超时）；
- 知道"失败是框架的锅还是样本的锅"，比成功率数字本身更重要。

---

## 4. 阶段③：gold patch 执行验证（validation.py）

> **一句话**：让任何模型答题之前，先用标准答案把判分系统验证一遍——
> 而且 **F2P/P2P 不是声明出来的，是执行推导出来的**。

**输入 → 输出**：62 个环境 → 47 条判分闭环成立的样本

### 两轮执行推导 F2P/P2P

| 轮次 | 打什么补丁 | 跑法 |
|---|---|---|
| **pre 轮** | 只打 test patch（加测试、不修 bug） | 跑一遍，log_parser 解析 |
| **post 轮** | test patch + gold patch，rebuild | **连跑三遍**，有一次 fail 记 fail |

```
FAIL_TO_PASS = pre 未通过、post 通过     ← gold patch 带来的由败转胜
PASS_TO_PASS = 两轮都通过                ← 不应被破坏的回归测试
F2P 为空 → 样本直接丢弃（闭环不成立）
```

- **三遍重复**是为了当场暴露 flaky 测试（时序/随机/网络敏感），不留到评测时污染分数；
- 判分依据是**执行出来的事实**，不是 PR 元数据的声称——跑不起来、解析不出、不稳定都在这步自然淘汰。

### 配套的 evaluation.py = 正式评分语义（Harbor 阶段完整复刻）

```
test patch + 被测模型的 pred patch → rebuild → 跑测试 → 解析
resolved = 所有 F2P 通过 且 没有任何 F2P/P2P 失败   ← 一票否决制
```

### 结果

- **47/62** 通过；失败常见原因：测试环境敏感（时区/网络/随机）、gold patch 依赖测试外改动、log_parser 解析错误；
- 与早期试点批合并：本批 47 剔 3 + 试点批 10 剔 3 留 7 = **51 条候选集**（剔除记录在 provenance.json）。

---

## 5. 阶段④：Harbor 适配与语义质检（本项目自己的设计）

> **一句话**：执行验证只保证"能跑通"，语义质检回答"值不值得当考题"。

**输入 → 输出**：51 条候选集 → Harbor 任务目录 + 四维质检结论

### 为什么选 Harbor

- 先自研轻量 harness（ClaudeCode-for-eval）跑通单样本评测验证可行，再迁到 Harbor；
- Harbor 提供标准任务格式、多 agent 支持（claude-code / cursor / codex / cline…）、并行调度；
- 此前已在 Harbor fork 上练过手：给 check/analyze 加了多 SDK 后端、自建过任务集——工具链是熟的。

### Adapter：parquet 数据行 → 自包含任务目录（约 450 行转换 + 330 行验证器模板）

| 文件 | 内容 |
|---|---|
| instruction.md | issue 原文 + 提交约束（不许动测试）+ **完整性约束**（禁止检索 upstream 答案） |
| task.toml | agent 网络 `allowlist`（只放 7 个模型推理端点，GitHub/搜索引擎全堵）；verifier 公网；难度决定超时/资源 |
| tests/ | config.json 原样携带四件套 + F2P/P2P；run_tests.py 验证器 |

**验证器逐条复刻 evaluation.py**：存 agent 的 `git diff` 为 pred.patch → 硬重置回
base_commit → 依次打 test patch、pred.patch → rebuild → 测试 → log_parser 解析
（失败回退 junit xml / 默认 pytest 解析器）→ 按同一公式判 resolved → 写 reward.txt。
分数与官方评测器语义一致，任务目录完全自包含、可独立分发。

### 四维语义质检 rubric（harbor check，LLM 逐样本判断）

| 维度 | 回答的问题 |
|---|---|
| benchmark_value | 考察的是真实工程能力吗 |
| instruction_self_contained | 只看公开题面和本地仓库，是否足以理解并尝试解决问题 |
| upstream_answer_access_blocked | Agent 可见内容和网络策略是否阻止直接取得 upstream 答案 |
| issue_test_alignment | F2P/P2P 所要求的行为是否与公开 issue 对齐，是否绑定 gold patch 的实现细节 |

`harbor check` 的核心是读取任务目录中的 `instruction.md`、`task.toml`、
`tests/config.json`、`tests/test.patch` 等文件，再按 rubric 做 LLM 语义判断。
它本身不执行测试，也不能观察真实做题 Agent 的行为；可执行性和测试状态转换由
前一阶段的 validation 保证，运行期行为由 `harbor run` 轨迹补充检查。

典型剔除案例：F2P 混入与 issue 无关的测试；隐藏测试要求题面无法推断的第二种行为；
测试绑定 gold patch 特有的 helper、字符串或调用方式；issue 与实际判分要求矛盾。

### rubric 的使用边界

- 当前四维每维只负责一个问题，减少维度重叠和超出静态语义判断能力的要求；
- check 结果是筛查线索，不是样本正确性的自动证明；失败项需要结合测试断言、
  多模型运行结果和轨迹人工复核；
- 生成的 `task.toml` 是构建产物，不直接手改；人工难度统一由 adapter 的覆盖配置应用，
  重新转换时不会丢失标注。

---

## 6. 专题：评测泄露的发现与治理（本项目最有价值的产出）

> **一句话**：新鲜样本只防"背题"，不防"查题"——训练时污染和运行时泄露是两条独立防线。

### 发现（真实案例）

审查一次 Cursor（Claude Sonnet 5）的运行轨迹：agent 没有分析代码，而是
**直接访问 upstream git 历史，找到真实修复 commit，把答案抄了回来**。
分数满分——但测到的是"检索搬运能力"，不是"修 bug 能力"。

### 分析

- 样本越新鲜，upstream 的修复 PR 越"现成"；
- agent 能联网，git fetch / GitHub 页面 / 搜索引擎都是泄露通道；
- 官方和多数第三方 harness **并不严格禁网**——这个问题在行业里真实存在且被低估。

### 治理（三层）

| 层 | 措施 |
|---|---|
| 网络收紧 | agent 解题阶段 allowlist 只留模型推理端点；构建/验证阶段保持联网 |
| 轨迹审计规则 | analyze rubric 写入污染判定三级标准：只碰了本地 shallow checkout（不算，见下注）/ 尝试访问被拦（记录）/ 真实拿到答案（判污染）；要求**读命令输出后再定性** |
| 文档化 | 泄露分析笔记：论证"联网不受控的跑分只有工程参考价值，不构成严格 benchmark 结论" |

注：任务环境里的仓库是 RepoLaunch 用 `git fetch --depth 1 <base_commit>`
准备的——**本地只有 base_commit 这一个 commit，之前和之后的历史都不存在**
（父 commit 不下载，修复 commit 更无处可查）。所以"只碰了本地 shallow
checkout"这一级天然无害；agent 想从 git 历史拿答案就**必须走网络**
（上述泄露案例正是 `git fetch` upstream）——这正是网络 allowlist 能把
git 泄露通道完全堵死的原因。副作用是 agent 也无法用 `git log`/`git blame`
追溯代码演化来辅助定位 bug，任务略难于完整 clone 的设定，但对所有被测
模型一视同仁，不影响公平性。

---

## 7. 阶段⑤+⑥：多模型交叉验证与轨迹审计

> **一句话**：这一步不是给模型排名，是**把模型当探针给数据集做压力测试**。

**输入 → 输出**：51 条任务 → 剔 29 → **22 条最终数据集**

### 交叉验证（harbor run）

- 多种差异化配置批量运行：DeepSeek V4 Flash / DeepSeek V4 Pro / Cursor Auto /
  Cursor Claude Sonnet 5 / Codex GPT-5.5；
- 多模型在同一位置、以同一种与题意无关的方式失败，只作为样本风险信号，
  不能单独证明样本有错；
- 对风险样本继续核对 issue、测试断言、F2P/P2P 明细、补丁和轨迹，确认测试是否
  超出题面、绑定特定实现，或受到环境噪声影响；
- 每次运行的 reward、F2P/P2P 明细、补丁 diff、轨迹摘要都留存为对比报告。

### 轨迹审计（harbor analyze）

- 对可疑运行做 LLM 轨迹级分析，专门编写 analyze prompt + rubric；
- 对重点样本使用不同模型独立分析，再由人工核对原始轨迹，降低单一 judge 偏差；
- 典型发现：**task_specification 不匹配**——验证器要求的行为细节
  （特定日志变量名、消息格式）题面根本没写，agent 不可能凭题面做对。

### 51 → 22 完整剔除台账（29 条，逐条记录在 harbor-check-notes.md）

| 原因类别 | 典型情况 |
|---|---|
| **判分信号与题目脱节**（最多） | F2P 混入无关测试 / 被无关测试主导（一例 30 条 F2P 仅 1 条相关）/ F2P 绑定 gold patch 特有 helper 名——换种正确实现就判负 |
| 环境性失败 | 镜像缺 `uv` verifier 跑不起来；pytest 版本不兼容；同一沙箱 P2P 测试全员必挂 |
| 可观测性问题 | verifier 超时且不产生任何报告文件 |
| 题面缺陷 | issue 说 301 判分要 302；初始仓库是脏的（污染 pred.patch）；修复只是一个标点 |

剔除只发生在能指出具体样本证据时，例如题面与测试矛盾、合理替代实现仍被实现细节测试拒绝、
环境稳定复现失败或判分报告不可用。单纯因为某个模型没有解出，不构成剔除理由。

### 最终产物

- **22 个保留任务**；
- 难度标签：patch 大小启发式 → **人工校准 rubric 标注**（一行修复也可能极难定位）;
- 来源、转换产物、剔除原因和历史运行结果均保留台账，便于复核。

---

## 8. 正式评测实战：GPT-5.6 系列跑分（2026-08-06）

> **一句话**：在同一批 22 个任务上，sol / terra / luna 各做一次全量评测，
> 原始自动测试分数依次为 **16 / 14 / 11**，已经形成清楚的档位区分。

### 评测口径（引用分数时必须带上）

| 项 | 配置 |
|---|---|
| 被测 | OpenAI GPT-5.6 三档：sol（旗舰）/ terra（均衡）/ luna（轻量） |
| agent | Codex CLI（`harbor run -a codex`） |
| 环境 | Modal；每个模型对 22 个任务并发执行 |
| 防泄露 | Codex 关闭 web search；任务级网络 allowlist 只允许模型服务端点 |
| 重复 | 每个模型 **1 次**全量运行（k=1） |
| 规模 | 3 模型 × 22 条 = **66 个 trial** |

三个 job 使用相同的任务集和运行参数，仅模型名不同：

```text
harbor run -p datasets/swebench-live -a codex -m codex/gpt-5.6-<档位> -e modal -n 22 -k 1 --max-retries 1 --env-file .env
```

### 原始结果

| 模型 | 通过 | 自动测试通过率 | 运行异常 | 记录成本 |
|---|---:|---:|---:|---:|
| **sol** | **16 / 22** | **72.7%** | 0 | $17.12 |
| terra | 14 / 22 | 63.6% | 0 | $5.15 |
| luna | 11 / 22 | 50.0% | 1 个 Agent 超时 | $0.79 |

Luna 的 `datamodel-code-generator-3476` 在 Agent 阶段运行满 1800 秒后超时，
Harbor 将该 trial 记为 0 分；因此 Luna 的 11/22 包含这一运行异常。

### 可以得出的结论

1. **本次运行能区分三个档位**：sol 比 terra 多通过 2 题，terra 比 luna 多通过
   3 题，总体顺序为 sol > terra > luna；对这次粗粒度档位比较，一轮已经足够。
2. **这里报告的是自动验证器分数**：通过表示 Agent 补丁满足该任务配置的
   F2P/P2P 判分条件，不等同于对修复质量的无限范围证明。
3. **不从单轮结果推导稳定性结论**：本次没有重复运行，因此不报告方差、翻转率、
   pass@k，也不据此做细粒度模型排名或难度标签有效性证明。
4. **失败结果需要结合轨迹解释**：模型未通过、测试约束过窄、任务范围争议和运行异常
   都可能产生 0 分；reward 是分析起点，不应自动等同于“模型完全没有解决 issue”。

运行期网络策略按任务配置生效，三个 job 的 reward、轨迹、`pred.patch` 和 verifier
产物均已落盘，可用于后续逐题复核；本文不额外声称已经对 66 条轨迹完成逐调用审计。

---

## 9. 方法论沉淀：六条评测认知

1. **评测数据的瓶颈是质量，不是数量。** 进入构建的 100 条最终保留 22 条；
   一条坏样本对结论的伤害远大于少一条好样本。任何自动质检都只能提供证据，
   不能给样本做绝对正确的背书。

2. **判分闭环必须先用 gold patch 验证。** 判分系统没被验证过的评测，分数没有意义。

3. **污染有两条独立防线：训练时新鲜度 + 运行时隔离。** 新鲜只堵"背题"，
   禁网才堵"查题"；样本越新鲜，现成答案越好查——行业普遍低估这一点。

4. **模型可以作为数据质检探针。** 多种差异化配置在同一处同一方式失败时，
   应优先复核题面、测试和环境；只有找到具体证据后，才能把失败归因于样本。

5. **LLM-as-judge 要设计失效边界。** 明确证据要求、多模型交叉印证、
   关键结论人工复核——judge 产出"线索+证据"，裁决权留给人。

6. **可审计性是评测数据集的基础设施。** 来源、剔除原因、镜像生命周期全部有记录；
   别人质疑任何数字时能指到文件，数据集才有公信力。

---

## 10. 反思与后续方向

| 方向 | 现状 → 目标 |
|---|---|
| 样本量 | 22 条足够演示完整流程并做粗粒度三档比较，不够做稳定的细粒度排名 → 提升 organize 62% 成功率、从 1868 池继续扩充 |
| 成本 | organize 35% 失败 = 显著浪费 → 失败归因报告指导下一轮降本 |
| judge 可靠性 | 多模型交叉印证 → 还应抽样人工复核、测 judge-人工一致率 |
| 指标科学 | 当前 GPT-5.6 每档只跑一轮 → 需要稳定性结论时再增加重复、估计方差和 pass@k |

---

## 11. FAQ

**Q：为什么最后只有 22 条？效率是不是太低？**
22 条不是从近 2000 条里全部逐条淘汰出来的——资源所限只抽了 100 条进入构建，
池里还有 1868 条可继续扩批。100 → 22 的损耗来自不同阶段：organize 失败、
gold patch 执行闭环不成立，以及题面、测试或环境证据显示样本不适合二元评测。

**Q：怎么证明这 22 条质量好？**
不能用一次自动检查“证明”样本绝对正确。当前证据包括 gold patch 执行闭环、
四维静态语义质检、多模型运行与重点轨迹复核；所有剔除都有台账，保留样本也允许
在后续运行暴露新问题后继续复核。

**Q：LLM 质检自己会不会出错？**
会。所以 rubric 只提供语义判断和风险线索；剔除需要具体证据，并结合执行结果、
不同模型分析和人工阅读原始文件或轨迹确认。

**Q：难度标签怎么定的？**
抽样阶段用 patch 统计启发式（保证抽样分布可控），入库后改 rubric 人工校准
——patch 大小和解题难度相关性有限，一行修复也可能需要极深的代码理解。

**Q：这些样本会不会已在训练数据里？**
样本全部晚于被测模型训练截止（2026.04–06），运行时又禁网
——训练污染和运行泄露两条通道都堵上了。源仓库本身是公开的，
无法绝对排除厂商爬取更晚数据，这正是"持续更新"必要性的论据。

---

## 附：数据出处速查

| 数字 | 出处 |
|---|---|
| 5548 / 2789 / 4670 / 2459 | `SWE-bench-Live/curation/output/run_20260401_20260629_075520.tar.gz`（Google Drive 有同 md5 备份） |
| 1968 / 100 抽样 | HF 备份 `curation/data/non_gpu_tasks*.jsonl` + summary.json |
| 97 setup / 62 organize | HF 备份 `launch/data/non_gpu_100_emh_deepseek_v4_pro/` |
| 35 失败归因 | `launch/reports/organize_failure_report_2026-07-03.md` |
| 47 validated | HF 备份 `evaluation/logs/deepseek_v4_pro_validation/validated_instances.jsonl` |
| 51 合并 / 22 最终 | `harbor2026/SWE-bench-Live-merged/provenance.json`、`review.md` |
| 29 条剔除逐条台账 | `harbor2026/SWE-bench-Live-merged/harbor-check-notes.md`（Removed Samples 表） |
| 泄露案例与治理 | `harbor2026/SWE-bench-Live-merged/network-leakage-notes.md`、`harbor-check-notes.md` |
| 四维 rubric / 审计规则 | `harbor2026/adapters/swebench_live/swebench-live-check-rubric.toml`、`swebench-live-analyze-prompt.txt` |
| 22 任务本体 | `harbor2026/datasets/swebench-live/` |
| GPT-5.6 单轮跑分（66 trial） | `harbor2026/jobs/swebench-live-22-run-codex-gpt-5-6-{sol,terra,luna}/` |
