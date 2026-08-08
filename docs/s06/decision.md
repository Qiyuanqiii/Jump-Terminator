# S0.6 韧性压力与权限撤销决策

状态：**通过，决策为 `S06_RESILIENCE_STRESS_PASSED`**

设备：Redmi `23078RKD5C` / Android 13 / MIUI 14

版本：`0.0.6-s06` / UserService v5

日期：2026-08-08

## 决策

允许继续下一项 Advanced S0 架构与安全验证。理由是本阶段要求的 5 次普通 UI 崩溃、10 次固定目标重复动作和 3 次平台权限撤销/恢复均完成，样本门与安全门同时通过；撤权时没有新特权会话，恢复后合法连接恰好恢复一次。

此决策不改变 Standard S0 No-Go，不授权消费者发布、真实第三方目标或 L3-L5 持久动作。

## 修复判定

原可复现路径为：Android 运行时 Shizuku 权限已撤销，但 Shizuku 的正向授权缓存仍使 `0.0.5-s05` 创建新的 UserService 会话。失败样例记录 `granted=false` 与同一周期 `readyCount=1`。

采用的窄修复只改变 POC 客户端的连接前置条件：平台运行时授权和 Shizuku 授权视图必须同时为真。没有修改固定来源/目标、Binder owner 身份、一次性能力、规则快照、租约、UserService v5 或动作执行逻辑。

修复后原样例不再复现：3 个撤权会话全部 `ready=0`；合法行为保持：3 个恢复会话全部恰好 `ready=1`，重复目标 `10/10`，普通 UI 崩溃 `5/5` 收尾并退出。

## 验收证据

| 属性 | 结果 | 判定 |
| --- | --- | --- |
| 崩溃压力 | 5 个会话全部通过生命周期、owner 脱离与服务退出门 | 通过 |
| 重复动作 | 检测、Back、离开、返回均 `10/10` | 通过 |
| 撤权 fail-closed | 3 次 `granted=false`，特权 `ready=0` | 通过 |
| 重授权恢复 | 3 次 `granted=true`，特权 `ready=1` | 通过 |
| 授权不变量 | Binder UID、签名、能力、规则快照、租约和最终串行化全部成立 | 通过 |
| 安全与完整性 | 安全违规、超时、失败事件、报告警告均为 0；源证据带 SHA-256 | 通过 |
| 自动化 | Android `52` 项、Python `35` 项、完整 build/lint | 通过 |

正式证据见 [S0.6 聚合报告](results/miui14-23078rkd5c-s06-resilience-v006-20260808/s06-resilience.report.json)，原问题见[修复前失败样本](results/miui14-23078rkd5c-s06-resilience-v006-20260808/s06-reauthorization-v005-pre-fix-failing.jsonl)。

## no-change 复核

对 AIDL 空闲方法的跨应用可达性怀疑未形成有效攻击路径：Shizuku 在交付 UserService Binder 前验证调用包与组件包，其他包不能取得该 Binder；`destroy` 还必须接受 Shizuku 服务端的生命周期事务。对此不修改代码，避免破坏合法销毁与版本替换。

## 剩余不确定性

- ADB `pm revoke/grant` 验证平台授权与 Shizuku 缓存分歧下的 fail-closed，不等同于 Shizuku Manager UI 流程验收；
- 单设备、固定测试包、debug 构建和 L1 Back 仍是硬边界；
- 锁屏/最近任务/多窗口重复压力、多用户/工作资料、其他 OEM、并发与内存压力尚未覆盖；
- 跨 UserService 重启的重放状态和更广泛 Binder 面仍需后续独立安全验证。
