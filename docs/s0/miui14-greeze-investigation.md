# MIUI 14 Greeze 调查记录

日期：2026-08-02

设备：Redmi 23078RKD5C（corot），Android 13 / API 33，MIUI 14 V14.0

观察 App UID：10415

## 摘要

Jump Terminator 的 Back 动作在及时获得目标事件后表现稳定；失败点是 MIUI 在自动批次中冻结观察 App 进程，使无障碍回调和 Handler 数十秒不能运行。解冻后事件仍会补到，但已经晚于 500 ms 实时窗口，也晚于测试目标的 900 ms 自行返回，因此不能用于可靠撤销跳转。

这不是仅由统计相关性得出的结论。设备时间线、Greeze 历史、广播超时、主线程停顿和 ANR 在同一时间窗口对齐。

## 可重复现象

### 正式 v0.0.12 武装 100 次

- 实时目标事件与候选：`92/100`；
- 最终目标事件：`100/100`；
- 及时进入动作链的样本：Back `92/92`、离开目标 `92/92`；
- Accessibility 接收年龄 P95：32,252 ms；
- 真值接收年龄 P95：19,383 ms；
- Home 与安全违规：0。

聚合报告：[miui14-23078rkd5c-v012-armed-deferred-truth-stable100-greeze-gap8-20260802.report.json](results/miui14-23078rkd5c-v012-armed-deferred-truth-stable100-greeze-gap8-20260802.report.json)。

### 最近任务锁复测

- MIUI 最近任务界面明确显示 `Jump Terminator S0,已加锁`；
- 批次停止于 42 次，实时目标事件与候选仅 `26/42`；
- 最终目标事件 `42/42`；
- Accessibility 接收年龄 P50/P95 为 6,025/53,063 ms；
- 已动作样本离开目标 `26/26`，安全违规 0。

聚合报告：[miui14-23078rkd5c-v012-armed-recents-locked-stable100-stopped42-greeze-failures-20260802.report.json](results/miui14-23078rkd5c-v012-armed-recents-locked-stable100-stopped42-greeze-failures-20260802.report.json)。

## 系统日志关联

以下是 USB 调试会话中的最小必要摘录。原始 logcat 与 JSONL 保持本地，不发布设备完整日志。

```text
08-02 17:00:12.138 BroadcastQueue: Timeout of broadcast ...
    com.jumpterminator.app.action.S0_TRUTH ... started 60002ms ago
08-02 17:00:12.146 GreezeManager: THAW uid = 10415 pid = [ 20332 ]
    reason : broadcast caller : 1000
08-02 17:00:12.263 ActivityManager: Completed ANR of
    com.jumpterminator.app in 121ms
```

同一轮随后再次出现：

```text
08-02 17:02:10.932 BroadcastQueue: Timeout of broadcast ...
    com.jumpterminator.app.action.S0_TRUTH ... started 60005ms ago
08-02 17:02:10.941 GreezeManager: THAW uid = 10415 pid = [ 20332 ]
    reason : broadcast caller : 1000
08-02 17:02:11.004 ActivityManager: Completed ANR of
    com.jumpterminator.app in 68ms
```

Greeze 历史在上述窗口前后持续把 UID 10415 列在 `LM FZ` 集合中。例如：

```text
2026-08-02T16:59:12.187425 - LM FZ [...] uid = [... 10415]
2026-08-02T17:00:12.146914 - THAW uid = 10415 pid = [ 20332 ]
```

另一复现轮同时记录了主线程消息约 60 秒的墙上耗时：

```text
08-02 16:47:16.478 BroadcastQueue: ... S0_TRUTH ... started 60005ms ago
08-02 16:47:16.486 GreezeManager: THAW uid = 10415 ...
08-02 16:47:16.500 Looper: ... wall=60043ms ...
    JumpAccessibilityService...
08-02 16:47:16.538 ActivityManager: Completed ANR of
    com.jumpterminator.app
```

`S0_TRUTH` 是目标退出后由测试来源发送的延迟真值，用来校准目标实际进入时刻。它没有驱动动作；广播超时在这里暴露了既有冻结，并由系统广播路径触发解冻。动作依据仍是实时无障碍/UsageStats 信号。

## 已验证配置与缓解

| 配置/缓解 | 验证 | 结果 |
| --- | --- | --- |
| 电池策略“无限制” | App 设置与测试前检查 | 仍冻结 |
| MIUI 自启动 | 用户在系统界面开启 | 仍冻结 |
| 用户启动的前台服务 | 持续通知与 `dumpsys activity services` | 仍冻结 |
| device-idle 白名单 | `user,com.jumpterminator.app,10415` | 仍冻结 |
| 实验性 Partial WakeLock | 持有状态下停止于 33 次；实时 `25/33`、最终 `33/33` | 无效，代码已回退 |
| MIUI 最近任务锁 | 系统界面显示“已加锁”；停止于 42 次 | 无效，锁已解除 |

Partial WakeLock 报告：[miui14-23078rkd5c-v013-armed-partial-wakelock-stable100-stopped33-gap8-20260802.report.json](results/miui14-23078rkd5c-v013-armed-partial-wakelock-stable100-stopped33-gap8-20260802.report.json)。

Android 官方把前台服务定义为用户可感知、受后台启动限制约束的长时任务机制，并建议只在确有必要时使用 WakeLock；两者都不构成“第三方 OEM 永不冻结进程”的平台保证：

- [Foreground services overview](https://developer.android.com/develop/background-work/services)
- [Keep the device awake](https://developer.android.com/develop/background-work/background-tasks/awake)

没有尝试不可发布的隐蔽保活方式，例如无可见价值的常驻 Activity、静音音频循环或绕过系统设置。这些做法会损害电量、用户信任和商店合规性，也不改变当前公开 API 架构缺少可靠实时执行保证的事实。

## 结论

在本主设备上，公开 API 观察器可以做到“收到实时事件后快速且安全地 Back”，但不能保证自己在关键窗口内有机会运行。计划 v1.1 要求的目标事件获取率和候选识别率已经正式失败，且合理的用户可见缓解未奏效。因此当前架构为 No-Go，详见 [S0 Go/No-Go 评审记录](go-no-go.md)。
