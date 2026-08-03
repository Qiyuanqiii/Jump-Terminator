# S0.3 Shizuku 生命周期与故障注入验证

状态：**完成，结论为 `STOP_UNTIL_FORCE_STOP_FAIL_SAFE`**

设备：Redmi `23078RKD5C` / `corot`，Android 13，MIUI 14

执行日期：2026-08-03

## 1. 验证目标

S0.2 已证明 Kotlin + Shizuku UserService 能在固定测试边界内稳定完成检测与一次 Back。S0.3 不再重复性能样本，而是验证特权伴侣在以下状态变化中是否安全：

- 普通 UI 进程崩溃；
- 用户或系统显式 force-stop 应用包；
- Shizuku 服务正常结束或被强制断开；
- Shizuku 重新启动后的授权、绑定和动作恢复；
- 手机重启时的冷启动状态；
- 手机重启并解锁后的显式恢复。

所有动作仍仅限 `com.jumpterminator.testsource/.SourceActivity` 到 `com.jumpterminator.testtarget/.TargetActivity`，每次会话最多一次 Back。普通 S0 观察器在测试前必须保持未武装。

## 2. 结论

七类必测场景均取得有效证据，六类通过，安全门因 force-stop 场景失败：

| 场景 | 故障注入与观察 | 结果 | 判定 |
| --- | --- | --- | --- |
| UI 进程崩溃 | `am crash` 后 UI PID `9435 → 0`，Shizuku 与伴侣存活 | 受控跳转检测、Back、离开目标、返回来源均 `1/1` | 通过韧性观察 |
| UI 包 force-stop | UI PID `10290 → 0`，伴侣 PID `10359` 仍存活 | force-stop 后仍检测并发送 Back `1/1` | **硬失败** |
| Shizuku 正常结束 | 服务 PID `11592 → 0`，伴侣 PID `11739 → 0` | 后续测试跳转发生，Back `0` | 通过，安全放行 |
| Shizuku 强制断连 | 服务 PID `12333 → 0`，伴侣 PID `12416 → 0` | 后续测试跳转发生，Back `0` | 通过，安全放行 |
| 断连后恢复 | 重新启动服务并绑定伴侣 | 检测、Back、离开目标、返回来源均 `1/1` | 通过 |
| 手机重启 | boot ID 改变；启动完成时设备仍锁定 | Shizuku 服务、伴侣、测试 UI、来源和目标 PID 均为 `0` | 通过，冷启动安全 |
| 重启后恢复 | 解锁后显式启动服务与探针 | 既有授权可用，检测与动作链 `1/1`，错误和超时均为 `0` | 通过 |

机器汇总结果：

- 证据覆盖门：`7/7`，通过；
- Shizuku 失联安全门：通过；
- 冷启动安全门：通过；
- 断连与重启后恢复门：通过；
- force-stop 失效安全门：失败；
- 总安全门：失败；
- 决策：`STOP_UNTIL_FORCE_STOP_FAIL_SAFE`。

这不会推翻 S0.2 的“特权执行面性能可行”结论，但会阻止它进入真实应用控制、完整 Advanced 实现或消费者发布。

## 3. 为什么 force-stop 是硬失败

普通 UI 崩溃和显式 force-stop 不能按同一产品语义处理：

- UI 崩溃后的短时连续工作可以是韧性能力，但必须有明确、有限的授权租约；
- force-stop 是一个明确的停止边界。应用包被停止后，特权伴侣不得继续依据旧的武装状态操作其他应用；
- 本次 force-stop 后，普通 UI 已消失，但 shell UID 的 UserService 仍持有旧会话并完成了一次 Back，因此旧授权已经越过应用的停止边界。

