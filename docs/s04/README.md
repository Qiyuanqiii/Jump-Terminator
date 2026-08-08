# S0.4 最小授权协议与竞态安全验证

状态：**完成，结论为 `S04_AUTHORIZATION_GATE_PASSED`；S0.3 生命周期门保持通过**

基线提交：`07a7be25bbbe3ce68778748066c5cdbbd01add6e`

S0.4 在 S0.3 已通过的 owner Binder 与 force-stop 撤权机制上继续收紧特权动作授权。它只处理固定测试来源、固定测试目标和一次 Back，不扩大到真实第三方应用或持久系统动作。

设备：Redmi `23078RKD5C` / `corot`，Android 13，MIUI 14

执行日期：2026-08-08

实现版本：`0.0.4-s04` / UserService v4

## 本阶段目标

- UserService 从 Binder 调用上下文派生调用方 UID，不接受客户端声明的 UID；
- 调用方 UID 必须映射到固定控制包，并解析当前安装签名；
- 每个监控会话使用进程内生成、不可记录明文的随机能力值；
- 会话 ID 与能力值在 UserService 进程生命周期内只能消费一次；
- 服务端生成不可变规则快照和单调时钟租约；
- 最终包状态复核与 `input keyevent 4` 启动共享同一授权串行化边界；
- 旧会话、重放、过期、身份不匹配、状态未知和撤权后的动作全部失败关闭。

## 交付物

- [安全加固方案集](hardening/hardening.md)
- [结构化方案](hardening/hardening.json)
- [选定方案实施计划](hardening/implementation/server-derived-capability.md)
- [完整技术提案](hardening/proposals/privileged-authorization-boundary.md)
- [S0.4 最终决策](decision.md)
- [授权与性能聚合报告](results/miui14-23078rkd5c-s04-authorization-v004-20260808.report.json)
- [生命周期聚合报告](results/miui14-23078rkd5c-s04-lifecycle-v004-20260808.report.json)

## 最终结果

| 门禁 | 结果 |
| --- | --- |
| 服务端身份 | Binder UID `10418` 与运行时包 UID 一致；固定包为 `com.jumpterminator.s02`；当前签名 SHA-256 已解析 |
| 能力与规则 | 两个正式会话能力指纹唯一，规则快照唯一，公开事件无能力明文 |
| 正样本 | 检测、Back、离开目标、返回来源均 `100/100` |
| 允许流程 | 误动作 `0/15`，允许流程保留 `15/15` |
| 延迟 P95 | 检测 `116 ms`，Back `158 ms`，离开目标 `233 ms` |
| 生命周期 | 七类场景 `7/7` 通过；六个非重启会话的 S0.4 身份门全部通过 |
| 自动化 | Android 单元测试 `46` 项、Python 报告测试 `24` 项全部通过；完整 Gradle build/lint 通过 |

机器报告给出：

- `securityGatePassed=true`；
- `performanceGatePassed=true`；
- `s04AuthorizationGatePassed=true`；
- `provisionalDecision=S04_AUTHORIZATION_GATE_PASSED`；
- `provisionalDecision=LIFECYCLE_GATE_PASSED`（生命周期报告）。

## 复现

手机需已解锁、通过 USB 连接，Shizuku 已启动且控制包权限已授予。正式正负样本：

```powershell
.\scripts\s02-shizuku-run.ps1 -Scenario block -BatchCount 100 -Arm
.\scripts\s02-shizuku-run.ps1 -Scenario allowed-negative -AllowedRepeats 5 -Arm
python .\scripts\s04_authorization_report.py <block.jsonl> <allow.jsonl> --output <report.json> --strict
```

生命周期命令与 S0.3 相同；聚合时使用 `scripts/s03_lifecycle_report.py --strict`。S0.2/S0.4 运行器现在会在锁屏时提前拒绝，避免把不可交互状态误判为协议失败。

## 当前授权边界

S0.4 只证明固定控制包、固定测试来源、固定测试目标和非持久 Back 的本地授权边界。重放集合只覆盖单个 UserService 进程；Android 的 package stopped 变化与 `input` 启动不能合并成系统事务；外部命令 Intent 仍是测试入口；多用户、工作资料、双开、其他 OEM 和真实第三方应用均未验证。

因此 Standard S0 仍为 No-Go；本阶段通过只授权继续 Advanced 架构与安全验证，不等于消费者版 Go。
