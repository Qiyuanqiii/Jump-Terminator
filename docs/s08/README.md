# S0.8 画中画窗口拓扑失效安全验证

状态：**完成，结论为 `S08_PIP_CONTEXT_GATE_PASSED`**

基线提交：`423d5e5`

设备：Redmi `23078RKD5C` / `corot`，Android 13，MIUI 14

执行日期：2026-08-09

实现版本：`0.0.8-s08` / UserService v7；测试来源 `0.0.8-s08`；测试目标 `0.0.4-s08`

## 本阶段验证什么

S0.8 验证固定来源或固定目标处于画中画（PiP）时，前台模型是否会因为只看到唯一 `topResumedActivity` 而错误沿用来源上下文。以下场景一律定义为零动作上下文：

- 目标已经由系统确认处于 `mode=pinned`，再打开来源并展开该目标；
- 目标在底层全屏、来源先建立有效上下文，随后来源进入 `mode=pinned` 并露出目标。

每轮都必须同时取得测试 APK 的 `pip_mode_changed(active=true)` 和系统活动栈中的 pinned 任务，保存 display、top-resumed、任务、windowing mode、可见状态和活动组件的结构化快照。缺少任一真值、超时或运行器错误都只能判 `NOT_READY`；PiP 会话中的任意目标检测或 Back 请求直接判 `STOP_S08_PIP_CONTEXT_PATH`。

## 修复前发现的问题

`0.0.7-s07` 已能识别多个 top-resumed Activity，却仍完全丢失 pinned 窗口。修复前会话 `839d250d781c4398b3526a2439d1dff2` 先让目标进入 PiP，并在系统活动栈确认 pinned；PiP 于墙上时钟 `1786269184256` 进入 active，监控随后于 `1786269186463` ready，来源于 `1786269188968` 被采样。展开目标后，旧服务于 `1786269191646` 产生 `target_detected=1`，并于 `1786269191800` 派发 `back_requested=1`。

这不是“PiP 请求与全屏检测”的竞态：目标在来源上下文建立前约 4.7 秒已经进入 PiP。旧模型把“来源全屏 + 仍可见的目标 PiP”压缩成唯一来源，因而建立了本不应存在的来源上下文。复现时序见[修复前 v0.0.7 记录](v007-pre-fix.md)。

## `0.0.8-s08` 的窄修复

- 前台采样同时读取全部 `topResumedActivity` 以及 active task 中的 `mode=pinned`、`mWindowingMode=pinned` 和 PiP 报告状态；
- `ForegroundSnapshot` 保留 pinned 包集合与 `pictureInPictureActive`，任意活动 PiP 都使快照 fail-closed，不再把唯一 top-resumed 误当作唯一交互上下文；
- 监控循环显式记录 `state=picture_in_picture`，已有来源上下文立即以 `reason=picture_in_picture` 失效；
- 最终动作授权在同一串行化边界再次读取 PiP 状态，即使监控循环与动作间发生窗口变化也会拒绝；
- 固定来源与目标测试 APK 增加受控 PiP 入口、双时钟和会话绑定日志。来源入口固定延迟 1.5 秒，只用于确定性证明“先建立来源，再进入 PiP”；
- 自动运行器先请求停止并等待 `complete(reason=stop_requested)`，再汇总会话；保存监控观察窗口内捕获的原始 companion/PiP 事件、结构化系统快照和三份输入证据的 SHA-256。

## 正式真机结果

| 场景 | 覆盖与关键证据 | 检测 / Back | 判定 |
| --- | --- | ---: | --- |
| 目标预先 PiP 后展开 | `5/5`；每轮在监控前及展开前确认目标 pinned，来源出现时服务均记录 PiP 状态 | `0 / 0` | 通过 |
| 来源 PiP 露出目标 | `5/5`；每轮先观察来源，随后确认“来源 pinned + 目标 top-resumed”，均以 `picture_in_picture` 失效 | `0 / 0` | 通过 |
| 全屏正向对照 | 检测、Back、离开目标和返回来源均为 `10/10` | `10 / 10` | 通过 |
| 完整性 | 10 个 PiP 会话 ID 唯一；每轮 armed/Shizuku/owner 授权租约均覆盖 PiP 边界至 worker complete，并在 stop-complete 后汇总；运行器错误、服务错误、超时、警告、readiness gap 和安全违规均为 0 | — | 通过 |
| 聚合门 | 样本门与安全门均为 `true` | — | `S08_PIP_CONTEXT_GATE_PASSED` |

