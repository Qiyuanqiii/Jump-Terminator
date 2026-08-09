# S0.8 画中画窗口拓扑失效安全决策

状态：**通过，决策为 `S08_PIP_CONTEXT_GATE_PASSED`**

设备：Redmi `23078RKD5C` / Android 13 / MIUI 14

版本：`0.0.8-s08` / UserService v7

日期：2026-08-09

## 决策

允许继续下一项 Advanced S0 架构与安全验证。正式矩阵中的目标预先 PiP 后展开 `5/5`、来源进入 PiP 并露出目标 `5/5` 均取得系统 pinned 真值，目标检测和 Back 请求均为 0；独立全屏正向对照的检测、Back、离开和返回均为 `10/10`。

此决策不改变 Standard S0 No-Go，不授权消费者发布、真实第三方应用控制或 L3-L5 持久动作。

## 缺陷与修复判定

修复前的 v0.0.7 模型只保留 top-resumed 组件集合，不保留 pinned 窗口。会话 `839d250d781c4398b3526a2439d1dff2` 中，目标在来源上下文建立前已经由系统确认处于 PiP，展开时旧服务仍产生 1 次检测和 1 次已派发 Back，因此属于必须修复的误动作。

采用的修复只收紧动作前置条件：采样 active PiP/pinned 状态；任何 PiP 都把上下文标记为不可动作；已建立来源立即失效；最终动作授权再次复核 PiP。普通全屏路径没有放宽身份、能力、规则、租约、锁屏或前台验证，正式正向对照证明合法固定测试路径仍保持 `10/10`。

## 验收证据

| 门 | 结果 | 判定 |
| --- | --- | --- |
| 目标预先 PiP 零动作 | 5 个独立会话均有系统 pinned 边界，检测/Back `0/0` | 通过 |
| 来源 PiP 零动作 | 5 个独立会话均证明来源先建立、随后 pinned 并以 `picture_in_picture` 失效，检测/Back `0/0` | 通过 |
| 全屏回归 | 检测、Back、离开、返回均 `10/10` | 通过 |
| 证据完整性 | 10 个会话 ID 唯一；每轮 `ready` 均绑定 armed block、Shizuku、owner 与一次性授权，授权租约覆盖 PiP 边界、目标呈现、stop 和 worker complete；观察窗口事件含双时钟和会话身份，`complete(reason=stop_requested)` 的检测/动作均为 `0/0` 后才汇总；结构化 display/windowing/top/pinned 快照完整，警告与违规为 0 | 通过 |
| 聚合决策 | 样本门、安全门均为 `true` | `S08_PIP_CONTEXT_GATE_PASSED` |

正式报告见 [S0.8 聚合报告](results/miui14-23078rkd5c-s08-pip-v008-20260809/s08-pip-context.report.json)，原缺陷复现见[修复前 v0.0.7 记录](v007-pre-fix.md)。

## 剩余不确定性

- 单设备、单用户、固定测试包和 debug 构建仍是硬边界；
- 正式证据只有内置 `displayId=0`，多显示器未通过硬门；
- 其他 OEM/Android 版本、自由窗、工作资料/双开和真实第三方目标未覆盖；
- worker complete 后的撤权与服务退出行政日志不纳入正式时间线；设备日志复核未发现迟到检测或 Back；
- 内存/资源压力、长轮询停顿、owner death 锚点与 stop/start 竞态转入 S0.9；
- 本门只证明当前 L1 固定测试动作在两类 PiP 拓扑中 fail-closed，不构成产品级 Go。
