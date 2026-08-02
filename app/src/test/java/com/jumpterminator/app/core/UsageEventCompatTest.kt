package com.jumpterminator.app.core

import org.junit.Assert.assertEquals
import org.junit.Test

class UsageEventCompatTest {
    @Test
    fun `Android 9 maps legacy foreground and background events`() {
        assertEquals(
            UsageEventCompat.Signal.FOREGROUND,
            UsageEventCompat.classify(28, UsageEventCompat.MOVE_TO_FOREGROUND),
        )
        assertEquals(
            UsageEventCompat.Signal.BACKGROUND,
            UsageEventCompat.classify(28, UsageEventCompat.MOVE_TO_BACKGROUND),
        )
        assertEquals(
            UsageEventCompat.Signal.IGNORE,
            UsageEventCompat.classify(28, UsageEventCompat.ACTIVITY_RESUMED),
        )
    }

    @Test
    fun `Android 10 and newer map activity lifecycle events with legacy fallback`() {
        assertEquals(
            UsageEventCompat.Signal.FOREGROUND,
            UsageEventCompat.classify(29, UsageEventCompat.ACTIVITY_RESUMED),
        )
        assertEquals(
            UsageEventCompat.Signal.BACKGROUND,
            UsageEventCompat.classify(29, UsageEventCompat.ACTIVITY_PAUSED),
        )
        assertEquals(
            UsageEventCompat.Signal.FOREGROUND,
            UsageEventCompat.classify(36, UsageEventCompat.MOVE_TO_FOREGROUND),
        )
    }

    @Test
    fun `nearby activity resumed does not override a move to foreground`() {
        assertEquals(
            false,
            UsageEventCompat.shouldDriveForeground(
                eventType = UsageEventCompat.ACTIVITY_RESUMED,
                eventWallClockMs = 11_500L,
                lastMoveToForegroundWallClockMs = 10_000L,
            ),
        )
    }

    @Test
    fun `activity resumed remains a fallback when no nearby move exists`() {
        assertEquals(
            true,
            UsageEventCompat.shouldDriveForeground(
                eventType = UsageEventCompat.ACTIVITY_RESUMED,
                eventWallClockMs = 20_000L,
                lastMoveToForegroundWallClockMs = null,
            ),
        )
        assertEquals(
            true,
            UsageEventCompat.shouldDriveForeground(
                eventType = UsageEventCompat.ACTIVITY_RESUMED,
                eventWallClockMs = 20_000L,
                lastMoveToForegroundWallClockMs = 10_000L,
            ),
        )
    }

    @Test
    fun `collector warmup events never drive foreground state`() {
        assertEquals(
            false,
            UsageEventCompat.shouldDriveForeground(
                eventType = UsageEventCompat.MOVE_TO_FOREGROUND,
                eventWallClockMs = 9_999L,
                lastMoveToForegroundWallClockMs = null,
                minimumActionableWallClockMs = 10_000L,
            ),
        )
        assertEquals(
            false,
            UsageEventCompat.shouldDriveForeground(
                eventType = UsageEventCompat.ACTIVITY_RESUMED,
                eventWallClockMs = 9_999L,
                lastMoveToForegroundWallClockMs = null,
                minimumActionableWallClockMs = 10_000L,
            ),
        )
    }
}
