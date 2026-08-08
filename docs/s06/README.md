# S0.6 韧性压力与权限撤销验证

状态：**完成，结论为 `S06_RESILIENCE_STRESS_PASSED`**

基线提交：`9d2b9f4`

设备：Redmi `23078RKD5C` / `corot`，Android 13，MIUI 14

执行日期：2026-08-08

实现版本：`0.0.6-s06` / UserService v5

## 本阶段验证什么

S0.6 把此前的单次生命周期和执行面样本扩展为三个可重复压力门：

- 连续 5 次普通 UI 崩溃：每次都必须保留且只完成已经授权的一次有界动作，记录 owner 脱离，并在会话完成后请求 UserService 退出；
- 同一有界授权内连续 10 次固定测试来源到固定测试目标：检测、单次 Back、离开目标、返回来源都必须恰好 `10/10`；
- 连续 3 次 Android 运行时权限撤销/恢复：撤权阶段不得出现特权 `ready`，恢复后必须恰好出现一次 `ready`。

本门仍只允许固定测试包、L1 单次 Back 和 ADB 调试环境，不扩大到真实第三方目标或持久动作。

## 冒烟测试发现并修复的问题

`0.0.5-s05` 的首次 `1/1/1` 冒烟在撤权门失败。Android `dumpsys package` 已显示 `moe.shizuku.manager.permission.API_V23: granted=false`，但唯一会话 `5b94c971e7ae4be18b8a5716347860e1` 仍产生 `ready=1`。失败证据见 [修复前撤权样本](results/miui14-23078rkd5c-s06-resilience-v006-20260808/s06-reauthorization-v005-pre-fix-failing.jsonl)。

根因是应用只信任 `Shizuku.checkSelfPermission()`。Shizuku 13.1.5 会缓存已附加客户端的正向授权状态；直接用 ADB 撤销 Android 运行时权限时，这个正向状态可能暂时保持，因而平台权限与 Shizuku 授权视图发生分歧。

`0.0.6-s06` 将权限不变量改为同时满足：

1. Android `checkSelfPermission(API_V23)` 为已授权；
2. `Shizuku.checkSelfPermission()` 为已授权。

平台授权为假时会短路，不绑定 UserService，也不请求创建特权会话。修复后的同一冒烟样例为撤权 `ready=0`、恢复 `ready=1`；正式矩阵连续 3 次得到相同结果。正常已授权连接、ADB debug 自动化、固定规则和 UserService v5 协议保持不变。

## AIDL 可达性前置复核

本阶段也复核了 `IPrivilegedCompanion` 的 `status`、`stopMonitor`、`drainEvents` 与 `destroy`。表面上，空闲状态下部分方法没有 active-owner 复核；但官方 Shizuku UserService 管理器在返回服务 Binder 前会核对请求组件包与 Binder 调用包，其他应用不能以自己的包请求 `com.jumpterminator.s02` 的 UserService Binder。`destroy` 同时是 Shizuku 服务端用于销毁/版本替换 UserService 的保留生命周期事务，强制只接受应用 UID 会破坏合法生命周期调用。

因此该怀疑项判定为 **no-change**：跨应用调用路径未成立，不做会破坏 Shizuku 生命周期的推测性补丁。这个结论只覆盖当前 UserService 获取路径，不替代后续完整安全审计。参考 [Shizuku UserService 文档](https://github.com/RikkaApps/Shizuku-API#userservice)和[官方实现](https://github.com/RikkaApps/Shizuku)。

## 正式真机结果

| 压力门 | 样本与关键结果 | 判定 |
| --- | --- | --- |
| UI 普通崩溃 | `5/5` 生命周期门通过；每个会话 owner 脱离 `1`、退出请求 `1`、检测/Back/离开/返回均 `1/1` | 通过 |
| 重复固定目标 | 会话 `ffeca6231cbf4e4db7b190d57c9a3176`：检测/Back/离开/返回均 `10/10` | 通过 |
| 最小授权绑定 | Binder UID、签名、一次性能力、规则快照、租约与最终动作串行化检查全部通过 | 通过 |
| 撤权负样本 | 3 个独立撤权会话均 `granted=false`、`ready=0` | 通过 |
| 恢复正样本 | 3 个独立恢复会话均 `granted=true`、`ready=1` | 通过 |
| 安全事件 | 安全违规、超时、失败事件均为 `0` | 通过 |
| 聚合门 | 样本门与安全门均为 `true` | `S06_RESILIENCE_STRESS_PASSED` |

重复目标的保守延迟上界为：检测 P50/P95 `70/131 ms`，Back 请求 `110/175 ms`，离开目标 `186/318 ms`，输入执行 `27/95 ms`，轮询 `30/47 ms`。

正式证据：

- [S0.6 聚合报告](results/miui14-23078rkd5c-s06-resilience-v006-20260808/s06-resilience.report.json)
- [10 次重复目标原始时间线](results/miui14-23078rkd5c-s06-resilience-v006-20260808/s06-repeated-targets.jsonl)
- [3 次撤权/恢复原始时间线](results/miui14-23078rkd5c-s06-resilience-v006-20260808/s06-reauthorization.jsonl)
- [5 个 UI 崩溃原始样本目录](results/miui14-23078rkd5c-s06-resilience-v006-20260808/)

重复目标子报告沿用 S0.2 的完整门，后者要求至少 100 个阻止样本和 15 个允许样本，所以子报告显示 `NOT_READY`。S0.6 聚合器不把它误当成失败，而是重新检查本阶段规定的 10 次压力样本、授权证据和安全事件；S0.2 原有的 100+15 结果仍由 S0.2/S0.4 回归报告负责。

## 自动验证与复现

- `ShizukuPermissionGateTest` 4 项覆盖双授权全组合，明确拦截“平台已撤权、Shizuku 仍缓存允许”；
- `test_s06_resilience_report.py` 7 项覆盖完整通过、样本不足、撤权时出现 `ready`、重复目标不完整、重复事件、会话 ID 复用和证据警告；
- 全工程 Android 单元测试 `52` 项、Python 测试 `35` 项通过；完整 Gradle build/lint 通过。

```powershell
python -m unittest scripts.test_s06_resilience_report -v
.\gradlew.bat :s02-shizuku-poc:testDebugUnitTest
.\scripts\s06-resilience.ps1 `
  -CrashCycles 5 `
  -RepeatedTargets 10 `
  -ReauthorizationCycles 3 `
  -Serial LBEATC9LPBYPMVFA
```

运行器在 `finally` 中恢复 POC 权限、重新启动 Shizuku、停止全部固定测试包并返回桌面；即使中途门失败，也执行同一恢复路径。

## 剩余边界

- 撤权压力使用 ADB 直接切换 Android 运行时权限，验证的是应用 fail-closed 不变量，不代表 Shizuku Manager 授权界面的 UI/交互已验收；
- 这次压力矩阵只有一台 MIUI 14 设备，未覆盖其他 OEM、Android 版本、多用户、工作资料、双开或多显示器；
- 尚未完成锁屏/最近任务/分屏的重复压力、内存压力并发、UserService 跨重启重放状态和真实第三方应用矩阵；
- 普通 UI 崩溃的 10 秒宽限仅允许已经绑定的一次有界会话收尾，不允许开始新会话；
- Standard S0 继续为 No-Go，L3-L5、真实第三方目标和消费者发布仍未获授权。
