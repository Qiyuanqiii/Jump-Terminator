# S0.3 Shizuku 生命周期门槛决策

日期：2026-08-03

设备：Redmi `23078RKD5C` / Android 13 / MIUI 14

当前决策：**`LIFECYCLE_GATE_PASSED`**

## 决策摘要

- v2 首轮样本发现 force-stop 后 shell 伴侣仍发送 1 次 Back，决策为 `STOP_UNTIL_FORCE_STOP_FAIL_SAFE`；
- v3 将监控会话绑定到普通控制进程 Binder，并在 owner 死亡及每次动作前复核对应用户下的包 stopped 状态；
- v3 force-stop 样本记录 `owner_package_stopped`，伴侣 PID 归零，后续跳转 Back 为 0；
- 普通 UI 崩溃只保留 10 秒宽限，本次在宽限内完成 1/1 次受控动作后请求退出；
- Shizuku 正常结束和强制断连均安全放行，后续 Back 为 0；
- 断连恢复、重启冷启动及解锁后显式恢复全部通过；
- 七类场景的证据门、安全门、恢复门和总门均通过；
- v3 额外完成正样本 100 次与允许流程 15 次回归，性能门仍为 `SHIZUKU_POC_FEASIBLE`。

因此，force-stop 硬阻塞已经解除，允许继续下一阶段 Advanced 架构与安全协议验证。本决策仍不是消费者发布 Go。

## 门槛结果

| 门槛 | 要求 | v3 结果 | 判定 |
| --- | --- | --- | --- |
| 场景证据覆盖 | 7 类全部有效 | 7/7 | 通过 |
| UI 崩溃韧性 | 仅在有限宽限内工作并退出 | 1/1；退出请求 1 | 通过 |
| force-stop 撤权 | 原因可解释、伴侣停止 | `owner_package_stopped`；PID 0 | 通过 |
| force-stop 后动作 | Back 0 | 0 | 通过 |
| Shizuku 正常结束降级 | Back 0 | 0 | 通过 |
| Shizuku 强制断连降级 | Back 0 | 0 | 通过 |
| 断连恢复 | 授权、绑定、动作恢复 | 1/1 | 通过 |
| 重启冷启动 | 不自动启动特权或测试进程 | 全部 PID 0 | 通过 |
| 重启后显式恢复 | 解锁后授权、绑定、动作恢复 | 1/1 | 通过 |
| 服务错误、超时、运行器错误 | 0 | 0 | 通过 |
| 每场景最终清理 | 特权与测试进程 PID 均为 0 | 7/7 | 通过 |

## 已实现的安全属性

- 监控调用必须携带 owner Binder token 和完整应用 UID；
- owner 死亡会触发 per-user stopped 状态检查；
- force-stop 或状态未知立即撤权、停止工作线程并退出；
- 普通崩溃最多保留 10 秒宽限，不产生永久孤儿伴侣；
- 每次 Back 前重新验证 stopped 状态和当前会话；
- Shizuku 断连与手机重启不隐式恢复武装；
- UserService 实现官方 destroy 事务并最终调用 `System.exit(0)`。

[Shizuku API UserService 文档](https://github.com/RikkaApps/Shizuku-API#userservice)明确说明 UserService 运行在独立 root/shell 进程，停止绑定不会自动杀死服务进程，因此这些生命周期属性必须由应用协议实现。

## 授权范围

允许继续：

- 设计 Advanced 的最小签名协议、规则快照和动作前二次验证；
- 扩大 force-stop、崩溃、锁屏、竞态及负样本；
- 验证多用户、工作资料、双开和其他 OEM；
- 对固定测试包继续进行非持久 L1 故障注入。

仍不允许：

- 接入真实第三方应用控制；
- 开始 force-stop、suspend、disable 等 L3-L5 产品能力；
- 将 PoC 描述为消费者版 Go 或可发布状态；
- 依赖无法解析的包状态继续动作。

## 剩余风险

- 证据只来自一台 MIUI 14 / Android 13 设备；
- stopped 状态读取依赖 shell 权限和 OEM `dumpsys package` 输出，其他平台尚未验证；
- 多用户与工作资料只进入了协议字段，尚无实体样本；
- 普通崩溃的 10 秒宽限仍需竞态、重复目标与锁屏测试；
- 允许流程只有 0/15，统计量不足以证明发布级 `≤2%` 误动作率；
- 所有动作仍是固定测试来源到固定测试目标，不能外推到真实应用。

## 证据

- [v3 生命周期通过报告](results/miui14-23078rkd5c-s03-lifecycle-v003-owner-bound-20260803.report.json)
- [v2 失败基线](results/miui14-23078rkd5c-s03-lifecycle-20260803.report.json)
- [运行、协议与复现手册](README.md)
- [v3 S0.2 性能报告](../s02/results/miui14-23078rkd5c-s02-shizuku-v003-owner-bound-block100-allow15-20260803.report.json)
- [S0.2 原始可行性决策](../s02/decision.md)
