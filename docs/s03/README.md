# S0.3 Shizuku 生命周期与故障注入验证

状态：**完成，owner-bound v3 结论为 `LIFECYCLE_GATE_PASSED`**

设备：Redmi `23078RKD5C` / `corot`，Android 13，MIUI 14

执行日期：2026-08-03

## 1. 验证目标

S0.2 已证明 Kotlin + Shizuku UserService 能在固定测试边界内稳定完成检测与一次 Back。S0.3 验证特权伴侣在以下状态变化中是否安全：

- 普通 UI 进程崩溃；
- 用户或系统显式 force-stop 应用包；
- Shizuku 服务正常结束或被强制断开；
- Shizuku 重新启动后的授权、绑定和动作恢复；
- 手机重启时的冷启动状态；
- 手机重启并解锁后的显式恢复。

所有动作仍仅限 `com.jumpterminator.testsource/.SourceActivity` 到 `com.jumpterminator.testtarget/.TargetActivity`，每次生命周期会话最多一次 Back。普通 S0 观察器在测试前必须保持未武装。

## 2. 最终结论

首次 v2 验证发现 force-stop 后旧 UserService 仍可动作，机器决策为 `STOP_UNTIL_FORCE_STOP_FAIL_SAFE`。加入所有权与撤权协议的 `0.0.3-s03` 重新执行全部七类场景后，结果如下：

| 场景 | v3 故障注入与观察 | 动作结果 | 判定 |
| --- | --- | --- | --- |
| UI 进程崩溃 | UI PID `13107 → 0`；伴侣在故障快照仍为 `13156` | 10 秒宽限内完成检测、Back、离开与返回 `1/1`，随后请求退出 | 通过，有界韧性 |
| UI 包 force-stop | UI PID `14099 → 0`；伴侣 PID `14147 → 0`；原因 `owner_package_stopped` | 后续测试跳转 Back `0` | 通过，立即撤权 |
| Shizuku 正常结束 | 服务 PID `14514 → 0`，伴侣 PID `14579 → 0` | 后续测试跳转 Back `0` | 通过，安全放行 |
| Shizuku 强制断连 | 服务 PID `14961 → 0`，伴侣 PID `15026 → 0` | 后续测试跳转 Back `0` | 通过，安全放行 |
| 断连后恢复 | 重新启动服务并绑定伴侣 | 检测、Back、离开、返回均 `1/1` | 通过 |
| 手机重启 | boot ID 改变；启动完成时设备锁定 | Shizuku、伴侣、UI、来源和目标 PID 均为 `0` | 通过，冷启动安全 |
| 重启后恢复 | 解锁后显式启动服务与 owner-bound 探针 | 检测、Back、离开、返回均 `1/1`，错误和超时为 `0` | 通过 |

新版机器报告为 `s0.3-report-2`：

- 证据覆盖门：`7/7`，通过；
- force-stop 失效安全门：通过；
- Shizuku 失联安全门：通过；
- 冷启动安全门：通过；
- UI 崩溃韧性门：通过；
- 断连与重启恢复门：通过；
- 总安全门：通过；
- 决策：`LIFECYCLE_GATE_PASSED`。

## 3. 修复协议

