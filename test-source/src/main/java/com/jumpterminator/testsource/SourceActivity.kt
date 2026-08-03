package com.jumpterminator.testsource

import android.app.Activity
import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.util.UUID

@SuppressLint("SetTextI18n")
class SourceActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var statusView: TextView
    private var runId = ""
    private var sequence = 0
    private var remaining = 0
    private var waitingForReturn = false
    private var activeLoopGapMs = STABLE_LOOP_GAP_MS
    private var activeTriggerType = ""
    private var activeExpected = ""
    private var activeTargetPackage = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(buildContent())
        handleS02Automation(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleS02Automation(intent)
    }

    override fun onResume() {
        super.onResume()
        if (!waitingForReturn) return
        waitingForReturn = false
        TruthEmitter.emit(
            context = this,
            phase = "source_resumed",
            runId = runId,
            sequence = sequence,
            triggerType = activeTriggerType,
            expected = activeExpected,
            targetPackage = activeTargetPackage,
        )
        updateStatus("已返回来源；剩余 $remaining 次")
        if (remaining > 0) {
            handler.postDelayed(
                { launchHarnessTarget("automatic_batch", autoFinishMs = 900L) },
                activeLoopGapMs,
            )
        } else {
            updateStatus("本轮完成 · runId=$runId")
        }
    }

    @Deprecated("S0 keeps API 28 compatibility; migrated to Activity Result APIs in S1")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != TARGET_REQUEST_CODE || resultCode != RESULT_OK || data == null) return
        val resultRunId = data.getStringExtra("run_id") ?: return
        val resultSequence = data.getIntExtra("sequence", -1)
        val targetEnteredElapsedMs = data.getLongExtra("target_entered_elapsed_ms", -1L)
        if (
            resultRunId != runId ||
            resultSequence != sequence ||
            targetEnteredElapsedMs < 0L
        ) {
            return
        }
        TruthEmitter.emit(
            context = this,
            phase = "target_entered",
            runId = resultRunId,
            sequence = resultSequence,
            triggerType = activeTriggerType,
            expected = activeExpected,
            targetPackage = TARGET_PACKAGE,
            originElapsedMs = targetEnteredElapsedMs,
        )
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun buildContent(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(20), dp(20), dp(32))
        }
        root.addView(text("S0 测试来源", 26f, Color.rgb(191, 54, 12)))
        root.addView(text("包名：$packageName", 13f, Color.DKGRAY))
        root.addView(text(
            "这里生成带 runId/序号的标注真值。自动批次中的目标会在 900 ms 后自行返回，因此仅记录模式也能连续采样。",
            14f,
            Color.BLACK,
        ))
        statusView = text("等待测试", 14f, Color.rgb(0, 77, 64)).apply {
            setPadding(0, dp(12), 0, dp(12))
        }
        root.addView(statusView)

        root.addView(title("应阻断样本"))
        root.addView(button("手动点击：打开测试目标") {
            cancelBatch()
            startRun()
            launchHarnessTarget("manual_click", autoFinishMs = 0L)
        })
        root.addView(button("延迟 1.5 秒自动打开一次") {
            cancelBatch()
            startRun()
            updateStatus("等待自动触发…")
            handler.postDelayed({ launchHarnessTarget("automatic_delayed", autoFinishMs = 900L) }, 1_500L)
        })
        root.addView(button("自动循环 10 次（稳定间隔）") { startBatch(10, STABLE_LOOP_GAP_MS) })
        root.addView(button("自动循环 100 次（稳定间隔）") { startBatch(100, STABLE_LOOP_GAP_MS) })
        root.addView(button("压力循环 10 次（短间隔）") { startBatch(10, STRESS_LOOP_GAP_MS) })
        root.addView(button("停止自动循环") { cancelBatch() })

        root.addView(title("应允许负样本"))
        root.addView(button("打开系统设置") {
            launchAllowed(Intent(Settings.ACTION_SETTINGS), "allowed_settings", "com.android.settings")
        })
        root.addView(button("打开浏览器（可能出现选择器）") {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://example.com/jump-terminator-s0"))
            val target = intent.resolveActivity(packageManager)?.packageName ?: "browser_or_chooser"
            launchAllowed(intent, "allowed_browser", target)
        })
        root.addView(button("回到桌面（来源上下文失效）") {
            val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            val target = intent.resolveActivity(packageManager)?.packageName ?: "launcher"
            launchAllowed(intent, "allowed_home", target)
        })

        return ScrollView(this).apply { addView(root) }
    }

    private fun startBatch(count: Int, loopGapMs: Long) {
        cancelBatch()
        startRun()
        activeLoopGapMs = loopGapMs
        remaining = count
        updateStatus("准备自动循环 $count 次 · runId=$runId")
        handler.postDelayed({ launchHarnessTarget("automatic_batch", autoFinishMs = 900L) }, 500L)
    }

    private fun startRun() {
        runId = UUID.randomUUID().toString()
        sequence = 0
    }

    private fun cancelBatch() {
        handler.removeCallbacksAndMessages(null)
        remaining = 0
        waitingForReturn = false
        updateStatus("已停止；等待测试")
    }

    private fun launchHarnessTarget(triggerType: String, autoFinishMs: Long) {
        if (triggerType == "automatic_batch") {
            if (remaining <= 0) return
            remaining -= 1
        }
        sequence += 1
        val targetPackage = TARGET_PACKAGE
        emitIssued(triggerType, "block", targetPackage)
        val intent = Intent().setClassName(TARGET_PACKAGE, TARGET_ACTIVITY).apply {
            putExtra("run_id", runId)
            putExtra("sequence", sequence)
            putExtra("trigger_type", triggerType)
            putExtra("expected", "block")
            putExtra("auto_finish_ms", autoFinishMs)
        }
        waitingForReturn = true
        try {
            startActivityForResult(intent, TARGET_REQUEST_CODE)
            updateStatus("已触发 #$sequence；剩余 $remaining 次")
        } catch (error: Exception) {
            waitingForReturn = false
            remaining = 0
            updateStatus("启动失败：${error.javaClass.simpleName}")
        }
    }

    private fun launchAllowed(intent: Intent, triggerType: String, targetPackage: String) {
        cancelBatch()
        startRun()
        sequence = 1
        emitIssued(triggerType, "allow", targetPackage)
        waitingForReturn = true
        try {
            startActivity(intent)
        } catch (error: Exception) {
            waitingForReturn = false
            updateStatus("启动失败：${error.javaClass.simpleName}")
        }
    }

    /**
     * Test-only entry point for the S0.2 ADB companion harness. It removes
     * coordinate-dependent UI automation while keeping every transition in
     * this dedicated source APK. Only fixed counts and fixed negative probes
     * are accepted; production packages remain unreachable from this path.
     */
    private fun handleS02Automation(commandIntent: Intent?) {
        if (commandIntent == null) return
        val batchCount = commandIntent.getIntExtra(EXTRA_S02_BATCH_COUNT, -1)
        if (batchCount in S02_ALLOWED_BATCH_COUNTS) {
            commandIntent.removeExtra(EXTRA_S02_BATCH_COUNT)
            handler.post { startBatch(batchCount, STABLE_LOOP_GAP_MS) }
            return
        }

        val allowedProbe = commandIntent.getStringExtra(EXTRA_S02_ALLOWED_PROBE) ?: return
        commandIntent.removeExtra(EXTRA_S02_ALLOWED_PROBE)
        handler.postDelayed({
            when (allowedProbe) {
                S02_PROBE_SETTINGS -> launchAllowed(
                    Intent(Settings.ACTION_SETTINGS),
                    "s02_allowed_settings",
                    "com.android.settings",
                )
                S02_PROBE_BROWSER -> {
                    val browserIntent = Intent(
                        Intent.ACTION_VIEW,
                        Uri.parse("https://example.com/jump-terminator-s02"),
                    )
                    val target = browserIntent.resolveActivity(packageManager)?.packageName
                        ?: "browser_or_chooser"
                    launchAllowed(browserIntent, "s02_allowed_browser", target)
                }
                S02_PROBE_HOME -> {
                    val homeIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
                    val target = homeIntent.resolveActivity(packageManager)?.packageName ?: "launcher"
                    launchAllowed(homeIntent, "s02_allowed_home", target)
                }
            }
        }, S02_PROBE_START_DELAY_MS)
    }

    private fun emitIssued(triggerType: String, expected: String, targetPackage: String) {
        activeTriggerType = triggerType
        activeExpected = expected
        activeTargetPackage = targetPackage
        TruthEmitter.emit(
            context = this,
            phase = "trigger_issued",
            runId = runId,
            sequence = sequence,
            triggerType = triggerType,
            expected = expected,
            targetPackage = targetPackage,
        )
    }

    private fun updateStatus(message: String) {
        if (::statusView.isInitialized) statusView.text = message
    }

    private fun title(value: String) = text(value, 19f, Color.rgb(191, 54, 12)).apply {
        setPadding(0, dp(18), 0, dp(6))
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

    companion object {
        private const val TARGET_PACKAGE = "com.jumpterminator.testtarget"
        private const val TARGET_ACTIVITY = "com.jumpterminator.testtarget.TargetActivity"
        private const val TARGET_REQUEST_CODE = 4200
        // The controlled cadence avoids overlapping target instances. S0 later
        // proved that a six-second gap is not immunity from MIUI Greeze, so all
        // acceptance decisions still use the complete realtime report.
        private const val STABLE_LOOP_GAP_MS = 6_000L
        private const val STRESS_LOOP_GAP_MS = 1_200L
        private const val EXTRA_S02_BATCH_COUNT = "jt_s02_batch_count"
        private const val EXTRA_S02_ALLOWED_PROBE = "jt_s02_allowed_probe"
        private const val S02_PROBE_SETTINGS = "settings"
        private const val S02_PROBE_BROWSER = "browser"
        private const val S02_PROBE_HOME = "home"
        private const val S02_PROBE_START_DELAY_MS = 500L
        private val S02_ALLOWED_BATCH_COUNTS = setOf(1, 10, 100)
    }
}
