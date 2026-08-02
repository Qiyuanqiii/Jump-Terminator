package com.jumpterminator.app.core

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ForegroundSignalGateTest {
    @Test
    fun `live signal drives tracker`() {
        assertTrue(ForegroundSignalGate.shouldDriveTracker(1_000L, 1_100L))
    }

    @Test
    fun `signal at age limit drives tracker`() {
        assertTrue(ForegroundSignalGate.shouldDriveTracker(1_000L, 1_500L))
    }

    @Test
    fun `signal older than age limit is diagnostic only`() {
        assertFalse(ForegroundSignalGate.shouldDriveTracker(1_000L, 1_501L))
    }

    @Test
    fun `small future skew does not look stale`() {
        assertTrue(ForegroundSignalGate.shouldDriveTracker(1_100L, 1_000L))
    }

    @Test
    fun `usage signal matching live accessibility window is consistent`() {
        assertTrue(
            ForegroundSignalGate.isUsageSignalConsistent(
                signaledPackage = "com.example.source",
                liveAccessibilityPackage = "com.example.source",
            ),
        )
    }

    @Test
    fun `usage signal remains a fallback when live window is unavailable`() {
        assertTrue(
            ForegroundSignalGate.isUsageSignalConsistent(
                signaledPackage = "com.example.source",
                liveAccessibilityPackage = null,
            ),
        )
    }

    @Test
    fun `usage signal conflicting with live accessibility window is rejected`() {
        assertFalse(
            ForegroundSignalGate.isUsageSignalConsistent(
                signaledPackage = "com.example.stale",
                liveAccessibilityPackage = "com.example.visible",
            ),
        )
    }
}
