package com.jumpterminator.app.core

/**
 * Delayed OEM event delivery is useful diagnostic evidence, but it must not
 * rewind foreground state or become an actionable transition.
 */
object ForegroundSignalGate {
    const val MAX_TRACKER_SIGNAL_AGE_MS = 500L

    fun shouldDriveTracker(eventElapsedMs: Long, receiptElapsedMs: Long): Boolean =
        receiptElapsedMs - eventElapsedMs <= MAX_TRACKER_SIGNAL_AGE_MS

    /**
     * UsageStats is a fallback signal. When the accessibility service can
     * inspect a live active window, a conflicting UsageStats package must not
     * overwrite that newer and more direct observation.
     */
    fun isUsageSignalConsistent(
        signaledPackage: String,
        liveAccessibilityPackage: String?,
    ): Boolean = liveAccessibilityPackage == null ||
        signaledPackage == liveAccessibilityPackage
}