正向对照的保守延迟上界为：检测 P50/P95 `153/186 ms`，Back 请求 `335/391 ms`，离开目标 `418/494 ms`，输入执行 `25/31 ms`，轮询 `29/47 ms`。

正式证据：

- [S0.8 聚合报告](results/miui14-23078rkd5c-s08-pip-v008-20260809/s08-pip-context.report.json)
- [10 个 PiP 零动作会话原始时间线](results/miui14-23078rkd5c-s08-pip-v008-20260809/s08-pip-context.jsonl)
- [10 次全屏正向对照报告](results/miui14-23078rkd5c-s08-pip-v008-20260809/s08-fullscreen-positive.report.json)
- [10 次全屏正向对照原始时间线](results/miui14-23078rkd5c-s08-pip-v008-20260809/s08-fullscreen-positive.jsonl)

聚合报告记录的三份源证据 SHA-256 分别为 `BECD83691971F769DD788CF8BE84E6AA7B8C8B09961876EA78C9F66F3C70EA02`、`530C595351F1A76FAE8F4BD88AC9D9E24C973AB75976059C5CC645A986CE4315` 和 `18AEA639182BC2FADA508F46C12D2000199CDB50F9A0883020324E81061F73BA`。

结构化快照只保留边界时仍可见的任务，正式时间线中的组件仅属于控制包、固定来源和固定目标。每份快照的 `rawActivitySha256` 是采集时 `dumpsys activity activities` 的指纹；为避免保存无关历史任务信息，原始 dumpsys 文本没有持久化，因此该逐快照指纹不能脱离设备日志独立重算。可复算的发布证据边界是上述三份完整文件哈希。

全屏子报告沿用 S0.2 的完整 100 次正样本加 15 次允许流程门，因此单独显示 `NOT_READY`；S0.8 聚合器重新核对本阶段规定的全屏 `10/10`、最小授权不变量与 PiP 零动作安全门，不把子报告的跨阶段样本不足误判为本阶段失败。

## 自动验证与复现

- `ForegroundSafetyTest` 覆盖 pinned task、PiP 状态过渡、普通 PiP 能力声明及既有单/多前台模型；
- `OwnerAuthorizationPolicyTest` 覆盖最终动作阶段的显式 `picture_in_picture` 拒绝；
- `test_s08_pip_report.py` 覆盖完整通过、PiP 误 Back 硬停止、缺 pinned 证据、正向回归不足、结构化边界缺失、跨会话事件混入、武装/Shizuku/owner 授权绑定缺失、负样本租约未覆盖观察窗或声明时长不一致、stop-complete 缺失或计数藏匿、汇总计数不一致、PiP 因果倒置、错误来源上下文、PiP/失效拓扑不匹配、正向序列重复/错序、ready→动作→complete 或租约因果链破坏、正向时间线不匹配和零样本期望值；
- 全工程 Android 单元测试 `67` 项、Python 测试 `60` 项以及完整 build/lint 由本阶段质量门复核。

```powershell
python -m unittest scripts.test_s08_pip_report -v
.\gradlew.bat :s02-shizuku-poc:testDebugUnitTest
.\scripts\s08-pip-context.ps1 `
  -TargetPreexistingPipCycles 5 `
  -SourcePipTargetCycles 5 `
  -Serial LBEATC9LPBYPMVFA
```

## 剩余边界

- 本次仍只有一台 MIUI 14 / Android 13 设备、单用户、固定测试包、debug 自动化和 L1 Back；
- 设备声明支持 secondary displays，但正式快照只有真实内置 `displayId=0`；没有实体副屏，因此多显示器只完成能力探测，不能宣称通过；
- pinned/PiP 文本标记属于当前 Android/OEM 的 `dumpsys` 表达，仍需在其他 OEM 与 Android 版本校准；
- 证据嵌入边界截止每个 worker 的 `complete(reason=stop_requested)`；其后的撤权和服务退出属于行政型收尾日志，不纳入本时间线，现存设备日志复核未发现任何迟到检测或 Back；
- 尚未覆盖自由窗、多用户、工作资料、双开、真实第三方目标、内存压力、轮询冻结和 stop/start 竞态；这些可靠性与并发项转入 S0.9；
- Standard S0 继续为 No-Go；本门不授权消费者发布、真实第三方应用控制或 L3-L5 持久动作。
