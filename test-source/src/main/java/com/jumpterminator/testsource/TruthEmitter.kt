package com.jumpterminator.testsource

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.SystemClock

object TruthEmitter {
    private const val APP_PACKAGE = "com.jumpterminator.app"
    private const val RECEIVER_CLASS = "com.jumpterminator.app.testsupport.S0TruthReceiver"
    private const val ACTION = "com.jumpterminator.app.action.S0_TRUTH"

    fun emit(
        context: Context,
        phase: String,
        runId: String,
        sequence: Int,
        triggerType: String,
        expected: String,
        targetPackage: String,
    ) {
        val intent = Intent(ACTION)
            .setComponent(ComponentName(APP_PACKAGE, RECEIVER_CLASS))
            .addFlags(Intent.FLAG_INCLUDE_STOPPED_PACKAGES)
            .putExtra("phase", phase)
            .putExtra("run_id", runId)
            .putExtra("sequence", sequence)
            .putExtra("trigger_type", triggerType)
            .putExtra("expected", expected)
            .putExtra("target_package", targetPackage)
            .putExtra("origin_package", context.packageName)
            .putExtra("origin_elapsed_ms", SystemClock.elapsedRealtime())
        context.sendBroadcast(intent)
    }
}
