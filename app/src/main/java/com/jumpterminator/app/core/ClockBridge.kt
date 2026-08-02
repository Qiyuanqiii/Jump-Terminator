package com.jumpterminator.app.core

import android.os.SystemClock

/** Maps UsageStats wall-clock timestamps into the boot-relative S0 timeline. */
data class ClockSnapshot(
    val wallClockMs: Long,
    val elapsedRealtimeMs: Long,
) {
    fun wallToElapsed(eventWallClockMs: Long): Long =
        elapsedRealtimeMs + (eventWallClockMs - wallClockMs)

    fun driftAt(nowWallClockMs: Long, nowElapsedRealtimeMs: Long): Long =
        (nowWallClockMs - wallClockMs) - (nowElapsedRealtimeMs - elapsedRealtimeMs)
}

object ClockBridge {
    fun capture(): ClockSnapshot = ClockSnapshot(
        wallClockMs = System.currentTimeMillis(),
        elapsedRealtimeMs = SystemClock.elapsedRealtime(),
    )
}
