# Backpack Skill、插件与 MCP 抽样测试

2026-10-13。测试结果有成功，也有明确缺口。两次真实 MCP 调用成功；当前 Codex 对话完成了一次通过背包获取并应用 Skill 的网页任务。公开目录中 7 个存在匹配能力的需求，只有 3 个被正确选中，另外 4 个停止，包含 1 个漏掉正确候选的案例。不能据此宣称所有能力或所有 Agent 已稳定可用。

## 范围与版本

- 本轮隔离安装的 Backpack 为修补后的 0.3.0，源代码提交 `831aea6476ab94fb8a2f4a9b77fef19c688913f3`；安装 wheel 的 SHA-256 为 `ff42f16659643b36df8c41ab7dde349f9895846702ed5b7b44d0ecad5192476c`。
- 公开测试目录共 **24 项可选择能力**，来自 frontend-design、DBHub、filesystem，以及一个包装原始公开 Skill 的组件；另加入 explanatory-output-style 插件，验证它的 SessionStart Hook。Hook 不计入 24 项可选择能力。
- DBHub 为 1.5.0，filesystem 为已固定的 2026.8.31。后者安装时提示日期版本已停用并改用语义化版本；本结果只代表这个固定版本。
- 五个公开 Skill 为 code-reviewer、senior-qa、content-production、senior-backend、senior-frontend，来源为 `alirezarezvani/claude-skills` 的提交 `19392f7a08264ed00486a251f5b2098321771f94`。本轮没有把原先 376 项目录全部接入并重测。
- 需求和期望能力在调用前固定。数据库、文件和网页均为本轮新增的本地合成数据。没有重复此前完成的业务调用，没有自动切换模型通道或付费回退。
- 公开路由使用两层目录，再选具体能力：8 个大类、30 个操作细类，目录保留阈值 0.20，最终置信度门槛 0.65。没有使用全量选择作为回退。
- 本轮未更新八个日常 Agent 连接。它们仍指向此前的 0.3.0 安装；版本号相同不代表包含本轮测试的修补内容。

## 公开目录的 9 个协议样本

此组使用**真实 Jev 决策和真实已安装 MCP 服务**，但 Agent 宿主的生命周期由测试程序模拟。MCP 成功说明背包到服务的调用链完成，不等于某个原生 Agent 完整完成任务。

| 案例 | 需求简述 | 期望能力 | 结果 | 停止时或最终候选数 | 单例时间 |
| --- | --- | --- | --- | ---: | ---: |
| schema_actual | 查看数据库表和字段 | search_objects | 原始最终选择正确，但置信度 0.46，低于门槛而停止 | 9/24 | 1.921 s |
| region_actual | 中英文混合的地区汇总 SQL | execute_sql | 正确选中；真实 SQL 返回预先未知的合成证明值 | 22/24 | 2.722 s |
| text_actual | 同义说法读取本地文本 | read_text_file | 正确选中；真实读取返回预先未知的合成证明值 | 22/24 | 2.152 s |
| design_mixed | HTML/CSS 作品集设计指导 | frontend-design | 正确选中并收到原始说明；此组只检查说明交付 | 22/24 | 1.730 s |
| schema_zh | 中文要求实际获取 schema 元数据 | search_objects | 原始最终选了 explore Skill，置信度 0.53；系统拒绝 | 22/24 | 1.750 s |
| info_synonym | 文件大小、修改时间、文件类型 | get_file_info | 操作细类未保留，正确候选被漏掉 | 0/24 | 1.090 s |
| backend_mixed | REST API 分页与服务端校验指导 | senior-backend | 目录保留了全量候选，按当前规则停止，未进行最终选择 | 24/24 | 1.057 s |
| absent_geology | 地质层序专业方法 | 无匹配能力 | 最终返回 none，置信度 0.81 | 18/24 | 1.729 s |
| absent_language | 梵语韵律专业方法 | 无匹配能力 | 未保留大类而停止；未使用不相关能力 | 0/24 | 0.635 s |

