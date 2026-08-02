package com.jumpterminator.app.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TransitionTrackerTest {
    private fun tracker() = TransitionTracker(
        protectedSource = "source",
        contextBreakPackages = setOf("launcher", "systemui", "self"),
    )

    @Test
    fun `creates one candidate for a fresh source to target transition`() {
        val tracker = tracker()
        assertNull(tracker.observeForeground("source", 1_000L, "accessibility"))

        val candidate = tracker.observeForeground("target", 1_320L, "usage_stats")

        assertEquals("source", candidate?.sourcePackage)
        assertEquals("target", candidate?.targetPackage)
        assertEquals(320L, candidate?.transitionLatencyMs)
        assertNull(tracker.observeForeground("other", 1_500L, "accessibility"))
    }

    @Test
    fun `same package changes never create a candidate`() {
        val tracker = tracker()
        assertNull(tracker.observeForeground("source", 1_000L, "accessibility"))
        assertNull(tracker.observeForeground("source", 1_100L, "usage_stats"))
    }

    @Test
    fun `source remains eligible while continuously foreground`() {
        val tracker = tracker()
        tracker.observeForeground("source", 1_000L, "accessibility")

        val candidate = tracker.observeForeground("target", 36_000L, "accessibility")

        assertEquals("target", candidate?.targetPackage)
        assertEquals(35_000L, candidate?.transitionLatencyMs)
    }

    @Test
    fun `launcher breaks source context`() {
        val tracker = tracker()
        tracker.observeForeground("source", 1_000L, "accessibility")
        tracker.observeForeground("launcher", 1_100L, "accessibility")

        assertNull(tracker.observeForeground("target", 1_200L, "accessibility"))
    }

    @Test
    fun `materially out of order usage event is ignored`() {
        val tracker = tracker()
        tracker.observeForeground("source", 2_000L, "accessibility")
        tracker.observeForeground("target", 2_200L, "accessibility")

        assertNull(tracker.observeForeground("source", 1_000L, "usage_stats"))
        assertEquals("target", tracker.currentPackage())
    }

    @Test
    fun `slightly delayed source signal cannot reopen consumed context`() {
        val tracker = tracker()
        tracker.observeForeground("source", 2_000L, "accessibility")
        tracker.observeForeground("target", 2_200L, "accessibility")
        tracker.observeForeground("source", 2_150L, "usage_stats")

        assertNull(tracker.observeForeground("target", 2_250L, "usage_stats"))
        assertEquals("target", tracker.currentPackage())
    }

    @Test
    fun `live snapshot may reseed source after fail-open reset`() {
        val tracker = tracker()
        tracker.observeForeground("source", 1_000L, "accessibility")
        tracker.reset()
        assertNull(tracker.observeForeground("source", 2_000L, "stale_recovery_snapshot"))

        val candidate = tracker.observeForeground("target", 2_100L, "accessibility")

        assertEquals("source", candidate?.sourcePackage)
        assertEquals("target", candidate?.targetPackage)
    }
}
