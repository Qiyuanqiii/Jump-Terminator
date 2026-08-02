package com.jumpterminator.app.core

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class S0PolicyTest {
    private fun input(
        mode: S0Mode = S0Mode.ARMED_BLOCK,
        source: String = S0Policy.HARNESS_SOURCE_PACKAGE,
        target: String = S0Policy.HARNESS_TARGET_PACKAGE,
        configuredSource: String = S0Policy.HARNESS_SOURCE_PACKAGE,
        configuredTarget: String = S0Policy.HARNESS_TARGET_PACKAGE,
        identityKnown: Boolean = true,
        safePackages: Set<String> = setOf("systemui", "launcher"),
    ) = S0PolicyInput(
        mode = mode,
        sourcePackage = source,
        targetPackage = target,
        configuredSourcePackage = configuredSource,
        configuredTargetPackage = configuredTarget,
        identityKnown = identityKnown,
        safePackages = safePackages,
    )

    @Test
    fun `record only mode never acts`() {
        assertFalse(S0Policy.evaluate(input(mode = S0Mode.RECORD_ONLY)).shouldAct)
    }

    @Test
    fun `unknown user identity never acts`() {
        assertFalse(S0Policy.evaluate(input(identityKnown = false)).shouldAct)
    }

    @Test
    fun `non harness target never acts even when configured`() {
        assertFalse(
            S0Policy.evaluate(
                input(target = "com.example.real", configuredTarget = "com.example.real"),
            ).shouldAct,
        )
    }

    @Test
    fun `safe package never acts`() {
        assertFalse(
            S0Policy.evaluate(
                input(safePackages = setOf(S0Policy.HARNESS_TARGET_PACKAGE)),
            ).shouldAct,
        )
    }

    @Test
    fun `exact armed harness transition may act`() {
        assertTrue(S0Policy.evaluate(input()).shouldAct)
    }
}
