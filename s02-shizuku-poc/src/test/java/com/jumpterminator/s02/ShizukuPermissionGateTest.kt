package com.jumpterminator.s02

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ShizukuPermissionGateTest {
    @Test
    fun `accepts only when platform and Shizuku grants agree`() {
        assertTrue(
            ShizukuPermissionGate.isGranted(
                platformPermissionGranted = true,
                shizukuPermissionGranted = true,
            ),
        )
    }

    @Test
    fun `rejects stale Shizuku grant after platform revocation`() {
        assertFalse(
            ShizukuPermissionGate.isGranted(
                platformPermissionGranted = false,
                shizukuPermissionGranted = true,
            ),
        )
    }

    @Test
    fun `rejects when Shizuku has not authorized the app`() {
        assertFalse(
            ShizukuPermissionGate.isGranted(
                platformPermissionGranted = true,
                shizukuPermissionGranted = false,
            ),
        )
    }

    @Test
    fun `rejects when neither grant exists`() {
        assertFalse(
            ShizukuPermissionGate.isGranted(
                platformPermissionGranted = false,
                shizukuPermissionGranted = false,
            ),
        )
    }
}
