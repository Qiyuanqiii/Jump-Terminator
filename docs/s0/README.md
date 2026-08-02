# S0 技术可行性验证运行手册

状态：**工程 PoC、MIUI 14 延迟真值校准和记录模式负样本预检已经完成；动作、武装允许流程、完整负样本及跨设备矩阵尚未完成，当前结论仍为 `NOT_READY`。**

本目录对应项目计划 v1.1 的 S0。它验证公开 Android API 能否稳定观察“测试来源进入前台后，测试目标进入前台”的时序，并在用户显式武装时安全执行一次 Back、验证结果，再按开关最多追加一次 Home。

## 已交付的 S0 工件

- `app`：诊断 App、无障碍服务、UsageStats 轮询、状态机、策略闸门、JSONL 导出；
- `test-source`：手动、延迟、稳定节奏 10/100 次及短间隔压力 10 次触发器，以及设置/浏览器/桌面负样本；
- `test-target`：可自动返回的受控目标 App；
- `scripts/s0_report.py`：样本关联、命中率、误阻止率、延迟和 Wilson 95% 区间；
- `scripts/s0-build.ps1`、`scripts/s0-device.ps1`：构建、安装、状态检查和日志导出；
- `test-matrix.csv`：需要在每台实体设备上填写的基线矩阵；
- `go-no-go.md`：最终评审模板。

三个 APK 均不申请 `INTERNET` 权限。动作代码还包含不可配置的硬边界：只有
`com.jumpterminator.testsource` → `com.jumpterminator.testtarget` 才可能执行全局动作；其他跳转一律记录但不动作。

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
2. **记录模式稳定基线**：运行“稳定自动循环 100 次”。稳定循环的来源间隔为 6 秒，高于本机观察到的 5 秒 Greeze 冻结窗口；这是正式候选识别基线。
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

`NOT_READY` 既可能表示未达门槛，也可能只是样本数不足，不应直接解释为技术 No-Go。锁屏、最近任务、多窗口及 OEM 覆盖仍需结合人工矩阵评审。

## 5. 当前主设备证据（2026-08-02）

主设备为 Redmi `23078RKD5C`（代号 `corot`），Android 13 / API 33、MIUI 14 `V14.0`、安全补丁 2023-10-01。测试配置为电池“无限制”、允许自启动、用户明确启动前台服务并保持 `RECORD_ONLY`；没有执行 Back、Home 或其他动作。

### v0.0.10 延迟真值校准

测试目标不再在进入时广播真值，而是在退出后把原始进入时刻返回给来源，再由来源发送真值。这样目标 App 不会在待测窗口内通过广播唤醒观察进程。

| 指标 | 结果 | 说明 |
| --- | ---: | --- |
| 实时目标事件获取 | 10/10（100%） | Wilson 95%：72.25%-100% |
| 实时无障碍获取 | 10/10（100%） | 主信号；P50/P95 接收年龄 75/82 ms |
| 实时 UsageStats 获取 | 0/10；最终 10/10 | 仅作辅助信号，不作为单独实时动作依据 |
| 实时应阻止候选识别 | 10/10（100%） | Wilson 95%：72.25%-100% |
| 候选生成延迟 | P50 110 ms / P95 140 ms | 满足当前 ≤150 ms 参考线 |
| 动作、安全违规 | 0 / 0 | 仅记录模式 |

本批次还把 20 条超过 500 ms 的陈旧信号和 10 条与实时无障碍窗口冲突的 UsageStats 信号拒绝出状态机；公开证据见 [延迟真值报告](results/miui14-23078rkd5c-v010-deferred-truth-record-only-stable10-20260802.report.json)。

### 记录模式负样本预检

- 设置 5、Chrome 5、桌面 5 共 15 个允许/上下文样本：`0/15` 动作、0 候选、0 安全违规；[负样本报告](results/miui14-23078rkd5c-v010-testsource006-record-only-negative15-20260802.report.json)中的允许流程误阻止 Wilson 95% 上限仍为 20.39%。
- 来源回桌面后，不返回来源而直接打开 Chrome；观察到 Chrome 延迟信号后仍为 0 候选、0 动作，见[上下文断路报告](results/miui14-23078rkd5c-v010-home-then-chrome-context-break-probe-20260802.report.json)。
- 由于 `RECORD_ONLY` 从策略上禁止动作，`0/15` 只能证明当前记录链没有意外动作和陈旧上下文复用，不能替代 `ARMED_BLOCK` 下至少 200 个允许流程样本。

### 历史与压力证据

v0.0.6 稳定 100 次曾取得实时目标事件和候选 `100/100`、候选 P50/P95 100/110 ms；但当时测试目标会在进入时立即发送真值广播，可能唤醒观察进程。因此该[稳定 100 次报告](results/miui14-23078rkd5c-v006-unrestricted-fgs-autostart-idle35-record-only-stable100-20260802.report.json)只保留为长批次历史基准，不再单独充当无偏采集验收证据。用户误触退出的 65 次部分样本只作本地诊断留档，不计入正式结果，也不计作失败。

无障碍服务重连探针取得 `1/1` 实时目标和 `1/1` 候选，候选延迟 94 ms；旧 UsageStats 事件被标记为 `collector_warmup` 且不驱动候选，公开证据见 [重连报告](results/miui14-23078rkd5c-v006-accessibility-reconnect-probe-20260802.report.json)。

短间隔压力 10 次只有 `2/10` 实时到达，但最终 `10/10` 到达，候选延迟 P50/P95 为 47,992/58,792 ms；设备日志同期出现 MIUI Greeze 冻结/解冻记录。这是仍需处理和复测的 OEM 突发压力风险，不应被稳定 100 次结果掩盖。公开证据见 [压力报告](results/miui14-23078rkd5c-v005-unrestricted-fgs-autostart-idle35-record-only-auto10-eventual-20260802.report.json)。

## 6. Go 门槛

- 目标事件获取率 ≥ 95%；
- 应阻止候选识别率 ≥ 93%；
- 允许流程误阻止率 ≤ 2%；
- 最终离开目标成功率 ≥ 90%；
- 不出现无限返回、关键系统界面动作或用户身份混淆；
- 自动应阻止 100、点击应阻止 100、允许 200、桌面主动打开 50、锁屏/最近任务/多窗口 50 的最小样本完成；
- 每项同时报告点估计和 Wilson 95% 置信区间；
- Redmi MIUI 14、对照设备和 Android 9 实体机证据齐全。

无法稳定执行一次安全返回，或允许流程误阻止不可控，应判定 No-Go。最终结论填写在 `go-no-go.md`，由技术与 QA 共同签署。

## 7. 当前已知边界

- 当前主设备已完成记录模式延迟真值校准、15 个混合负样本和桌面断路探针；真实 Back/Home、武装允许流程、手动样本和完整负样本尚未执行；
- Redmi 稳定节奏已经验证，但 MIUI Greeze 会在短间隔连续拉起时造成数十秒事件延迟，仍需定义可接受产品边界和缓解策略；
- 对照设备、Android 9 实体机、长时间待机与电量结果尚未采集；
- S0 只证明受控包之间的公开 API 能力，不证明能获得原始 Intent 或权威调用链；
- UsageStats 使用墙上时钟，已映射到单调时钟；系统时钟跳变超过 5 秒会清空来源上下文；
- 无障碍事件时间是 uptime，代码映射到 elapsed realtime 后再与 UsageStats 合并；
- `performGlobalAction()` 的布尔返回只表示动作已分派，最终成功必须由后续前台状态确认；
- S0 不读取窗口文本、不遍历节点树、不执行 Shell、不处理测试包之外的目标。
