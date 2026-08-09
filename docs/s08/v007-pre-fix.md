# S0.8 修复前 v0.0.7 PiP 误动作记录

这是 2026-08-09 在 Redmi `23078RKD5C` / Android 13 / MIUI 14 上执行的修复前手工基线记录。会话 ID 为 `839d250d781c4398b3526a2439d1dff2`，实现为 `0.0.7-s07` / UserService v6。

## 确定性编排

1. 启动固定来源作为底层窗口；
2. 启动固定目标并请求 PiP；
3. 等待 `pip_mode_changed(active=true)`，并用 `dumpsys activity activities` 确认目标任务为 `mode=pinned`；
4. 在目标保持 pinned 的前提下启动监控，再把固定来源带到前台；
5. 等待旧服务把来源记录为 `state=source`；
6. 重新启动固定目标以展开已有 PiP 任务。

目标在监控 ready 和来源上下文建立前已经稳定进入 PiP，因此该复现不把 PiP 请求阶段的短暂全屏窗口误算成失败。

## 关键时序

| 墙上时钟 ms | 事件 |
| ---: | --- |
| `1786269183796` | 测试目标请求 PiP，`accepted=true` |
| `1786269184256` | 测试目标报告 `pip_mode_changed(active=true)`；系统活动栈同时确认 pinned |
| `1786269186463` | companion `ready` |
| `1786269188968` | companion 把来源记录为 `state=source` |
| `1786269191106` | 展开操作使目标报告 `pip_mode_changed(active=false)` |
| `1786269191646` | companion 产生 `target_detected=1` |
| `1786269191800` | companion 产生 `back_requested=1`，`dispatched=true` |

从 PiP active 到来源被接受相隔约 `4.7 s`，到错误检测相隔约 `7.4 s`。根因是 v0.0.7 的 `ForegroundSnapshot` 仅保留去重后的 top-resumed 组件，不保留 pinned/windowing 状态；它无法表达“来源全屏时仍有一个可见 PiP 任务”，因而建立了错误的来源上下文。

该基线用于证明修复必要性；正式通过结论只使用 v0.0.8 的自动化双时钟与结构化证据，见 [S0.8 聚合报告](results/miui14-23078rkd5c-s08-pip-v008-20260809/s08-pip-context.report.json)。
