package com.jumpterminator.app.platform

import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.SystemClock
import com.jumpterminator.app.core.ClockBridge
import com.jumpterminator.app.core.ClockSnapshot
import com.jumpterminator.app.core.UsageEventCompat
import com.jumpterminator.app.data.TimelineRecorder
import java.util.LinkedHashSet
import java.util.concurrent.ExecutorService
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs

class UsageStatsCollector(
    context: Context,
    private val handler: Handler,
    private val executor: ExecutorService,
    private val recorder: TimelineRecorder,
    private val onForeground: (packageName: String, elapsedMs: Long, evidence: String) -> Unit,
    private val onClockJump: (driftMs: Long) -> Unit,
) {
    private val usageStats = context.getSystemService(UsageStatsManager::class.java)
    private val queryRunning = AtomicBoolean(false)
    private val seenKeys = LinkedHashSet<String>()
    private val lastMoveToForegroundByPackage = mutableMapOf<String, Long>()
    private val minimumActionableWallClockMs = System.currentTimeMillis()
    @Volatile
    private var stopped = false
    private var lastQueryWallMs = System.currentTimeMillis() - INITIAL_LOOKBACK_MS
    private var baseline: ClockSnapshot = ClockBridge.capture()

    private val pollRunnable = object : Runnable {
        override fun run() {
            if (stopped) return
            pollOnce()
            handler.postDelayed(this, POLL_INTERVAL_MS)
        }
    }

    fun start() {
        stopped = false
        handler.removeCallbacks(pollRunnable)
        handler.post(pollRunnable)
    }

    fun stop() {
        stopped = true
        handler.removeCallbacks(pollRunnable)
    }

    private fun pollOnce() {
        if (usageStats == null || !queryRunning.compareAndSet(false, true)) return
        executor.execute {
            try {
                queryEvents()
            } catch (error: RuntimeException) {
                recorder.record(
                    kind = "usage_query_error",
                    data = mapOf("error" to error.javaClass.simpleName),
                )
            } finally {
                queryRunning.set(false)
            }
        }
    }

    private fun queryEvents() {
        val snapshot = ClockBridge.capture()
        val drift = baseline.driftAt(snapshot.wallClockMs, snapshot.elapsedRealtimeMs)
        if (abs(drift) > CLOCK_JUMP_THRESHOLD_MS) {
            baseline = snapshot
            handler.post { onClockJump(drift) }
            recorder.record(kind = "clock_jump", data = mapOf("driftMs" to drift))
        }

        val endWallMs = snapshot.wallClockMs
        val beginWallMs = maxOf(lastQueryWallMs - QUERY_OVERLAP_MS, endWallMs - MAX_LOOKBACK_MS)
        val events = usageStats.queryEvents(beginWallMs, endWallMs)
        val event = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            val packageName = event.packageName ?: continue
            val signal = UsageEventCompat.classify(Build.VERSION.SDK_INT, event.eventType)
            if (signal == UsageEventCompat.Signal.IGNORE) continue

            val key = "$packageName:${event.eventType}:${event.timeStamp}"
            if (!remember(key)) continue

            val shouldDriveForeground = if (signal == UsageEventCompat.Signal.FOREGROUND) {
                val shouldDrive = UsageEventCompat.shouldDriveForeground(
                    eventType = event.eventType,
                    eventWallClockMs = event.timeStamp,
                    lastMoveToForegroundWallClockMs = lastMoveToForegroundByPackage[packageName],
                    minimumActionableWallClockMs = minimumActionableWallClockMs,
                )
                if (event.eventType == UsageEventCompat.MOVE_TO_FOREGROUND) {
                    lastMoveToForegroundByPackage[packageName] = event.timeStamp
                }
                shouldDrive
            } else {
                false
            }

            val elapsedMs = snapshot.wallToElapsed(event.timeStamp)
            recorder.record(
                kind = "usage_signal",
                packageName = packageName,
                elapsedRealtimeMs = elapsedMs,
                data = mapOf(
                    "signal" to signal.name,
                    "eventType" to event.eventType,
                    "eventWallClockMs" to event.timeStamp,
                    "forwardedToTracker" to shouldDriveForeground,
                    "suppressionReason" to when {
                        signal != UsageEventCompat.Signal.FOREGROUND || shouldDriveForeground -> null
                        event.timeStamp < minimumActionableWallClockMs -> "collector_warmup"
                        else -> "nearby_move_to_foreground"
                    },
                ),
            )
            if (signal == UsageEventCompat.Signal.FOREGROUND && shouldDriveForeground) {
                // Give the lower-latency accessibility signal a short chance
                // to establish the current package before UsageStats corroboration.
                handler.postDelayed(
                    { if (!stopped) onForeground(packageName, elapsedMs, "usage_stats") },
                    ACCESSIBILITY_GRACE_MS,
                )
            }
        }
        lastQueryWallMs = endWallMs
    }

    @Synchronized
    private fun remember(key: String): Boolean {
        if (!seenKeys.add(key)) return false
        while (seenKeys.size > MAX_DEDUPE_KEYS) {
            val iterator = seenKeys.iterator()
            if (iterator.hasNext()) {
                iterator.next()
                iterator.remove()
            }
        }
        return true
    }

    companion object {
        private const val POLL_INTERVAL_MS = 750L
        private const val ACCESSIBILITY_GRACE_MS = 120L
        private const val INITIAL_LOOKBACK_MS = 3_000L
        private const val MAX_LOOKBACK_MS = 5_000L
        private const val QUERY_OVERLAP_MS = 300L
        private const val CLOCK_JUMP_THRESHOLD_MS = 5_000L
        private const val MAX_DEDUPE_KEYS = 512
    }
}
