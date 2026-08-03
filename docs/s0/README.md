# S0 技术可行性验证运行手册

状态：**首要 MIUI 14 设备的当前公开 API 架构已判定 `NO-GO`；S1 暂停，等待架构或产品承诺调整。**

本目录对应项目计划 v1.1 的 S0。它验证公开 Android API 能否稳定观察“测试来源进入前台后，测试目标进入前台”的时序，并在用户显式武装时安全执行一次 Back、验证结果，再按开关最多追加一次 Home。

## 已交付的 S0 工件

- `app`：诊断 App、无障碍服务、UsageStats 轮询、状态机、策略闸门、JSONL 导出；
- `test-source`：手动、延迟、稳定节奏 10/100 次及短间隔压力 10 次触发器，以及设置/浏览器/桌面负样本；
- `test-target`：可自动返回的受控目标 App；
- `scripts/s0_report.py`：样本关联、命中率、误阻止率、延迟和 Wilson 95% 区间；
- `scripts/s0-build.ps1`、`scripts/s0-device.ps1`：构建、安装、状态检查和日志导出；
- `test-matrix.csv`：需要在每台实体设备上填写的基线矩阵；
- `go-no-go.md`：最终评审模板。

三个 S0 APK 均不申请 `INTERNET` 权限。动作代码还包含不可配置的硬边界：只有
`com.jumpterminator.testsource` → `com.jumpterminator.testtarget` 才可能执行全局动作；其他跳转一律记录但不动作。

根目录构建脚本现也会编译独立的 S0.2 Shizuku 实验 APK；它不改变本页的 S0 No-Go 结论，运行方法见 [S0.2 手册](../s02/README.md)。

## 1. 构建

基线环境：JDK 17、Gradle 9.1.0、Android Gradle Plugin 9.0.1、Android API 36、Build Tools 36.0.0。

当前工作站已经在 `%USERPROFILE%\.cache\jump-terminator\toolchain` 配置隔离工具链，可直接运行：

```powershell
Set-Location 'D:\GitProjects\Jump Terminator'
.\scripts\s0-build.ps1
```

在已自行配置 `JAVA_HOME` 和 `ANDROID_SDK_ROOT` 的其他工作站上，也可运行：

```powershell
.\gradlew.bat testDebugUnitTest assembleDebug --no-daemon
```

构建产物：

- `app/build/outputs/apk/debug/app-debug.apk`
- `s02-shizuku-poc/build/outputs/apk/debug/s02-shizuku-poc-debug.apk`（独立 S0.2 实验）
- `test-source/build/outputs/apk/debug/test-source-debug.apk`
- `test-target/build/outputs/apk/debug/test-target-debug.apk`

## 2. 安装与授权

连接并授权一台 ADB 设备后：

```powershell
.\scripts\s0-device.ps1 -Action install
```

脚本依次安装主 App、测试目标、测试来源，然后启动主 App。它不会通过 ADB 偷渡授权；请在设备上人工完成：

1. 打开 Jump Terminator S0；
2. 进入无障碍设置，阅读披露并开启“Jump Terminator S0 观察器”；
3. 返回 App，进入“使用情况访问”并授权；
4. 确认诊断卡显示两个能力均为“是”，用户身份为“已确认”；
5. 允许通知；在 MIUI 上将电池策略设为“无限制”并允许自启动；
6. 由用户在 App 内明确启动前台保活，确认常驻通知可见；应用不会在开机后或被用户停止后静默自启；
7. 保持“仅记录”完成第一轮采样；
8. 只有记录模式和负样本安全闸门通过后，才在受控测试设备上开启“武装测试阻断”，确认弹窗后完成动作轮次。

查看设备、系统版本和授权状态：

```powershell
.\scripts\s0-device.ps1 -Action status
```

连接多台设备时，每条命令附加 `-Serial <adb序列号>`。

## 3. 推荐执行顺序

每台设备均先清空时间线，并在 `test-matrix.csv` 复制一份设备专属记录。

