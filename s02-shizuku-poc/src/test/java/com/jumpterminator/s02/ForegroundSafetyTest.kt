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
        assertTrue(snapshot.pinnedPackages.isEmpty())
        assertFalse(snapshot.pictureInPictureActive)
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
    fun `active pinned task makes an otherwise single foreground fail closed`() {
        val snapshot = ForegroundSnapshotParser.parse(
            """
            Task{abc #42 type=standard A=10416:example.pip U=0 visible=true mode=pinned translucent=true sz=1}
              mWindowingMode=pinned
              mLastReportedPictureInPictureMode=true
            topResumedActivity=ActivityRecord{def u0 example.target/.MainActivity t43}
            """.trimIndent(),
        )

        assertEquals("example.target/.MainActivity", snapshot.topComponent)
        assertEquals(listOf("example.pip"), snapshot.pinnedPackages)
        assertTrue(snapshot.pictureInPictureActive)
        assertTrue(snapshot.ambiguous)
    }

    @Test
    fun `manifest capability without an active pinned task is not picture in picture`() {
        val snapshot = ForegroundSnapshotParser.parse(
            """
            supportsPictureInPicture=true
            topResumedActivity=ActivityRecord{abc u0 example.target/.MainActivity t43}
            """.trimIndent(),
        )

        assertFalse(snapshot.pictureInPictureActive)
        assertFalse(snapshot.ambiguous)
    }

    @Test
    fun `reported picture in picture transition fails closed without a task package`() {
        val snapshot = ForegroundSnapshotParser.parse(
            """
            mLastReportedPictureInPictureMode=true
            topResumedActivity=ActivityRecord{abc u0 example.target/.MainActivity t43}
            """.trimIndent(),
        )

        assertTrue(snapshot.pinnedPackages.isEmpty())
        assertTrue(snapshot.pictureInPictureActive)
        assertTrue(snapshot.ambiguous)
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