7 个有匹配能力的需求中，**3/7（42.9%）正确选中并通过本组检查**，4/7 停止。3 个被接受的选择均正确；这不足以证明整体准确率为 100%。文件属性案例直接不满足“不漏掉正确能力”的要求。

2 个无匹配能力的对照均未触发错误操作。冻结的严格判定要求返回 `none`，因此第二个返回 `unavailable` 的对照仍记为失败。保留原始 **4/9** 通过数，不通过修改评分标准提高结果。

3 个成功选择都仍保留 22/24 项，候选只缩小 **8.3%**。另一个案例保留全部 24 项后停止。当前分类覆盖较宽，同时仍存在细类漏选；这组结果不支持“既显著缩小范围，又不漏能力”的结论。

## 原生 Agent 与插件测试

| 路径 | 实际检查到的行为 | 结论 |
| --- | --- | --- |
| 新隔离 Claude Code | 原生 Agent 获取到 execute_sql；两层目录加最终选择完成，候选缩至 9/24；实际 session 与 token 绑定匹配 | 获取能力成功，完整任务未完成 |
| 同一 Claude Code 的模型通道 | 第 2 次已转发模型请求返回 HTTP 429；SDK 的后续重试在再次发送前被阻止 | 未发出业务 invoke；0/1 个已尝试原生任务完成。其余 5 个计划案例未执行 |
| explanatory-output-style 插件 | 实际 SessionStart Hook 产生的上下文出现在上述两次原生模型请求中 | 验证了这一个 Hook 的上下文交付；没有证明所有插件组件可移植 |
| 新隔离 Codex CLI | App Server 列出了 Backpack acquire/invoke 工具；11 个自有 Hook 均为 untrusted | 0 个模型回合，未更改信任状态；完整新连接未验证 |
| 当前 Codex 对话中的公开 Skill 背包 | 真实获取 frontend-design，阅读并应用说明，生成合成摄影作品集；浏览器检查桌面、390 px 手机宽度、无横向溢出及展开交互 | 这一个 Skill 的获取与实际应用成功；与新隔离 Codex CLI 是不同路径 |
| 当前 Codex 的私有 PDF 需求 | 正常网关返回 none，置信度 0.96；111 个可用候选中保留 26 个，没有交付说明或执行 PDF 操作 | 记录为未获得能力；不能证明目录中不存在合适能力 |

Claude Code 最终显示的是防重放保护错误，实际已观察到的上游响应是 HTTP 429。原始供应商错误原因未保留，不能认定为额度耗尽或其他具体原因。供应商实际模型身份为 `unobservable`。

原始原生汇总曾把 token/session 绑定标为失败。只读复核发现检查程序使用了错误的哈希方式；修正后的凭据绑定检查通过。原始结果保留，完整任务仍因上述通道失败而未完成，没有重放模型或业务调用。