这与 Shizuku 的进程模型一致，不是 Shizuku 自身缺陷。[Shizuku API 的 UserService 文档](https://github.com/RikkaApps/Shizuku-API#userservice)说明 UserService 在独立的 root/shell 进程中运行，`unbindUserService` 不会自动杀死该进程，服务实现需要提供 destroy 事务并自行清理、退出。因此，生命周期所有权必须由 Jump Terminator 的协议显式实现，不能假设 Android 会替普通应用自动回收 shell 伴侣。

在重新通过安全门之前，至少需要设计并验证：

1. 每次动作前检查短时、单调时钟驱动、不可重放的授权租约；
2. 控制端 Binder 死亡或租约过期后原子解除武装，拒绝新动作；
3. UserService 支持官方 destroy 事务并可确定性退出；
4. 应用被 force-stop 后，伴侣必须退出或保持可证明的无动作状态；
5. Shizuku 或手机重启后默认不隐式恢复武装，必须由用户可见流程重新启用；
6. 用多次、延时和竞态故障注入证明 force-stop 后 Back 始终为 `0`。

若架构无法可靠区分普通崩溃与显式 force-stop，应选择安全优先：控制端死亡即解除武装，而不是保留无界后台动作能力。

## 4. 复现

前置条件：安装项目四个测试 APK 与官方 Shizuku；手机通过 ADB 连接；除 `reboot` 外运行前均已解锁；Shizuku 权限已经通过手机上的可见对话框授予。Shizuku 的启动方式见[官方用户手册](https://shizuku.rikka.app/guide/setup/)。

逐场景执行：

```powershell
.\scripts\s03-lifecycle.ps1 -Scenario ui-kill
.\scripts\s03-lifecycle.ps1 -Scenario ui-force-stop
.\scripts\s03-lifecycle.ps1 -Scenario shizuku-graceful-stop
.\scripts\s03-lifecycle.ps1 -Scenario shizuku-disconnect
.\scripts\s03-lifecycle.ps1 -Scenario disconnect-recovery
.\scripts\s03-lifecycle.ps1 -Scenario reboot
# 手机启动完成后先解锁
.\scripts\s03-lifecycle.ps1 -Scenario post-reboot-recovery
```

脚本在每个非重启场景启动一个至多执行一次动作的 S0.2 伴侣会话，按精确进程名注入故障，记录 PID、boot ID、锁屏状态和动作摘要，并在 finally 阶段停止特权服务、伴侣与测试应用后回到桌面。force-stop 和两种 Shizuku 失联场景使用固定 4 秒无动作观察窗口，不要求伴侣进程必须死亡；正常停止场景只发送 TERM，未停止即记为失败，不会静默升级成强杀。若设备处于锁定状态，交互场景会直接拒绝运行。

聚合选定的七份有效时间线：

```powershell
$inputs = @(
  '.\docs\s03\results\s03-ui-kill-20260803-165751.jsonl',
  '.\docs\s03\results\s03-ui-force-stop-20260803-165834.jsonl',
  '.\docs\s03\results\s03-shizuku-graceful-stop-20260803-170027.jsonl',
  '.\docs\s03\results\s03-shizuku-disconnect-20260803-170123.jsonl',
  '.\docs\s03\results\s03-disconnect-recovery-20260803-170216.jsonl',
  '.\docs\s03\results\s03-reboot-20260803-170257.jsonl',
  '.\docs\s03\results\s03-post-reboot-recovery-20260803-170807.jsonl'
)
python .\scripts\s03_lifecycle_report.py @inputs --output .\docs\s03\results\miui14-23078rkd5c-s03-lifecycle-20260803.report.json
python -m unittest scripts.test_s03_lifecycle_report -v
```

`--strict` 只有在机器决策为 `LIFECYCLE_GATE_PASSED` 时返回 0；本次证据会按设计返回 2。原始 JSONL 默认由 `.gitignore` 保留在本机，公开仓库只提交聚合报告及每份输入的 SHA-256。

## 5. 证据与授权边界

- [S0.3 聚合报告](results/miui14-23078rkd5c-s03-lifecycle-20260803.report.json)
- [S0.3 门槛决策](decision.md)
- [S0.2 性能与安全边界](../s02/README.md)
- [S0 原架构 No-Go](../s0/go-no-go.md)

当前只允许修订生命周期协议、实现最小失效安全机制并复测 S0.3。不得据此控制真实第三方包，不得开始 L3-L5 持久动作，也不得把项目状态描述为可发布。
