# S0.5 调试自动化入口边界验证

状态：**完成，结论为 `S05_DEBUG_AUTOMATION_BOUNDARY_PASSED`**

基线提交：`ddf2c3368f571246435b289172822babfc3e5574`

设备：Redmi `23078RKD5C` / `corot`，Android 13，MIUI 14

执行日期：2026-08-08

实现版本：`0.0.5-s05` / UserService v5

## 发现与修复契约

修复前，带 Launcher intent-filter 的 `MainActivity` 以 `exported=true` 对外开放，同时解析 `jt_s02_session`、`jt_s02_armed` 等自动化 extras。只要 POC 包已获 Shizuku 权限，外部调用者便可让该包以自己的授权连接 UserService 并启动固定测试规则，形成 confused-deputy 路径。动作仍被固定来源、固定目标和一次 Back 限制，但公开入口不应拥有创建特权会话的能力。

修复必须同时满足三个不变量：

- 公开 Launcher 不接受任何自动化命令；
- release APK 不包含自动化入口；
- 合法的 ADB 调试脚本仍可运行 S0.2/S0.3，不改变固定规则、Shizuku 授权或 UserService 安全模型。

## 最小修复

- `MainActivity` 默认使用 `PUBLIC_LAUNCHER` ingress；检测到任一自动化 extra 时先记录拒绝事件、清除 extras 并返回。
- `AutomationActivity` 只放在 `src/debug`，要求平台权限 `android.permission.DUMP`。ADB shell 持有该权限，普通第三方应用不能调用。
- 调试 Activity 使用独立 task affinity 与 `singleTask`，确保连续脚本命令总会进入 `onNewIntent`，不会被公开 Activity 所在任务栈吞掉。
- S0.2/S0.3 脚本只调用受保护的调试组件，不再向公开 `MainActivity` 发送命令。
- `test-source` 的普通 UID 攻击探针同样只存在于 debug 构建，并强制 `armed=false`。

首版曾尝试 `exported=false + adb shell run-as ... am start`。Android 的 `am` 仍以 `com.android.shell` 申明调用包，系统拒绝该组合，合法自动化无法工作。因此最终选择 debug-only + `DUMP` 权限；这不是放宽入口，而是把允许方准确限定为 ADB shell。

## 真机结果

| 验收项 | 会话/结果 | 判定 |
| --- | --- | --- |
| 修复前外部入口复现 | `8e09b5ff760e43e7967fc53488640564`：公开 `MainActivity` 产生 `ready` | 漏洞路径成立 |
| ADB 调试入口 | `45bc1cd749d741c98477d6b18bfa0b5a`：`ready=1` | 合法行为保留 |
| 公开 Launcher 携带 extras | `f7b7a0246a0848caa79897ef8ea2ad13`：拒绝事件 1，`ready=0` | 通过 |
| 普通应用 UID 调试入口 | `2afbffea3e6b4a1eb0b366f78cfe6eb2`：`SecurityException`，`ready=0` | 通过 |
| release 合并清单 | `AutomationActivity` 出现次数 0 | 通过 |
| S0.2 block1 观察回归 | `9fe264a51b8c49babdf166aebc486207`：12 个事件，检测/离开/返回 `1/1`，安全违规 0 | 通过 |
| S0.3 UI force-stop 回归 | `c7ec51ec5cc64dedacf00c035b3a61d6`：`owner_package_stopped`，后续 Back 0 | 通过 |

本次 block1 使用观察模式，所以没有发送 Back，单样本报告显示 `NOT_READY` 属于预期的样本/动作门结果；它不代表入口回归失败。

结构化证据见 [S0.5 报告](results/miui14-23078rkd5c-s05-entrypoint-v005-20260808.report.json)。

## 自动验证

- `AutomationCommandGateTest` 验证公开入口拒绝、ADB debug ingress 允许。
- `test_s05_automation_boundary.py` 验证主/调试清单、`DUMP` 权限、独立任务栈、脚本迁移和普通 UID 探针永不武装。
- debug/release 均完成 assemble；release 合并清单无自动化组件。
- 全工程 Android 单元测试 `48` 项、Python 测试 `28` 项通过；完整 Gradle build/lint 通过。

## 复现

```powershell
python -m unittest scripts.test_s05_automation_boundary -v
.\gradlew.bat :s02-shizuku-poc:testDebugUnitTest :s02-shizuku-poc:assembleDebug :s02-shizuku-poc:assembleRelease
.\scripts\s02-shizuku-run.ps1 -Scenario block -BatchCount 1
.\scripts\s03-lifecycle.ps1 -Scenario ui-force-stop
```

真机权限负探针：

```powershell
adb shell am start -n com.jumpterminator.testsource/.AutomationBoundaryProbeActivity --es jt_s05_session <32位十六进制会话>
adb logcat -d -v raw -s JT_S05_ATTACK:I *:S
```

## 剩余边界

S0.5 关闭的是开发自动化入口，不是整个产品授权问题。debug 签名、ADB 主机信任、Shizuku 本身的授权与启动仍属于开发环境信任根；UserService 重启后的重放状态、多用户/工作资料、其他 OEM 和真实第三方目标仍未覆盖。Standard S0 继续为 No-Go，消费者发布仍未获授权。