Codex 的 Hook 信任状态来自实际 `hooks/list` 检查；宿主命令入口见 [Codex developer commands](https://learn.chatgpt.com/docs/developer-commands)。这里只记录检查结果，没有通过改写信任状态绕过宿主审核。工具列表也不等于调用已成功，接口背景见 [Codex App Server](https://learn.chatgpt.com/docs/app-server)。

当前 Codex 的 Skill 使用回执为 `agent_reported`，表示网关记下 Agent 的报告；实际完成证据另来自保存的网页、浏览器检查和截图。这个样本的 Skill 来源是 `anthropics/skills` 提交 `8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4`，与隔离公开目录中的 frontend-design 来源分别记录。

## 时间与消耗

| 阶段 | 时间 | 实际调用数 | 已记录输入 / 输出 token | 限制 |
| --- | ---: | ---: | ---: | --- |
| 首次分类 24 项能力 | 15.943 s | 24 次 Jev | 121,293 / 12,912 | 分类成本，可缓存 |
| 相同目录再次刷新 | 未记录时间 | 0 次 Jev | 无新增分类调用 | 不能把未计时写成 0 秒 |
| 9 个协议案例 | 合计 14.786 s；均值 1.643 s；中位数 1.730 s | 23 次 Jev | 至少 28,118 / 2,682 | 只有 3 个成功选择保留了 usage；其余不是零消耗。均值包含提前停止 |
| 3 个成功协议选择 | 完整单例 1.730–2.722 s；选择阶段 1.696–1.895 s | 各 3 次 Jev | 各约 9,336–9,395 / 893–895 | 不包含首次分类；SQL/文本完整单例包含业务调用 |
| Claude Code 原生尝试 | 12.227 s，未完成 | 2 次模型请求已转发；选择另有 3 次 Jev | Jev 6,540 / 473；原生回执 2,620 / 106 | 原生 usage 对应已返回回执，不能补齐失败请求账单 |
| 当前 Codex 的 Skill 获取 | 0.828 s | 网关返回 1 次 attempt | 未返回 usage | 不含主 Agent 生成和浏览器检查时间 |
| 当前私有 PDF 获取 | 1.670 s | 3 次 Jev | 7,873 / 505 | 返回 none，未执行任务 |

完整主 Agent token、失败请求消耗和计费金额均未完整可观测。使用已有免费测试通道，没有付费回退；不因此推断总 token 成本为零。本轮未运行相同条件的策略 A/B 对照，不能据此宣称速度或 token 优于旧方案。

## 问题与后续优先级

1. 优先修正目录分类与操作细类选择。文件属性需求漏掉 get_file_info，是本轮直接观察到的漏选。
2. 检查跨类别挂载为什么让三个成功案例仍留下 22/24 项。需要同时检查能力归类和需求选类，不能只调整最终门槛。
3. 单独处理最终选择的语义边界与置信度。search_objects 选择正确但 0.46 被拒，另一个 schema 案例误选 explore Skill 且被拒；直接降门槛可能接受后一种错误。
4. 保留模型通道、宿主 Hook 和日常安装版本的独立问题记录。429、untrusted Hook，以及旧安装版本不包含修补，均不能用协议成功替代原生验收。

这些是后续修复方向，本轮只做抽样和记录，没有把未验证的策略变更安装到日常连接。

## 证据与复核

本地证据批次为 `public-sampling-20261013T081625Z`，保存在用户的 Backpack `rollout-evidence` 下。公开汇总见 [机器可读结果](../benchmarks/results/backpack-public-sampling-2026-10-13.json)。原始会话、配置、selection/session 凭据和私有说明不进入仓库。

关键原始收据为 `CLASSIFICATION.json`、`WARM-CLASSIFICATION.json`、`protocol-samples/cause-repaired/SUMMARY.json`、`LOCAL-DIAGNOSTICS.json`、`native-claude/RECONCILIATION.json`、`sql_zh/VERIFICATION-RECONCILED.json`、`codex-native-check/repaired-binary/SUMMARY.json`、`current-codex-skill/VERIFICATION.json` 和 `PRIVATE-PDF-OUTCOME.json`。

准备阶段修复过已固定 filesystem 包的启动依赖位置：原 Documents 目录中存在 iCloud 占位文件，在隔离目录安装同一固定包后恢复启动。此前没有发出业务调用；这一现象指向依赖未物化，但没有完全隔离所有传递依赖，不能宣称唯一原因已证明。另两个测试程序的路径/接口错误发生在模型和业务调用前，修正后使用新收据记录；原始失败保留。

独立只读复核重新计算了通过数、时间和已记录 token，检查了协议/原生范围区别及凭据绑定的审计修正；没有新增模型或业务调用。结束时隔离状态库中活跃 session 为 0，业务操作的 pending/unknown 均为 0。Codex App Server 已退出，但状态库仍保留 1 个标为 active 的 Codex peer，作为生命周期清理缺口记录；没有直接改库掩盖状态。临时网页服务器停止，验证标签已关闭，证据文件保留。
