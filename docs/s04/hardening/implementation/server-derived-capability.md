# Implementation Plan: 服务端派生身份与一次性能力

状态：**已实施并在固定测试边界验收通过（2026-08-08）**

## Completion Record

- AIDL/UserService 已升级到 v4，owner UID 不再来自客户端字段；
- Binder UID、固定包映射和当前签名解析已在实体机确认；
- session/capability 重放、租约、未知状态、旧 death 回调和撤权竞态已有纯单元测试；
- 最终状态复核与 `ProcessBuilder.start()` 已进入同一授权锁；
- 完整 Gradle build/lint、Android `46` 项和 Python `24` 项测试通过；
- 正样本与允许流为 `100/100`、`0/15`，Back P95 `158 ms`；
- 七类生命周期矩阵及 S0.4 身份证据门通过。

验收依据见 [S0.4 决策](../../decision.md)、[授权报告](../../results/miui14-23078rkd5c-s04-authorization-v004-20260808.report.json)与[生命周期报告](../../results/miui14-23078rkd5c-s04-lifecycle-v004-20260808.report.json)。

## Selected Design And Constraints

选择 `server-derived-capability`。我们保留 S0.3 的 owner Binder、per-user stopped 检查、10 秒崩溃宽限和确定性退出；新增控制仅覆盖固定测试来源、固定测试目标和非持久 Back。

## Source Revision And Drift Check

设计基线为 `07a7be25bbbe3ce68778748066c5cdbbd01add6e`，分析开始时工作树与该提交一致。实施前未发现相关源码漂移；实施变更将作为该基线的直接后继进行验证。

## Affected Components

- `IPrivilegedCompanion.aidl`
- `MainActivity.kt`
- `PrivilegedCompanionService.kt`
- `OwnerAuthorizationPolicy.kt`
- 新增服务端身份解析与规则快照类型
- S0.2/S0.3 报告工具、单元测试和 S0.4 文档

## Ordered Work Packages

1. 将 AIDL 升级为 v4：删除客户端 `ownerUid`，加入内部生成的 256 位能力值；UserService 版本同步升级。
2. 使用 `Binder.getCallingUid()`、UserService `Context`、`PackageManager.getPackagesForUid()` 与当前签名证书派生 owner 身份；任何未知状态失败关闭。
3. 扩展授权状态机：一次性消费 session ID 和能力值，生成不可变规则快照哈希与服务端单调租约。
4. 将最终 stopped 查询、授权判定和 `ProcessBuilder.start()` 放入同一进程内串行化边界；保留系统外部竞态的明确线性化语义。
5. 为身份不匹配、签名缺失、重放、租约过期、旧会话死亡和撤权竞态补充纯单元测试。
6. 构建、lint 后先执行单次实体机身份探针，再重跑 force-stop、断连、重启和 100+15 性能回归。

## Compatibility And Migration

UserService 参数版本升到 4，使 Shizuku 调用官方 destroy 事务清理旧 v3 进程。S0.2/S0.3 自动化仍通过同一 Activity extras 启动；能力值由应用进程内部生成，不接受 Intent 输入。Shizuku v13 的 Context 构造器是本阶段前置条件。

## Tactical Protections During Migration

- 继续固定来源与目标组件；
- 继续限制批量为 1、10、100，允许流最多 60；
- 继续在每次 Back 前检查 stopped；
- 状态未知、身份未知或签名未知均不执行动作；
- Standard S0 保持未武装。

## Tests And Security Validation

- UID 必须由 Binder 调用上下文派生；
- UID 不包含固定 owner 包时拒绝；
- 当前签名证书无法解析时拒绝；
- session ID 或能力值重复时拒绝；
- 单调租约到期时拒绝；
- owner death、force-stop、状态未知和旧会话回调不得越权；
- 撤权在线性化点先发生时，动作启动计数必须为 0；
- 原 S0.3 七类场景继续通过。

## Performance And Resource Benchmarks

以 v3 的检测/Back/离开 P95 `116/139/211 ms` 为基线。实体机重新测量 100 次正样本和 15 次允许流；记录 PackageManager 身份解析只发生在会话开始，动作路径新增锁内 stopped 查询不得产生超时或重复动作。若 Back P95 明显超过现有 250 ms 产品门，停止进入下一阶段并分析。

## Rollout And Rollback

本阶段只发布调试 APK 和固定测试证据。回滚时恢复 UserService v3、AIDL v3 和对应报告逻辑；不得在 v4 失败时通过接受客户端 UID 或跳过身份/签名检查来兼容。

## Acceptance Criteria

- 服务端事件证明 owner UID 来源为 Binder，包名与签名已解析；
- session 与能力重放测试全部拒绝；
- 租约和撤权后动作启动为 0；
- S0.3 七类生命周期门仍为 `LIFECYCLE_GATE_PASSED`；
- 正样本与允许流门仍为 `SHIZUKU_POC_FEASIBLE`；
- 构建、lint、Android 单元测试和 Python 报告测试全部通过。

## Open Decisions

- 真正规则入口是否需要 Keystore 签名授权代理；
- 多用户、工作资料和双开环境中的包/签名映射策略；
- Android 系统层无法与 `input` 合并为单一事务的外部竞态应采用何种发布级风险限额。
