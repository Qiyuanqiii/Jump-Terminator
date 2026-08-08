package com.jumpterminator.testsource

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.util.Log
import org.json.JSONObject

/**
 * Test-only ordinary-UID probe for the S0.5 automation boundary.
 * It never requests an armed monitor and emits one machine-readable log line.
 */
class AutomationBoundaryProbeActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val sessionId = intent.getStringExtra(EXTRA_SESSION).orEmpty()
        val probe = Intent().setClassName(POC_PACKAGE, POC_AUTOMATION_ACTIVITY).apply {
            putExtra("jt_s02_session", sessionId)
            putExtra("jt_s02_max_actions", 1)
            putExtra("jt_s02_requested_allowed", 0)
            putExtra("jt_s02_armed", false)
        }

        val result = JSONObject().apply {
            put("schema", "s0.5-entrypoint-1")
            put("sessionId", sessionId)
        }
        try {
            startActivity(probe)
            result.put("result", "unexpectedly_allowed")
        } catch (error: SecurityException) {
            result.put("result", "denied")
            result.put("error", error.javaClass.simpleName)
        } catch (error: Exception) {
            result.put("result", "unexpected_error")
            result.put("error", error.javaClass.simpleName)
        }

        Log.i(LOG_TAG, result.toString())
        finish()
    }

    companion object {
        private const val LOG_TAG = "JT_S05_ATTACK"
        private const val EXTRA_SESSION = "jt_s05_session"
        private const val POC_PACKAGE = "com.jumpterminator.s02"
        private const val POC_AUTOMATION_ACTIVITY =
            "com.jumpterminator.s02.AutomationActivity"
    }
}
