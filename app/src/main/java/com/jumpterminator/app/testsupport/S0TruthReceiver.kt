package com.jumpterminator.app.testsupport

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.jumpterminator.app.data.TimelineRecorder

class S0TruthReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_S0_TRUTH) return
        TimelineRecorder(context).record(
            kind = "ground_truth",
            packageName = intent.getStringExtra(EXTRA_ORIGIN_PACKAGE),
            data = mapOf(
                "phase" to intent.getStringExtra(EXTRA_PHASE),
                "runId" to intent.getStringExtra(EXTRA_RUN_ID),
                "sequence" to intent.getIntExtra(EXTRA_SEQUENCE, -1),
                "triggerType" to intent.getStringExtra(EXTRA_TRIGGER_TYPE),
                "expected" to intent.getStringExtra(EXTRA_EXPECTED),
                "targetPackage" to intent.getStringExtra(EXTRA_TARGET_PACKAGE),
                "originElapsedMs" to intent.getLongExtra(EXTRA_ORIGIN_ELAPSED_MS, -1L),
            ),
        )
    }

    companion object {
        const val ACTION_S0_TRUTH = "com.jumpterminator.app.action.S0_TRUTH"
        const val EXTRA_PHASE = "phase"
        const val EXTRA_RUN_ID = "run_id"
        const val EXTRA_SEQUENCE = "sequence"
        const val EXTRA_TRIGGER_TYPE = "trigger_type"
        const val EXTRA_EXPECTED = "expected"
        const val EXTRA_TARGET_PACKAGE = "target_package"
        const val EXTRA_ORIGIN_PACKAGE = "origin_package"
        const val EXTRA_ORIGIN_ELAPSED_MS = "origin_elapsed_ms"
    }
}
