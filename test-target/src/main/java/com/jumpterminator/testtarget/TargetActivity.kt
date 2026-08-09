package com.jumpterminator.testtarget

import android.app.Activity
import android.app.PictureInPictureParams
import android.annotation.SuppressLint
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.util.Rational
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

@SuppressLint("SetTextI18n")
class TargetActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private var runId = "unknown"
    private var sequence = -1
    private var triggerType = "unknown"
    private var expected = "block"
    private var pipSessionId = "unknown"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        runId = intent.getStringExtra("run_id") ?: "unknown"
        sequence = intent.getIntExtra("sequence", -1)
        triggerType = intent.getStringExtra("trigger_type") ?: "unknown"
        expected = intent.getStringExtra("expected") ?: "block"
        pipSessionId = intent.getStringExtra(EXTRA_PIP_SESSION)
            ?.takeIf(PIP_SESSION_PATTERN::matches)
            ?: "unknown"
        setResult(
            RESULT_OK,
            Intent()
                .putExtra("run_id", runId)
                .putExtra("sequence", sequence)
                .putExtra("target_entered_elapsed_ms", SystemClock.elapsedRealtime()),
        )
        setContentView(buildContent())

        if (intent.getBooleanExtra(EXTRA_ENTER_PIP, false)) {
            handler.post { requestPictureInPicture() }
        }
        val autoFinishMs = intent.getLongExtra("auto_finish_ms", 0L)
        if (autoFinishMs > 0L) handler.postDelayed({ finish() }, autoFinishMs)
    }

    override fun onPictureInPictureModeChanged(
        isInPictureInPictureMode: Boolean,
        newConfig: Configuration,
    ) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
        logPipEvent("pip_mode_changed", "\"active\":$isInPictureInPictureMode")
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun buildContent() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER
        setPadding(dp(24), dp(24), dp(24), dp(24))
        setBackgroundColor(Color.rgb(255, 235, 238))

        addView(TextView(this@TargetActivity).apply {
            text = "S0 测试目标"
            textSize = 30f
            setTextColor(Color.rgb(183, 28, 28))
            gravity = Gravity.CENTER
        }, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

        addView(TextView(this@TargetActivity).apply {
            text = "runId: $runId\nsequence: $sequence\ntrigger: $triggerType\n\n只有本测试包允许被 S0 动作处理。"
            textSize = 15f
            gravity = Gravity.CENTER
            setPadding(0, dp(18), 0, dp(18))
        }, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

        addView(Button(this@TargetActivity).apply {
            text = "返回测试来源"
            isAllCaps = false
            setOnClickListener { finish() }
        })
    }

    private fun requestPictureInPicture() {
        val accepted = enterPictureInPictureMode(
            PictureInPictureParams.Builder()
                .setAspectRatio(Rational(16, 9))
                .build(),
        )
        logPipEvent("pip_requested", "\"accepted\":$accepted")
    }

    private fun logPipEvent(kind: String, details: String) {
        Log.i(
            PIP_LOG_TAG,
            "{\"schema\":\"s0.8-pip-1\",\"kind\":\"$kind\"," +
                "\"sessionId\":\"$pipSessionId\",\"role\":\"target\"," +
                "\"wallClockMs\":${System.currentTimeMillis()}," +
                "\"elapsedRealtimeMs\":${SystemClock.elapsedRealtime()},$details}",
        )
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private companion object {
        const val EXTRA_ENTER_PIP = "jt_s08_enter_pip"
        const val EXTRA_PIP_SESSION = "jt_s08_session"
        const val PIP_LOG_TAG = "JT_S08_PIP"
        val PIP_SESSION_PATTERN = Regex("[a-f0-9]{32}")
    }
}