1. **记录模式，双信号检查**：从测试来源触发单次，确认时间线出现实时信号、候选与真值，且不出现 `action_attempt`。
2. **记录模式稳定基线**：运行“稳定自动循环 100 次”。来源间隔为约 6 秒；该节奏曾在短批次稳定，但不能假定可避开 MIUI Greeze，必须以完整批次和实时口径验收。
3. **短间隔压力样本**：单独运行“压力循环 10 次”。该结果用于暴露 OEM 突发冻结风险，不与稳定基线合并，也不能替代稳定基线。
4. **应阻断自动样本**：前述安全闸门通过后再武装，并运行稳定自动循环 100 次。目标在记录模式下会在 900 ms 自行结束，武装模式下应更早被 Back 撤销。
5. **应阻断点击样本**：完成 100 次“手动点击：打开测试目标”。
6. **应允许样本**：累计 200 次设置、浏览器或其他明确允许跳转；任何 `action_attempt` 都算误阻止。
7. **上下文负样本**：累计至少 50 次主动回桌面，并完成锁屏、最近任务、分屏/画中画等 50 次组合测试。
8. **故障与恢复**：修改系统时钟、重启无障碍服务、撤销 UsageStats、锁屏/解锁；确认来源上下文失效，身份未知时禁止动作。
9. **重复设备矩阵**：至少 Redmi MIUI 14 和一台 AOSP/Pixel 对照机；基础动作还必须在一台 Android 9 实体机验证。

不要把自动 100 次循环用于真实应用。S0 测试目标没有业务数据，但 Home 回退会改变当前界面。

## 4. 导出与统计

可在 App 内选择“导出完整 JSONL”，也可通过 ADB：

```powershell
.\scripts\s0-device.ps1 -Action export
```

生成统计报告（Python 3.10+，仅使用标准库）：

```powershell
python .\scripts\s0_report.py `
  .\docs\s0\results\timeline-20260801-120000.jsonl `
  --output .\docs\s0\results\report-20260801.json
```

报告以接收年龄不超过 500 ms 作为“实时”口径，同时保留“最终到达”口径，以免把几十秒后的 OEM 解冻重放误算成实时能力。报告会输出：

- 无障碍、UsageStats 和任一信号的目标获取率；
- 应阻断候选识别率；
- 允许流程误阻止率；
- 最终离开目标成功率；
- 候选、首次动作、最终离开目标的 P50/P95；
- 每个比例的 Wilson 95% 置信区间；
- 重复 Back/Home 等安全违规。

`NOT_READY` 是报告工具的保守机器状态：既可能表示未达门槛，也可能只是完整样本矩阵不足。人工评审仍可在正式硬门槛已失败、且缓解复测再次失败时判定当前架构 No-Go；本机即属于这种情况。

## 5. 当前主设备证据（2026-08-02）

主设备为 Redmi `23078RKD5C`（代号 `corot`），Android 13 / API 33、MIUI 14 `V14.0`、安全补丁 2023-10-01。基线包含电池“无限制”、允许自启动、device-idle 白名单，以及用户明确启动且有持续通知的前台服务。测试目标在退出后才由来源回传原始进入时刻，避免目标侧真值广播在待测窗口内唤醒观察进程。

### v0.0.12 正式武装自动 100 次

| 指标 | 结果 | Wilson 95% / 说明 |
| --- | ---: | --- |
| 实时目标事件获取 | 92/100（92%） | 85.00%-95.89%；门槛 ≥95%，失败 |
| 实时无障碍获取 | 92/100（92%） | 与组合主指标相同 |
| 实时 UsageStats 获取 | 1/100（1%） | 不能单独承担实时动作 |
| 最终目标事件获取 | 100/100（100%） | 8 次仅在解冻后补到，不可用于实时阻断 |
| 实时应阻止候选识别 | 92/100（92%） | 85.00%-95.89%；门槛 ≥93%，失败 |
| 最终离开目标 | 92/92（100%） | 95.99%-100%；只统计及时进入动作链的样本 |
| 安全违规 / Home | 0 / 0 | 每个已处理样本只分派一次 Back |

延迟 P50/P95：候选 103/118 ms、首次动作 227/243 ms、离开目标 284/307 ms。结论是“动作链一旦及时启动就可靠”，但观察进程被冻结时无法启动动作链，因而不能满足产品的可靠阻止承诺。公开证据见[正式武装 100 次报告](results/miui14-23078rkd5c-v012-armed-deferred-truth-stable100-greeze-gap8-20260802.report.json)。

