package com.jumpterminator.s02

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AutomationCommandGateTest {
    @Test
    fun `exported launcher cannot submit automation commands`() {
        assertFalse(
            AutomationCommandGate.allows(AutomationCommandIngress.PUBLIC_LAUNCHER),
        )
    }

    @Test
    fun `adb debug activity can submit automation commands`() {
        assertTrue(
            AutomationCommandGate.allows(
                AutomationCommandIngress.ADB_DEBUG_AUTOMATION,
            ),
        )
    }
}
