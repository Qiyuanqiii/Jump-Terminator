package com.jumpterminator.app

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.method.ScrollingMovementMethod
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import com.jumpterminator.app.core.S0Policy
import com.jumpterminator.app.data.S0SettingsRepository
import com.jumpterminator.app.data.TimelineRecorder
import com.jumpterminator.app.data.UserIdentityResolver
import com.jumpterminator.app.platform.PermissionChecks
import com.jumpterminator.app.service.ObservationKeepAliveService
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@SuppressLint("SetTextI18n")
class MainActivity : Activity() {
    private lateinit var settingsRepository: S0SettingsRepository
    private lateinit var recorder: TimelineRecorder
    private lateinit var statusView: TextView
    private lateinit var timelineView: TextView
    private lateinit var armedSwitch: Switch
    private lateinit var homeFallbackSwitch: Switch

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settingsRepository = S0SettingsRepository(this)
        recorder = TimelineRecorder(this)
        setContentView(buildContent())
    }

    override fun onResume() {
        super.onResume()
        val settings = settingsRepository.load()
        armedSwitch.isChecked = settings.mode.name == "ARMED_BLOCK"
        homeFallbackSwitch.isChecked = settings.homeFallbackEnabled
        refreshDiagnostics()
    }

    @Deprecated("S0 keeps API 28 compatibility; migrated to Activity Result APIs in S1")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != EXPORT_REQUEST_CODE || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        try {
            contentResolver.openOutputStream(uri)?.use { recorder.exportTo(it) }
            toast("时间线已导出")
        } catch (error: Exception) {
            toast("导出失败：${error.javaClass.simpleName}")
        }
    }

    @Deprecated("S0 keeps API 28 compatibility; migrated to Activity Result APIs in S1")
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != NOTIFICATION_PERMISSION_REQUEST_CODE) return
        val granted = grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
        startKeepAlive(showNotificationWarning = !granted)
    }

    private fun buildContent(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(20), dp(20), dp(32))
        }

        root.addView(text("Jump Terminator · S0", 26f, Color.rgb(13, 71, 161)))
        root.addView(text("技术可行性验证诊断版 · 0.0.10-s0", 14f, Color.DKGRAY))
        root.addView(spacer(12))
        root.addView(text(
            "安全边界：默认仅记录。武装后也只会精确处理随包测试来源 → 测试目标，且每个候选最多执行一次返回和一次可选主页；不会处理其他应用。",
            15f,
            Color.rgb(183, 28, 28),
        ))
        root.addView(spacer(12))

        statusView = text("正在检查…", 14f, Color.BLACK)
        statusView.setPadding(dp(12), dp(12), dp(12), dp(12))
        statusView.setBackgroundColor(Color.rgb(238, 244, 252))
        root.addView(statusView, matchWrap())

        root.addView(sectionTitle("1. 授权与测试入口"))
        root.addView(button("打开无障碍设置") {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
        root.addView(button("打开使用情况访问设置") {
            startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).apply {
                data = Uri.parse("package:$packageName")
            })
        })
        root.addView(button("启动 S0 测试来源 App") { launchTestSource() })

        root.addView(sectionTitle("2. MIUI 实时性实验"))
        root.addView(text(
            "前台保活只在你明确启动后运行，并显示持续通知；不自启动、不静默重启，也不会改变仅记录/武装动作模式。",
            13f,
            Color.DKGRAY,
        ))
        root.addView(button("启动前台保活（持续通知）") { confirmKeepAliveStart() })
        root.addView(button("停止前台保活") { stopKeepAlive() })

        root.addView(sectionTitle("3. 受控动作模式"))
        root.addView(text("固定来源：${S0Policy.HARNESS_SOURCE_PACKAGE}\n固定目标：${S0Policy.HARNESS_TARGET_PACKAGE}", 13f, Color.DKGRAY))
        armedSwitch = Switch(this).apply { text = "武装测试阻断（默认关闭）" }
        homeFallbackSwitch = Switch(this).apply { text = "Back 未离开目标时，追加一次 Home" }
        root.addView(armedSwitch, matchWrap())
        root.addView(homeFallbackSwitch, matchWrap())
        root.addView(button("保存动作模式") { saveActionMode() })

        root.addView(sectionTitle("4. 时间线"))
        root.addView(button("刷新最近事件") { refreshDiagnostics() })
        root.addView(button("导出完整 JSONL") { requestExport() })
        root.addView(button("清空 S0 时间线") { confirmClear() })
        timelineView = text("尚无事件", 11f, Color.rgb(32, 32, 32)).apply {
            typeface = android.graphics.Typeface.MONOSPACE
            movementMethod = ScrollingMovementMethod()
            setTextIsSelectable(true)
            setPadding(dp(10), dp(10), dp(10), dp(10))
            setBackgroundColor(Color.rgb(245, 245, 245))
        }
        root.addView(timelineView, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            dp(360),
        ))

        return ScrollView(this).apply { addView(root) }
    }

    private fun saveActionMode() {
        if (!armedSwitch.isChecked) {
            settingsRepository.save(armed = false, homeFallbackEnabled = homeFallbackSwitch.isChecked)
            recorder.record(kind = "mode_changed", data = mapOf("mode" to "RECORD_ONLY"))
            toast("已保存：仅记录")
            refreshDiagnostics()
            return
        }

        AlertDialog.Builder(this)
            .setTitle("武装 S0 测试阻断？")
            .setMessage("仅在测试来源精确跳转到测试目标、身份已确认时执行一次 Back；可选再执行一次 Home。请勿将测试目标用于真实业务。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认武装") { _, _ ->
                settingsRepository.save(armed = true, homeFallbackEnabled = homeFallbackSwitch.isChecked)
                recorder.record(
                    kind = "mode_changed",
                    data = mapOf(
                        "mode" to "ARMED_BLOCK",
                        "homeFallbackEnabled" to homeFallbackSwitch.isChecked,
                    ),
                )
                toast("已武装：仅限 S0 测试包")
                refreshDiagnostics()
            }
            .show()
    }

    private fun confirmKeepAliveStart() {
        AlertDialog.Builder(this)
            .setTitle("启动前台保活验证？")
            .setMessage(
                "用于验证 MIUI 是否仍会冻结观察进程。运行期间会有持续通知；服务不会随开机启动，进程被终止后也不会自行重启。",
            )
            .setNegativeButton("取消", null)
            .setPositiveButton("启动") { _, _ -> requestNotificationThenStart() }
            .show()
    }

    private fun requestNotificationThenStart() {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                NOTIFICATION_PERMISSION_REQUEST_CODE,
            )
            return
        }
        startKeepAlive(showNotificationWarning = false)
    }

    private fun startKeepAlive(showNotificationWarning: Boolean) {
        try {
            recorder.record(
                kind = "keepalive_start_requested",
                packageName = packageName,
                data = mapOf("notificationPermissionGranted" to !showNotificationWarning),
            )
            ObservationKeepAliveService.start(this)
            if (showNotificationWarning) {
                toast("已启动；通知未授权时仅在系统任务管理器显示")
            } else {
                toast("前台保活验证已启动")
            }
            statusView.postDelayed({ refreshDiagnostics() }, 500)
        } catch (error: RuntimeException) {
            recorder.record(
                kind = "keepalive_start_failed",
                packageName = packageName,
                data = mapOf("error" to error.javaClass.simpleName),
            )
            toast("启动失败：${error.javaClass.simpleName}")
            refreshDiagnostics()
        }
    }

    private fun stopKeepAlive() {
        recorder.record(kind = "keepalive_stop_requested", packageName = packageName)
        ObservationKeepAliveService.stop(this)
        toast("前台保活验证已停止")
        statusView.postDelayed({ refreshDiagnostics() }, 300)
    }

    private fun launchTestSource() {
        val launchIntent = packageManager.getLaunchIntentForPackage(S0Policy.HARNESS_SOURCE_PACKAGE)
        if (launchIntent == null) {
            toast("未安装 test-source APK")
        } else {
            startActivity(launchIntent)
        }
    }

    private fun requestExport() {
        recorder.record(kind = "timeline_export_requested", packageName = packageName)
        val timestamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
        startActivityForResult(
            Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/x-ndjson"
                putExtra(Intent.EXTRA_TITLE, "jump-terminator-s0-$timestamp.jsonl")
            },
            EXPORT_REQUEST_CODE,
        )
    }

    private fun confirmClear() {
        AlertDialog.Builder(this)
            .setTitle("清空 S0 时间线？")
            .setMessage("应用内记录将被删除；已导出的文件不受影响。")
            .setNegativeButton("取消", null)
            .setPositiveButton("清空") { _, _ ->
                recorder.clear()
                recorder.record(kind = "timeline_cleared", packageName = packageName)
                refreshDiagnostics()
            }
            .show()
    }

    private fun refreshDiagnostics() {
        val accessibility = PermissionChecks.isAccessibilityEnabled(this)
        val usage = PermissionChecks.hasUsageStatsAccess(this)
        val identity = UserIdentityResolver.resolve(this)
        val settings = settingsRepository.load()
        val testSourceInstalled = isPackageInstalled(S0Policy.HARNESS_SOURCE_PACKAGE)
        val testTargetInstalled = isPackageInstalled(S0Policy.HARNESS_TARGET_PACKAGE)

        statusView.text = buildString {
            appendLine("无障碍服务：${yesNo(accessibility)}")
            appendLine("使用情况访问：${yesNo(usage)}")
            appendLine("当前用户身份：${if (identity.known) "已确认" else "未知（动作被禁止）"}")
            appendLine("userId / serial：${identity.userId ?: "?"} / ${identity.userSerial ?: "?"}")
            appendLine("测试来源 / 目标：${yesNo(testSourceInstalled)} / ${yesNo(testTargetInstalled)}")
            appendLine("前台保活验证：${if (ObservationKeepAliveService.isRunning) "运行中" else "未运行"}")
            appendLine("当前模式：${settings.mode.name}")
            append("日志体积：${recorder.totalBytes()} bytes")
        }
        timelineView.text = recorder.tail(35).joinToString("\n").ifEmpty { "尚无事件" }
    }

    private fun isPackageInstalled(packageName: String): Boolean = try {
        packageManager.getApplicationInfo(packageName, 0)
        true
    } catch (_: Exception) {
        false
    }

    private fun yesNo(value: Boolean) = if (value) "是" else "否"

    private fun sectionTitle(value: String) = text(value, 19f, Color.rgb(13, 71, 161)).apply {
        setPadding(0, dp(20), 0, dp(8))
    }

    private fun text(value: String, sizeSp: Float, color: Int) = TextView(this).apply {
        text = value
        textSize = sizeSp
        setTextColor(color)
    }

    private fun button(label: String, action: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        setOnClickListener { action() }
    }

    private fun spacer(heightDp: Int) = View(this).apply {
        layoutParams = LinearLayout.LayoutParams(1, dp(heightDp))
    }

    private fun matchWrap() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    )

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_SHORT).show()

    companion object {
        private const val EXPORT_REQUEST_CODE = 4100
        private const val NOTIFICATION_PERMISSION_REQUEST_CODE = 4102
    }
}
