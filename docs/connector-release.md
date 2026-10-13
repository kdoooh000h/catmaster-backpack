# 连接器候选安装与恢复

`0.3.0` 本地合并候选提供六宿主共用的 `catmaster-backpack pipelines` 操作入口，
并将两层任务目录接入原有插件/MCP 调用管道。注册更新时分类变化的能力，
使用时逐层选择；执行凭证、参数检查和未知操作隔离沿用已有实现。
本轮源码、独立 wheel 安装和协议验证见 [合并验证记录](capability-integration.md)。
已有宿主连接不自动升级，这份记录也不代表全部原生 Agent 已验收新版。
这份说明只覆盖隔离项目和 profile；配置、安装包检查和原生验收分开记录。
安装包版本与 `catmaster-plugin-pipelines/v1` 注册库、连接协议版本不同。

`0.2.4` 为 Claude Code 原生 CLI Hook 增加项目范围守卫。有效回调的 `cwd`
位于绑定项目外时，Hook 无输出并成功退出，不分发插件、不创建运行数据库。
绑定项目及子目录继续正常分发。缺失、相对、非目录或不存在的 `cwd`、无效事件
仍然失败；核心分发、其他宿主和 gateway session token 的范围检查保持不变。
这允许日常 profile 收到其他项目的原生回调；不表示其他项目已连接 Backpack。

`0.2.5` 为 Pi 生成扩展增加同样的项目范围隔离。扩展加载时先校验当前目录，
项目外或绑定根不存在时不注册 MCP 和事件。每个事件也校验真实 `ctx.cwd`，
项目及子目录继续执行；符号链接按真实路径判断，无效目录不分发。
这项检查不放宽核心管道策略；生成扩展测试使用模拟 Pi API，不代表原生会话验收。

`0.2.6` 将 Claude Code 原生 CLI Hook 的同一范围守卫扩展到 Qwen Code。
有效项目外回调无输出并成功退出，不分发插件、不创建或修改运行数据库；
项目和子目录继续分发，无效目录或事件仍然失败。核心分发、gateway session token
和其他宿主的范围检查保持不变。Qwen MCP 入口保存在绑定项目的 `.qwen/settings.json`，
通过当前 `QWEN_HOME` 选择 profile；原生与 CS profile 共用该项目入口。
测试执行生成的原生 Hook 命令及确定性插件，
不代表真实 Qwen 会话或模型调用验收。

`0.2.7` 让 Qwen MCP 使用原生 `QWEN_CODE_SESSION_ID` 绑定已收到启动回调的
当前会话。实际请求工具列表后，连接关闭会复用原有结束兜底，即使会话尚未调用
插件工具。只握手的协议探测不接管会话；绑定固定启动代次，不关闭其他连接、
其他会话或后来生成的新 token。其他宿主继续按实际工具调用绑定。
该修复不自动清除旧运行记录，也不重放未知操作。

`0.2.8` 对新 Qwen 连接的 profile 与项目 `settings.json` 使用 JSON 配置视图，
仅排除原生自动维护的顶层 `$version` 整数标记和 JSON 排版差异。模型、权限、
MCP、Hook 和其他配置内容仍受保护；连接描述和启动桥继续逐字节校验。
已有字节收据不自动迁移，也不自动恢复用户文件。

`0.2.9` 为 Droid 日常 profile 使用同一项目范围守卫。Droid MCP 保存到项目
`.factory/mcp.json`，通过原生 `FACTORY_HOME_OVERRIDE` 或 `HOME` 选择对应
固定启动桥。原生与 CS profile 共用项目入口，项目外回调不分发。
已有同名全局或项目入口仍拒绝覆盖；核心 session token 范围检查保持严格。

`0.2.10` 为 Hermes 生成桥增加项目范围检查，使用实际进程工作目录。
项目外不注册事件；MCP 保持正常握手但返回空工具列表，不创建运行数据库或
暴露插件目录。项目内继续使用原有共享管道。已有桥不会被自动改写。
解析已有 Hermes YAML 配置时，使用安装包的 `hermes` 可选依赖。

## 保留安装包再连接

使用 Python 3.11 或更新版本。为每个版本创建独立环境，保留 wheel 和环境。
下列路径都是示例，应换成新的隔离路径。不要覆盖现有版本目录。

```sh
python3 -m venv /path/releases/0.2.3
/path/releases/0.2.3/bin/python -m pip install --no-index --no-deps /path/wheels/catmaster_backpack-0.2.3-py3-none-any.whl
/path/releases/0.2.3/bin/catmaster-backpack --version
/path/releases/0.2.3/bin/catmaster-backpack pipelines init --store /path/store --project-root /path/project
/path/releases/0.2.3/bin/catmaster-backpack pipelines connect --store /path/store --host qwen-code --profile-root /path/profile
/path/releases/0.2.3/bin/catmaster-backpack pipelines version --connection /path/profile/backpack-connection.json
```

