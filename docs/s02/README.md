# S0.2 特权伴侣可行性验证

状态：**完成，结论为 `SHIZUKU_POC_FEASIBLE`**

设备：Redmi `23078RKD5C` / `corot`，Android 13，MIUI 14

执行日期：2026-08-03

## 1. 为什么有 S0.2

S0 已证明普通消费者 App 即使获得无障碍、UsageStats、前台服务、电池无限制和自启动，仍会被 MIUI Greeze 冻结。正式 100 次中只有 `92/100` 能实时收到目标事件，因此 Standard 架构维持 No-Go。

S0.2 不再尝试给普通进程叠加后台豁免，而是回答一个更窄的问题：

> 如果检测与动作运行在 Android `shell` 身份的独立伴侣进程中，固定测试跳转能否稳定地被发现并以一次 Back 撤销？

## 2. 结论

| 执行面 | 固定目标检测 | Back | 离开并返回来源 | 允许流程误动作 | 决策 |
| --- | ---: | ---: | ---: | ---: | --- |
| 普通 App / 公开 API（S0） | 92/100 实时 | 92/100 | 92/92 | 0/15 | No-Go |
| ADB/shell 上界 | 100/100 | 100/100 | 100/100 | 0/15 | 可进入 Shizuku PoC |
| Kotlin + Shizuku UserService | 100/100 | 100/100 | 100/100 | 0/15 | `SHIZUKU_POC_FEASIBLE` |

Shizuku 正式样本的 Wilson 95% 下界为 96.30%（100/100 指标）；延迟均为从最后一次观察到来源开始计算的保守上界：

| 指标 | P50 | P95 |
| --- | ---: | ---: |
| 目标检测 | 59 ms | 125 ms |
| Back 请求 | 59 ms | 125 ms |
| 离开目标 | 167 ms | 214 ms |
| `input keyevent 4` 执行 | 48 ms | 70 ms |
| 单次前台轮询 | 25 ms | 38 ms |

15 个负样本全部保持允许且未出现 Back。需要注意，`0/15` 的 Wilson 95% 上界仍为 20.39%，所以它只是当前安全门的冒烟样本，不足以证明发布级 `≤2%` 误拦截率；零失败时至少需要 189 个负样本才能把该上界压到 2% 以下。

## 3. 实现边界

实验链路为：

`测试控制 UI（普通应用 UID） → Shizuku Binder → Kotlin UserService（shell UID 2000） → dumpsys activity / input keyevent 4`

UserService 只接受以下硬编码边界：

- 来源必须是 `com.jumpterminator.testsource/.SourceActivity`；
- 目标必须是 `com.jumpterminator.testtarget/.TargetActivity`；
- 正样本批量只允许 1、10 或 100；
- 负样本最多 60 个，并且必须处于武装模式；
- 每个来源到目标序列至多发送一次 Back；
- 短暂无法解析前台时记为 `unknown`，不得据此清除来源上下文或执行动作；
- UserService 不发送 Home，不执行 force-stop、suspend、disable，也不修改持久系统状态；
- 普通 S0 App 必须保持未武装，避免两个执行面同时动作；
- 设备所有者、Root 和恢复出厂设置均不在本实验范围。

原始 JSONL 和逐次临时报告默认被 `.gitignore` 排除，只提交不含应用内容或屏幕文本的聚合统计。

## 4. 代码与复现

构建全部实验模块：

```powershell
.\scripts\s0-build.ps1
```

安装原型 APK：

```powershell
adb install -r .\s02-shizuku-poc\build\outputs\apk\debug\s02-shizuku-poc-debug.apk
```

Shizuku 必须从[官方 Release](https://github.com/RikkaApps/Shizuku/releases/tag/v13.6.0)安装并按[官方启动指南](https://shizuku.rikka.app/guide/setup/)启动；授权必须经过手机上可见的 Shizuku 对话框。本次验证的管理器包为 `13.6.0.r1086.2650830c`，运行页显示服务版本 `13.5 (adb)`，原型依赖 Shizuku API `13.1.5`。本地下载 APK 的 SHA-256 为 `6E273AB0E991C4E79BC8B1BBB9B9DD739CCAC1A8712A541A214078886B7B790F`，签名证书 SHA-256 为 `268B5590E868FB08BAE7E0AC413564CD1FF88F5CCFF74AF9DBD0DC918E30DB30`。

授权并连接后，按小样本到正式样本执行：

```powershell
.\scripts\s02-shizuku-run.ps1 -Scenario block -BatchCount 1 -Arm
.\scripts\s02-shizuku-run.ps1 -Scenario block -BatchCount 10 -Arm
.\scripts\s02-shizuku-run.ps1 -Scenario allowed-negative -AllowedRepeats 5 -Arm
.\scripts\s02-shizuku-run.ps1 -Scenario block -BatchCount 100 -Arm -TimeoutSeconds 900
```

ADB/shell 上界脚本默认只观察；只有显式传入 `-Arm` 才会发送 Back：

```powershell
.\scripts\s02-adb-companion.ps1 -Scenario block -BatchCount 10 -Arm
```

统计与严格门槛：

```powershell
python .\scripts\s02_report.py <block.jsonl> <allowed.jsonl> --output <aggregate.report.json> --strict
python -m unittest scripts.test_s02_report -v
```

## 5. 可公开证据

- [ADB/shell 上界聚合报告](results/miui14-23078rkd5c-s02-adb-privileged-upper-bound-block100-allow15-20260803.report.json)
- [Kotlin + Shizuku 聚合报告](results/miui14-23078rkd5c-s02-shizuku-block100-allow15-20260803.report.json)
- [S0.2 门槛决策](decision.md)
- [S0 原架构 No-Go](../s0/go-no-go.md)

## 6. 下一道门

`SHIZUKU_POC_FEASIBLE` 只授权 Advanced 架构设计与继续验证。进入真实实现前至少还需：

1. 明确 Standard 与 Advanced 的产品承诺、安装渠道和降级提示；
2. 验证 UI 进程被杀、锁屏/息屏、重启、Shizuku 断连和重新授权；
3. 将允许流程负样本扩到发布级统计规模，并覆盖支付、安装器、系统设置、浏览器和桌面；
4. 验证多用户、双开、分屏、PiP 和设备锁定状态；
5. 把测试包硬编码边界替换为经过签名、用户身份、规则和当前前台二次校验的最小协议；
6. 在任何 L3-L5 工作之前单独完成恢复账本、断连与故障注入门槛。

在这些条件完成前，README 不得把结果描述为消费者版 Go 或可发布状态。
