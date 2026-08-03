package com.jumpterminator.s02

import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Binder
import android.os.Bundle
import android.os.IBinder
import android.os.Process
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import rikka.shizuku.Shizuku
import java.util.UUID

class MainActivity : Activity() {
    private lateinit var statusView: TextView
    private lateinit var serviceArgs: Shizuku.UserServiceArgs
    private val ownerToken = Binder()
    private var service: IPrivilegedCompanion? = null
    private var pendingCommand: MonitorCommand? = null
    private var pendingControl: String? = null

    private val binderReceivedListener = Shizuku.OnBinderReceivedListener {
        renderStatus("Shizuku Binder 已连接")
        tryStartPending()
    }
    private val binderDeadListener = Shizuku.OnBinderDeadListener {
        service = null
        renderStatus("Shizuku Binder 已断开")
    }
    private val permissionListener = Shizuku.OnRequestPermissionResultListener { requestCode, result ->
        if (requestCode != REQUEST_CODE) return@OnRequestPermissionResultListener
        if (result == PackageManager.PERMISSION_GRANTED) {
            renderStatus("Shizuku 权限已授予；正在连接 UserService")
            bindCompanion()
        } else {
            renderStatus("Shizuku 权限未授予")
        }
    }
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            service = IPrivilegedCompanion.Stub.asInterface(binder)
            renderStatus("特权伴侣已连接：${service?.status()}")
            tryStartPending()
        }

        override fun onServiceDisconnected(name: ComponentName) {
            service = null
            renderStatus("特权伴侣已断开")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        serviceArgs = Shizuku.UserServiceArgs(
            ComponentName(packageName, PrivilegedCompanionService::class.java.name),
        )
            .daemon(true)
            .processNameSuffix("s02_companion")
            .debuggable(true)
            .version(3)
            .tag("jump-terminator-s02")
        setContentView(buildContent())
        Shizuku.addBinderReceivedListenerSticky(binderReceivedListener)
        Shizuku.addBinderDeadListener(binderDeadListener)
        Shizuku.addRequestPermissionResultListener(permissionListener)
        handleCommandIntent(intent)
        renderStatus(currentStatus())
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleCommandIntent(intent)
    }

    override fun onDestroy() {
        Shizuku.removeBinderReceivedListener(binderReceivedListener)
        Shizuku.removeBinderDeadListener(binderDeadListener)
        Shizuku.removeRequestPermissionResultListener(permissionListener)
        super.onDestroy()
    }

    private fun buildContent() = ScrollView(this).apply {
        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(24), dp(20), dp(32))
            addView(text("Jump Terminator · S0.2", 26f, Color.rgb(74, 20, 140)))
            addView(text(
                "实验性 Kotlin + Shizuku UserService。只处理固定测试来源 → 固定测试目标；不是消费者版功能。",
                15f,
                Color.DKGRAY,
            ))
            statusView = text("初始化中", 14f, Color.rgb(0, 77, 64)).apply {
                setPadding(0, dp(18), 0, dp(18))
            }
            addView(statusView)
            addView(button("请求 Shizuku 权限") { ensurePermission() })
            addView(button("连接特权伴侣") { bindCompanion() })
            addView(button("启动单次武装探针") {
                pendingCommand = MonitorCommand(
                    UUID.randomUUID().toString().replace("-", ""),
                    1,
                    0,
                    true,
                )
                tryStartPending()
            })
            addView(button("查询伴侣状态") {
                renderStatus(service?.status() ?: currentStatus())
            })
            addView(button("停止监控") {
                service?.stopMonitor()
                renderStatus("已请求停止监控")
            })
            addView(button("销毁特权伴侣") {
                try {
                    service?.destroy()
                } finally {
                    Shizuku.unbindUserService(serviceArgs, connection, true)
                    service = null
                }
                renderStatus("特权伴侣已销毁")
            })
        })
    }

    private fun handleCommandIntent(commandIntent: Intent?) {
        if (commandIntent == null) return
        val control = commandIntent.getStringExtra(EXTRA_CONTROL)
        if (control != null) {
            commandIntent.removeExtra(EXTRA_CONTROL)
            if (control != CONTROL_STOP) {
                renderStatus("拒绝无效控制命令")
                return
            }
            pendingControl = control
            tryStartPending()
            return
        }
        val sessionId = commandIntent.getStringExtra(EXTRA_SESSION) ?: return
        val requestedBlock = commandIntent.getIntExtra(EXTRA_MAX_ACTIONS, -1)
        val requestedAllowed = commandIntent.getIntExtra(EXTRA_REQUESTED_ALLOWED, 0)
        val armed = commandIntent.getBooleanExtra(EXTRA_ARMED, false)
        val validBlock = requestedBlock in setOf(1, 10, 100) && requestedAllowed == 0
        val validAllowed = requestedBlock == 0 && requestedAllowed in 1..60 && armed
        if (!sessionId.matches(Regex("[a-f0-9]{32}")) || (!validBlock && !validAllowed)) {
            renderStatus("拒绝无效自动化参数")
            return
        }
        commandIntent.removeExtra(EXTRA_SESSION)
        commandIntent.removeExtra(EXTRA_MAX_ACTIONS)
        commandIntent.removeExtra(EXTRA_REQUESTED_ALLOWED)
        commandIntent.removeExtra(EXTRA_ARMED)
        pendingCommand = MonitorCommand(
            sessionId,
            requestedBlock,
            requestedAllowed,
            armed,
        )
        tryStartPending()
    }

    private fun tryStartPending() {
        val connectedService = service
        val control = pendingControl
        if (control != null) {
            if (connectedService != null) {
                connectedService.stopMonitor()
                pendingControl = null
                renderStatus("已请求停止监控")
            } else if (hasPermission()) {
                bindCompanion()
            } else {
                renderStatus("请先授予 Shizuku 权限")
            }
            return
        }
        val command = pendingCommand ?: return
        if (connectedService != null) {
            val result = connectedService.startMonitor(
                command.sessionId,
                command.requestedBlock,
                command.requestedAllowed,
                command.armed,
                Process.myUid(),
                ownerToken,
            )
            pendingCommand = null
            renderStatus("监控已启动：$result")
            return
        }
        if (hasPermission()) bindCompanion() else renderStatus("请先授予 Shizuku 权限")
    }

    private fun bindCompanion() {
        if (!Shizuku.pingBinder()) {
            renderStatus("Shizuku 尚未运行")
            return
        }
        if (!hasPermission()) {
            ensurePermission()
            return
        }
        try {
            Shizuku.bindUserService(serviceArgs, connection)
            renderStatus("正在连接特权伴侣…")
        } catch (error: Throwable) {
            renderStatus("连接失败：${error.javaClass.simpleName}: ${error.message}")
        }
    }

    private fun ensurePermission() {
        if (!Shizuku.pingBinder()) {
            renderStatus("Shizuku 尚未运行")
            return
        }
        if (hasPermission()) {
            renderStatus("Shizuku 权限已存在")
            bindCompanion()
        } else if (Shizuku.shouldShowRequestPermissionRationale()) {
            renderStatus("权限已被拒绝；请在 Shizuku 中重新允许")
        } else {
            Shizuku.requestPermission(REQUEST_CODE)
            renderStatus("等待 Shizuku 权限确认")
        }
    }

    private fun hasPermission(): Boolean = try {
        Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    } catch (_: Throwable) {
        false
    }

    private fun currentStatus(): String = try {
        if (!Shizuku.pingBinder()) {
            "Shizuku 未运行"
        } else {
            "Shizuku 已运行 · uid=${Shizuku.getUid()} · permission=${hasPermission()}"
        }
    } catch (error: Throwable) {
        "Shizuku 状态异常：${error.javaClass.simpleName}"
    }

    private fun renderStatus(value: String) {
        runOnUiThread { if (::statusView.isInitialized) statusView.text = value }
    }

    private fun text(value: String, size: Float, color: Int) = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
    }

    private fun button(label: String, action: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        setOnClickListener { action() }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private data class MonitorCommand(
        val sessionId: String,
        val requestedBlock: Int,
        val requestedAllowed: Int,
        val armed: Boolean,
    )

    companion object {
        private const val REQUEST_CODE = 2002
        private const val EXTRA_SESSION = "jt_s02_session"
        private const val EXTRA_MAX_ACTIONS = "jt_s02_max_actions"
        private const val EXTRA_REQUESTED_ALLOWED = "jt_s02_requested_allowed"
        private const val EXTRA_ARMED = "jt_s02_armed"
        private const val EXTRA_CONTROL = "jt_s02_control"
        private const val CONTROL_STOP = "stop"
    }
}
