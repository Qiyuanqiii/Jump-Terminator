# S0.5 调试自动化入口边界决策

状态：**通过，决策为 `S05_DEBUG_AUTOMATION_BOUNDARY_PASSED`**

设备：Redmi `23078RKD5C` / Android 13 / MIUI 14

版本：`0.0.5-s05` / UserService v5

日期：2026-08-08

## 决策

采用“公开 Launcher 默认拒绝 + debug-only 权限组件”方案。公开 `MainActivity` 不再解析自动化命令；`AutomationActivity` 仅存在于 debug source set，并要求 `android.permission.DUMP`。release APK 不包含该组件。相比把共享密钥、调用方 UID 或可伪造 extras 放在应用层，这一方案在最靠近 Android 组件入口的位置使用系统调用权限完成区分。

该修复保持了正常 Launcher 行为、ADB 自动化、固定规则与 UserService 授权协议；原公开入口的特权会话创建路径不再复现。因此允许继续下一项 Advanced S0 安全验证。

## 验收证据

| 安全属性 | 结果 | 判定 |
| --- | --- | --- |
| 公开入口默认拒绝 | 合法格式 extras 被记录为 `public_launcher` 拒绝，特权 `ready=0` | 通过 |
| 普通应用隔离 | UID `10417` 调用调试组件收到 `SecurityException`，`ready=0` | 通过 |
| ADB 合法行为 | shell UID `2000` 持有 `DUMP`，调试入口产生 `ready=1` | 通过 |
| 发布构建 | release 合并清单不存在 `AutomationActivity` | 通过 |
| 脚本兼容 | S0.2 block1 端到端脚本退出码 0 | 通过 |
| 生命周期兼容 | `ui-force-stop` 场景完成，`owner_package_stopped` 撤权且后续 Back 0 | 通过 |
| 自动化 | Android `48` 项、Python `28` 项及完整 build/lint | 通过 |

正式证据：[结构化报告](results/miui14-23078rkd5c-s05-entrypoint-v005-20260808.report.json)。

## 原问题已关闭

修复前，外部显式 Intent 到导出的 Launcher 可产生 UserService `ready`。修复后，同样的公开入口输入只产生拒绝事件；由普通应用 UID 直接调用调试组件则在 Android 组件权限检查处失败，两条路径都没有特权事件。合法 ADB 路径和两条代表性回归保持可用。

## 剩余风险

- `DUMP` 是开发/系统权限边界，因此此入口只能用于 debug 构建，不能演化为消费者授权接口；
- 已获 ADB shell 控制权的主机本就在开发信任边界内，可以运行调试自动化；
- 该修复不改变 Shizuku 授权、UserService 进程内重放集合或 package/input 系统竞态；
- 真机覆盖仍只有一台 MIUI 14 设备，未覆盖多用户、工作资料、双开与其他 OEM；
- Standard S0 No-Go 与禁止 L3–L5、真实第三方目标及消费者发布的约束保持不变。
