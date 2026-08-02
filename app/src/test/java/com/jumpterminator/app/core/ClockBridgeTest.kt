package com.jumpterminator.app.core

import org.junit.Assert.assertEquals
import org.junit.Test

class ClockBridgeTest {
    @Test
    fun `maps wall clock timestamps into elapsed realtime`() {
        val snapshot = ClockSnapshot(wallClockMs = 10_000L, elapsedRealtimeMs = 4_000L)

        assertEquals(3_750L, snapshot.wallToElapsed(9_750L))
        assertEquals(4_200L, snapshot.wallToElapsed(10_200L))
    }

    @Test
    fun `detects wall clock jump independently of elapsed time`() {
        val snapshot = ClockSnapshot(wallClockMs = 10_000L, elapsedRealtimeMs = 4_000L)

        assertEquals(0L, snapshot.driftAt(nowWallClockMs = 11_000L, nowElapsedRealtimeMs = 5_000L))
        assertEquals(7_000L, snapshot.driftAt(nowWallClockMs = 18_000L, nowElapsedRealtimeMs = 5_000L))
    }
}
