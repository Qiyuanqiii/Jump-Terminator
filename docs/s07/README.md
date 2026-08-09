# S0.7 设备状态与多窗口上下文失效验证

状态：**完成，结论为 `S07_DEVICE_STATE_GATE_PASSED`**

基线提交：`681b3da`

设备：Redmi `23078RKD5C` / `corot`，Android 13，MIUI 14

执行日期：2026-08-09

实现版本：`0.0.7-s07` / UserService v6

## 本阶段验证什么

S0.7 验证来源上下文在设备状态和窗口拓扑发生变化时能否可靠失效。以下场景一律定义为零动作上下文：

- 打开最近任务后再启动固定测试目标；
- 固定测试来源与目标同时处于分屏、两者均为 `topResumedActivity`；
- 来源在前台时息屏并进入安全锁屏，锁屏期间启动目标，随后由用户正常解锁。

每个零动作会话都必须先观察到唯一来源，再观察到明确的上下文失效事件；之后目标检测、Back 请求和服务错误必须全部为 `0`。矩阵末尾另跑 10 次普通全屏来源到目标，证明 fail-closed 修复没有关闭合法的固定测试路径。

## 修复前发现的问题

`0.0.6-s06` 只读取 `dumpsys activity activities` 中第一条 `topResumedActivity`。分屏时来源和目标可以同时处于 resumed 状态，但旧实现把窗口集合压缩成单个组件，无法表达歧义。

修复前会话 `9957ab8bb5ba41bda9f8d97b1e555442` 在真实分屏中先建立来源上下文，随后把目标当作唯一前台，产生 `target_detected=1` 和已派发的 `back_requested=1`。这会干扰用户仍在使用的另一个分屏窗格，因此判定为必须修复的误动作。原始关键事件见[修复前失败摘录](results/miui14-23078rkd5c-s07-device-state-v007-20260809/s07-split-screen-v006-pre-fix-failing-excerpt.jsonl)。

## `0.0.7-s07` 的窄修复

- 读取并去重全部 `topResumedActivity`；集合大于 1 时标记 `foregroundAmbiguous=true`，不再任意选择第一项；
- resumed 组件集合发生变化时，即使状态仍为 `ambiguous`，也记录新的 `foreground_changed` 证据；
- 来源上下文遇到最近任务/其他前台时以 `foreground_changed` 失效，遇到多前台时以 `foreground_ambiguous` 立即失效；
- 每次最终动作授权同时复核设备交互状态和安全锁屏状态；息屏、锁屏、状态未知、前台未知或多前台均拒绝动作；
- 监控循环在来源有效期间主动读取电源与锁屏状态，`Dozing`/`Asleep` 不依赖 Activity 是否仍被系统保留为 top-resumed，都会立即使来源失效；
- MIUI 的普通全屏切换会出现约 50–100 ms 的瞬时空 `topResumedActivity`。仅该“前台未知且设备仍可交互”状态采用 500 ms 持续门；多前台、息屏和锁屏不去抖，仍立即失效。

运行器不会尝试绕过安全锁屏。它唤醒设备后等待用户正常解锁，并要求 `Awake + keyguardLocked=false` 连续稳定 3 秒才继续正向对照。

## 正式真机结果

| 场景 | 覆盖与关键证据 | 检测 / Back | 判定 |
| --- | --- | ---: | --- |
| 最近任务 | `5/5`；边界为 MIUI Launcher，来源均以 `foreground_changed` 失效 | `0 / 0` | 通过 |
| 分屏 | `5/5`；每轮来源与目标均同时 top-resumed，`mInSplitScreen=true`，来源均以 `foreground_ambiguous` 失效 | `0 / 0` | 通过 |
| 息屏与安全锁屏 | `1/1`；边界为 `Dozing`、`interactive=false`，以 `device_not_interactive` 失效；解锁后为 `Awake` 且未锁 | `0 / 0` | 通过 |
| 全屏正向对照 | 检测、Back、离开目标、返回来源均为 `10/10` | `10 / 10` | 通过 |
| 完整性 | 11 个零动作会话 ID 唯一；服务错误、超时、失败事件、证据警告和安全违规均为 0 | — | 通过 |
| 聚合门 | 样本门与安全门均为 `true` | — | `S07_DEVICE_STATE_GATE_PASSED` |

正向对照的保守延迟上界为：检测 P50/P95 `134/274 ms`，Back 请求 `305/409 ms`，离开目标 `380/504 ms`，输入执行 `25/34 ms`，轮询 `21/36 ms`。

正式证据：

- [S0.7 聚合报告](results/miui14-23078rkd5c-s07-device-state-v007-20260809/s07-device-state.report.json)
- [11 个零动作会话原始时间线](results/miui14-23078rkd5c-s07-device-state-v007-20260809/s07-device-state.jsonl)
- [10 次全屏正向对照报告](results/miui14-23078rkd5c-s07-device-state-v007-20260809/s07-fullscreen-positive.report.json)
- [10 次全屏正向对照原始时间线](results/miui14-23078rkd5c-s07-device-state-v007-20260809/s07-fullscreen-positive.jsonl)

聚合报告记录了三份正式输入的 SHA-256，且 `warnings=[]`。全屏子报告沿用 S0.2 的完整 100+15 样本门，因此单独显示 `NOT_READY`；S0.7 聚合器重新核对本阶段规定的 10 次正向对照、最小授权不变量和零动作安全门，不把子报告的样本不足误判为功能失败。

## 自动验证与复现

- `ForegroundSafetyTest` 覆盖单前台、多前台、前台缺失、Awake、Asleep 和设备状态缺失；
- `OwnerAuthorizationPolicyTest` 新增分屏歧义、息屏和锁屏拒绝测试；
- `test_s07_device_state_report.py` 覆盖完整通过、最近任务误 Back、锁屏样本缺失、分屏证据不足和证据警告；
- 全工程 Android 单元测试 `63` 项、Python 测试 `41` 项以及完整 build/lint 由本阶段质量门复核。

```powershell
python -m unittest scripts.test_s07_device_state_report -v
.\gradlew.bat :s02-shizuku-poc:testDebugUnitTest
.\scripts\s07-device-state.ps1 `
  -RecentsCycles 5 `
  -SplitScreenCycles 5 `
  -ScreenLockCycles 1 `
  -Serial LBEATC9LPBYPMVFA
```

锁屏场景会要求操作者手动解锁。运行器的 `finally` 路径会唤醒设备、恢复 POC 权限、确保 Shizuku 运行、停止固定测试包并返回桌面；它不会保存、输入或绕过设备凭据。

## 剩余边界

- 本次仍只有一台 MIUI 14 / Android 13 设备、固定测试包、debug 自动化和 L1 Back；
- 尚未覆盖画中画、多显示器、多用户、工作资料、双开、其他 OEM/Android 版本和真实第三方应用；
- 安全锁屏只做 1 个需人工解锁的正式周期，尚未覆盖不同 PIN/生物识别配置和大量重复压力；
- 500 ms 前台未知持续门来自本设备观察，仍需在更多 OEM 和负载条件下校准；
- Standard S0 继续为 No-Go；消费者发布、真实第三方目标和 L3-L5 持久动作仍未获授权。