v2 的根因不是 Shizuku 错误，而是 Jump Terminator 没有把普通控制进程的生命周期绑定到 shell UserService 的动作授权。[Shizuku API 的 UserService 文档](https://github.com/RikkaApps/Shizuku-API#userservice)说明 UserService 在独立 root/shell 进程中运行，`unbindUserService` 不会自动杀死进程，服务实现必须提供 destroy 事务并自行退出。

v3 实现以下最小协议：

1. `startMonitor` 必须接收控制进程创建的 Binder owner token 与 `Process.myUid()`；
2. UserService 对 owner token 注册 death recipient，并把完整 UID 映射到对应 Android 用户；
3. owner 死亡后读取固定控制包在该用户下的 `stopped` 状态；
4. `stopped=true` 或状态无法确认时立即原子撤权、中断监控并请求进程退出；
5. 普通崩溃的 `stopped=false` 只获得 10 秒单调时钟宽限；会话完成或宽限到期后退出；
6. 每次发送 Back 前重新查询 stopped 状态并复核当前会话授权；
7. 官方 destroy 事务继续执行停止、解绑所有权和 `System.exit(0)`。

force-stop 新样本明确记录 `authorization_revoked(reason=owner_package_stopped)` 与 `service_exit_requested`，故障快照中伴侣已经归零；后续目标确实启动，但没有检测或 Back。

该协议选择 fail-safe：包状态输出无法解析时不执行动作。它仍是测试包限定的 PoC；`dumpsys package` 在其他 Android/OEM、多用户和工作资料上的输出及权限必须另行验证。

## 4. 性能回归

动作前新增 stopped 查询后重新执行 Shizuku 正样本 100 次和允许流程 15 次：

| 指标 | v3 结果 | P50 | P95 |
| --- | ---: | ---: | ---: |
| 目标检测 | 100/100 | 53 ms | 116 ms |
| Back 请求 | 100/100 | 71 ms | 139 ms |
| 离开目标 | 100/100 | 158 ms | 211 ms |
| 返回来源 | 100/100 | — | — |
| `input keyevent 4` | 100/100 | 37 ms | 56 ms |
| 单次前台轮询 | 100/100 | 21 ms | 38 ms |
| 允许流程误动作 | 0/15 | — | — |

机器结论仍为 `SHIZUKU_POC_FEASIBLE`。`0/15` 的 Wilson 95% 上界仍为 20.39%，所以负样本只满足当前安全冒烟门，不代表发布级误动作率。

## 5. 复现

前置条件：安装项目测试 APK 与官方 Shizuku；手机通过 ADB 连接；除 `reboot` 外运行前已解锁；Shizuku 权限经过手机上的可见对话框授予。启动方式见[官方用户手册](https://shizuku.rikka.app/guide/setup/)。

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

force-stop 和两种 Shizuku 失联场景使用固定 4 秒无动作观察窗口；正常停止场景只发送 TERM，未停止即失败，不会静默升级成强杀。每场 finally 都停止特权服务、伴侣和测试应用后回到桌面。

聚合本次七份有效时间线：

```powershell
$inputs = @(
  '.\docs\s03\results\s03-ui-kill-20260803-173752.jsonl',
  '.\docs\s03\results\s03-ui-force-stop-20260803-173802.jsonl',
  '.\docs\s03\results\s03-shizuku-graceful-stop-20260803-173813.jsonl',
  '.\docs\s03\results\s03-shizuku-disconnect-20260803-173825.jsonl',
  '.\docs\s03\results\s03-disconnect-recovery-20260803-173837.jsonl',
  '.\docs\s03\results\s03-reboot-20260803-173934.jsonl',
  '.\docs\s03\results\s03-post-reboot-recovery-20260803-174124.jsonl'
)
python .\scripts\s03_lifecycle_report.py @inputs --output .\docs\s03\results\miui14-23078rkd5c-s03-lifecycle-v003-owner-bound-20260803.report.json --strict
python -m unittest scripts.test_s03_lifecycle_report -v
```

原始 JSONL 默认由 `.gitignore` 保留在本机，公开仓库只提交聚合报告及输入 SHA-256。

## 6. 证据与授权边界

- [v3 生命周期通过报告](results/miui14-23078rkd5c-s03-lifecycle-v003-owner-bound-20260803.report.json)
- [v2 force-stop 失败基线](results/miui14-23078rkd5c-s03-lifecycle-20260803.report.json)
- [v3 S0.2 性能报告](../s02/results/miui14-23078rkd5c-s02-shizuku-v003-owner-bound-block100-allow15-20260803.report.json)
- [S0.3 当前门槛决策](decision.md)
- [S0 原架构 No-Go](../s0/go-no-go.md)

`LIFECYCLE_GATE_PASSED` 只授权继续 Advanced 架构和扩大安全验证。它不授权真实第三方包控制、L3-L5 持久动作或消费者发布。
