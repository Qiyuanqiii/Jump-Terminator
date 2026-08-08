# Security Hardening Review: Jump Terminator privileged authorization

## Evidence Basis

我们以提交 `07a7be2` 的 S0.2/S0.3 特权伴侣源码、v2 force-stop 失败报告和 owner-bound v3 通过报告为边界。我检查了 AIDL、控制端、授权状态机和最终 `input` 启动路径；证据清单及摘要固定在 [context.md](context.md)。这不是仓库级安全扫描，结论不外推到尚未实现的消费者产品。

## Constraints

当前采用平衡型约束：保留固定测试包、Shizuku UserService、非持久 Back 动作和现有自动化脚本；不引入网络、Root、Device Owner 或 L3-L5 能力。我们没有发布级延迟和内存预算，因此所有未重新测量的影响均视为待验证。

## Opportunity Portfolio

| Opportunity | Evidence | Options | Recommendation | Proposal |
| --- | --- | --- | --- | --- |
| 集中特权会话身份、能力值与最终动作授权 | v2/v3 生命周期报告及 AIDL、状态机、动作边界（`E001`–`E006`） | 1. 加强 v3 局部检查；2. 服务端派生身份与一次性能力；3. 独立签名授权代理 | 当前固定测试 PoC 采用方案 2；真实动态规则出现时重新评估方案 3 | [完整提案](proposals/privileged-authorization-boundary.md) |

## Recommendation Summary

v3 已经证明 owner Binder、stopped 复核和确定性退出可以修复已观察到的 force-stop 失败。剩余控制仍分散：客户端声明 UID，状态机没有独立重放记录或会话租约，授权检查与进程启动分属两个步骤。我们可以保留 v3 的有效保护，同时把身份派生、能力消费、租约和最终启动串行化收进一个服务端边界。

我建议在当前固定测试范围选择方案 2。它不增加新进程或持久密钥，迁移面可控，也为将来的签名规则快照留下明确接口。方案 3 在真实规则可由多个 UI、自动化入口或恢复流程创建时更有吸引力；现在引入会增加 Keystore、恢复和可用性负担，却不能替代当前路径的直接修复。

## Implementation Outcome

方案 2 已在 `0.0.4-s04` 实施，并于 2026-08-08 在 Redmi `23078RKD5C` / Android 13 / MIUI 14 重新验证。Binder owner UID 与控制包 UID 一致，签名解析成功；正式 100+15 样本的安全与性能门通过，Back P95 为 `158 ms`；S0.3 七类生命周期门和六个非重启会话的 S0.4 身份证据门全部通过。详见 [S0.4 决策](../decision.md)、[授权报告](../results/miui14-23078rkd5c-s04-authorization-v004-20260808.report.json)和[生命周期报告](../results/miui14-23078rkd5c-s04-lifecycle-v004-20260808.report.json)。

该结果是目标设备和固定测试组件上的观察事实。跨 UserService 重启重放、多用户和系统级 check/start 外部竞态仍属于剩余风险，不能标记为已解决。

## Next Decisions

- 真实规则接入前收口或移除外部测试 Intent；
- 为多用户、工作资料和双开定义 owner 包与签名归属；
- 决定是否需要跨 UserService 重启的持久重放防护；
- 在真实应用或动态规则接入前，重新决定是否升级为独立签名授权代理。