`connect` 返回宿主启动环境。按 [管道说明](plugin-pipelines.md) 使用该 profile
启动原生会话；Codex 的原生 Hook 审核仍须单独完成。插件注册与调用沿用
`add`、`add --replace`、`unregister`、`acquire → invoke`。

新连接在 profile 保存固定 `backpack-runtime.py` 和 `backpack-release.json`。
已有同名启动桥或收据会拒绝新连接。受管重新连接只允许重现收据记录的配置字节；
新版 adapter 新增目标或改变输出时会在提交前拒绝，不自动迁移宿主配置。
收据记录当前 runtime 路径、版本、包内 Python 文件与 adapter 校验、宿主配置校验。
新收据显式记录配置视图。Codex 的 `config.toml` 固定 TOML 语义内容，仅排除原生界面
维护的 `hooks.state` 和 `tui.screen_reader_detection_done`；其他字段保持固定。
`hooks.json`、启动桥、连接描述和其他宿主文件继续逐字节校验。工具不写入或清除信任状态。
受管重新连接还要求 Codex 配置计划保留当前原字节，不能借排除字段改变原生状态。
固定桥在加载 runtime 前校验这些源码。收据不保存配置内容、模型密钥或会话日志。
校验仅证明记录的本地文件身份，不是发布者签名或外部解释器与传递依赖保证。

## 升级与回退

先停止使用该 profile 的全部原生宿主进程，再把新版 wheel 装到新的独立环境。
使用新版 CLI 执行升级。下面示例从保留的 `0.2.2` 切换到独立安装的 `0.2.3` 修复候选；
本地候选构建不表示已经公开发布。旧实验中的合成 `0.2.1` wheel 不属于此修复候选。

```sh
# 如尚未安装独立的 0.2.3 环境，先按上面的安装步骤完成。
/path/releases/0.2.3/bin/catmaster-backpack pipelines upgrade --connection /path/profile/backpack-connection.json --host-stopped
/path/releases/0.2.3/bin/catmaster-backpack pipelines version --connection /path/profile/backpack-connection.json
/path/releases/0.2.3/bin/catmaster-backpack pipelines rollback --connection /path/profile/backpack-connection.json --host-stopped
```

升级只接受不同安装路径的较新三段数字版本。回退选择最近保留的上一版本。
操作只切换收据中的 runtime 指针，保留原指针备份与全部版本文件，不改宿主设置、
插件注册库、session token 或 unknown 操作回执。回退不是撤销插件业务操作。
固定桥仍使用首次连接时的 Python 解释器；保留该环境，并为后续版本使用兼容解释器。

切换前检查当前 runtime、目标 runtime 和所有已记录配置。固定内容改变或文件缺失都会拒绝。
当前 runtime 损坏时也会拒绝回退；此路径仅支持完整保留版本之间的切换，不提供损坏修复。
这意味着用户修改配置后，工具不会整份覆盖恢复旧配置。停止声明还会核对当前连接的
活动 session 与 MCP peer；崩溃后遗留活动记录会拒绝切换，不会自动清除记录。
进程停止声明由操作员负责，数据库检查不能证明操作系统中没有残留进程。

升级后必须从新的原生会话验证实际行为。`version` 只报告调用方版本、当前指针、
保留版本和文件检查；它不查询线上最新发布，也不证明原生执行成功。
原 unknown 操作继续隔离，不能用升级或回退重放。

## 旧连接与源码模式

无版本收据的旧连接继续使用原 argv，并报告 `unmanaged`；工具不会静默接管。
旧收据未记录配置视图时继续逐字节校验。Codex 原生界面更新旧配置后可能拒绝升级；
新版不会静默迁移旧收据或恢复配置。需要原生状态兼容时，请建立新的隔离连接。
请保留旧 profile，在新隔离项目/profile 中创建受管连接。Claude Code 的项目
`.mcp.json` 也绑定连接；新 profile 不能强占同一个项目的旧 Backpack 入口。

源码 checkout 可用于连接和测试，但不能参与版本切换。受管升级与回退只针对保留的
wheel 安装。源码原地改变时，固定桥拒绝执行；直接调用源码 CLI 不代表通过了桥校验。
本路径不提供初次安装卸载、备份清理、全局部署、自动下载或自动升级。

Wheel 安装方式参考 [pip 官方说明](https://pip.pypa.io/en/stable/cli/pip_install/)。
