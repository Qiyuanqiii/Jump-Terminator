package com.jumpterminator.s02

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ForegroundSafetyTest {
    @Test
    fun `single resumed activity is unambiguous`() {
        val snapshot = ForegroundSnapshotParser.parse(
            "topResumedActivity=ActivityRecord{abc u0 example.source/.MainActivity t12}",
        )

        assertEquals("example.source/.MainActivity", snapshot.topComponent)
        assertEquals(listOf("example.source/.MainActivity"), snapshot.resumedComponents)
        assertFalse(snapshot.ambiguous)
    }

    @Test
    fun `split screen resumed activities are ambiguous`() {
        val snapshot = ForegroundSnapshotParser.parse(
            """
            topResumedActivity=ActivityRecord{abc u0 example.target/.MainActivity t13}
            topResumedActivity=ActivityRecord{def u0 example.source/.MainActivity t12}
            """.trimIndent(),
        )

        assertEquals("example.target/.MainActivity", snapshot.topComponent)
        assertEquals(2, snapshot.resumedComponents.size)
        assertTrue(snapshot.ambiguous)
    }

    @Test
    fun `missing resumed activity is unknown`() {
        val snapshot = ForegroundSnapshotParser.parse("no resumed activity")

        assertEquals("unknown", snapshot.topComponent)
        assertTrue(snapshot.resumedComponents.isEmpty())
        assertFalse(snapshot.ambiguous)
    }

    @Test
    fun `awake unlocked device is actionable`() {
        val state = DeviceInteractionStateParser.parse(
            """
            mWakefulness=Awake
            mInputRestricted=false
            mDreamingLockscreen=false
            """.trimIndent(),
        )

        assertEquals(true, state.interactive)
        assertEquals(false, state.keyguardLocked)
    }

    @Test
    fun `asleep keyguard device is not actionable`() {
        val state = DeviceInteractionStateParser.parse(
            """
            mWakefulness=Asleep
            mInputRestricted=true
            mDreamingLockscreen=true
            """.trimIndent(),
        )

        assertEquals(false, state.interactive)
        assertEquals(true, state.keyguardLocked)
    }

    @Test
    fun `missing device state fails closed as unknown`() {
        val state = DeviceInteractionStateParser.parse("unrecognized")

        assertNull(state.interactive)
        assertNull(state.keyguardLocked)
    }
}
