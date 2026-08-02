package com.jumpterminator.app.core

/** API-independent mapping kept testable without an Android runtime. */
object UsageEventCompat {
    const val MOVE_TO_FOREGROUND = 1
    const val MOVE_TO_BACKGROUND = 2
    const val ACTIVITY_RESUMED = 23
    const val ACTIVITY_PAUSED = 24

    enum class Signal {
        FOREGROUND,
        BACKGROUND,
        IGNORE,
    }

    fun classify(apiLevel: Int, eventType: Int): Signal = when {
        apiLevel >= 29 && eventType == ACTIVITY_RESUMED -> Signal.FOREGROUND
        apiLevel >= 29 && eventType == ACTIVITY_PAUSED -> Signal.BACKGROUND
        eventType == MOVE_TO_FOREGROUND -> Signal.FOREGROUND
        eventType == MOVE_TO_BACKGROUND -> Signal.BACKGROUND
        else -> Signal.IGNORE
    }

    /**
     * Some OEMs publish ACTIVITY_RESUMED well after a newer legacy foreground/background pair.
     * Keep lifecycle events as a fallback for devices that do not publish MOVE_TO_FOREGROUND,
     * but do not let a nearby duplicate drive the foreground state machine.
     */
    fun shouldDriveForeground(
        eventType: Int,
        eventWallClockMs: Long,
        lastMoveToForegroundWallClockMs: Long?,
        minimumActionableWallClockMs: Long? = null,
    ): Boolean = when (eventType) {
        MOVE_TO_FOREGROUND -> minimumActionableWallClockMs == null ||
            eventWallClockMs >= minimumActionableWallClockMs
        ACTIVITY_RESUMED -> {
            if (
                minimumActionableWallClockMs != null &&
                eventWallClockMs < minimumActionableWallClockMs
            ) {
                false
            } else if (lastMoveToForegroundWallClockMs == null) {
                true
            } else {
                val deltaMs = eventWallClockMs - lastMoveToForegroundWallClockMs
                deltaMs !in 0..LIFECYCLE_DUPLICATE_WINDOW_MS
            }
        }
        else -> false
    }

    const val LIFECYCLE_DUPLICATE_WINDOW_MS = 5_000L
}