### 武装安全样本

- 手动单次取得目标、候选、Back、最终离开各 `1/1`，候选/动作/离开为 101/225/285 ms，见[手动单次报告](results/miui14-23078rkd5c-v012-armed-manual-single-inline-20260802.report.json)。
- 设置 5、Chrome 5、桌面 5 共 15 个武装允许/上下文样本均为 0 候选、0 动作、0 安全违规，见[武装负样本报告](results/miui14-23078rkd5c-v012-testsource006-armed-negative15-20260802.report.json)。点估计为 `0/15`，但 Wilson 95% 上限为 20.39%，不能宣称已经证明 `≤2%`。
- Home 回退在全部正式测试中保持关闭；测试结束后已恢复 `RECORD_ONLY`、停止前台服务并解除最近任务锁。

### 缓解复测

| 配置 | 实时目标/候选 | 最终目标 | 结论 |
| --- | ---: | ---: | --- |
| 基线：电池无限制 + 自启动 + 前台服务 + device-idle 白名单 | 92/100 | 100/100 | 硬门槛失败 |
| 实验性 Partial WakeLock，停止于 33 次 | 25/33 | 33/33 | 仍被冻结；代码已回退 |
| MIUI 最近任务锁，停止于 42 次 | 26/42 | 42/42 | 仍被冻结；锁已解除 |

Partial WakeLock 和最近任务锁的聚合证据分别见[复测报告](results/miui14-23078rkd5c-v013-armed-partial-wakelock-stable100-stopped33-gap8-20260802.report.json)与[最近任务锁复测报告](results/miui14-23078rkd5c-v012-armed-recents-locked-stable100-stopped42-greeze-failures-20260802.report.json)。详细系统日志关联见 [MIUI Greeze 调查记录](miui14-greeze-investigation.md)。

历史 v0.0.6 稳定 100 次因目标侧即时真值广播可能唤醒观察进程，只保留为历史基准；v0.0.10 延迟真值 10 次和早期短间隔压力样本则用于解释测试演进，不覆盖本次正式武装 100 次结论。

## 6. Go 门槛

- 目标事件获取率 ≥ 95%；
- 应阻止候选识别率 ≥ 93%；
- 允许流程误阻止率 ≤ 2%；
- 最终离开目标成功率 ≥ 90%；
- 不出现无限返回、关键系统界面动作或用户身份混淆；
- 自动应阻止 100、点击应阻止 100、允许 200、桌面主动打开 50、锁屏/最近任务/多窗口 50 的最小样本完成；
- 每项同时报告点估计和 Wilson 95% 置信区间；
- Redmi MIUI 14、对照设备和 Android 9 实体机证据齐全。

无法稳定执行一次安全返回，或关键实时采集/候选门槛失败且合理缓解后仍复现，应判定 No-Go。最终结论填写在 `go-no-go.md`。

## 7. 当前结论与边界

- 当前消费者 App + 公开 API 架构在首要 MIUI 14 设备上为 **No-Go**，不得据此启动 S1；
- 该结论针对“可靠撤销跳转”的当前架构和产品承诺，不证明所有 Android/OEM/企业设备实现路径都不可行；
- 对照设备、Android 9 实体机、允许 200 次等矩阵未继续扩样，因为首要平台的两个硬门槛已经在正式 100 次及两种缓解复测中失败；架构调整后应从新的 S0 门开始；
- 若产品改为“尽力而为的记录/提醒”，必须重写成功指标和用户文案，不能沿用“可靠阻止”承诺；
- S0 只证明受控包之间的公开 API 能力，不证明能获得原始 Intent 或权威调用链；
- UsageStats 使用墙上时钟，已映射到单调时钟；系统时钟跳变超过 5 秒会清空来源上下文；
- 无障碍事件时间是 uptime，代码映射到 elapsed realtime 后再与 UsageStats 合并；
- `performGlobalAction()` 的布尔返回只表示动作已分派，最终成功必须由后续前台状态确认；
- S0 不读取窗口文本、不遍历节点树、不执行 Shell、不处理测试包之外的目标。
