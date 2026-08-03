package com.jumpterminator.s02

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OwnerAuthorizationPolicyTest {
    @Test
    fun `force stopped owner is revoked immediately after binder death`() {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        policy.begin("session-a")

        val decision = policy.ownerDied("session-a", 1_000L, ownerPackageStopped = true)

        assertTrue(decision.applies)
        assertEquals("owner_package_stopped", decision.revokedReason)
        assertEquals(
            "owner_package_stopped",
            policy.actionDenialReason("session-a", 1_001L, ownerPackageStopped = true),
        )
    }

    @Test
    fun `ordinary crash receives only the bounded grace interval`() {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        policy.begin("session-a")

        val decision = policy.ownerDied("session-a", 1_000L, ownerPackageStopped = false)

        assertEquals(11_000L, decision.graceDeadlineElapsedMs)
        assertNull(policy.actionDenialReason("session-a", 10_999L, ownerPackageStopped = false))
        assertEquals(
            "owner_crash_grace_expired",
            policy.actionDenialReason("session-a", 11_000L, ownerPackageStopped = false),
        )
    }

    @Test
    fun `action check rejects force stop even before death callback runs`() {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        policy.begin("session-a")

        assertEquals(
            "owner_package_stopped",
            policy.actionDenialReason("session-a", 1_000L, ownerPackageStopped = true),
        )
    }

    @Test
    fun `unknown package state fails safe`() {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        policy.begin("session-a")

        assertEquals(
            "owner_state_unknown",
            policy.actionDenialReason("session-a", 1_000L, ownerPackageStopped = null),
        )
    }

    @Test
    fun `stale owner death cannot revoke a newer session`() {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        policy.begin("session-a")
        policy.begin("session-b")

        val decision = policy.ownerDied("session-a", 1_000L, ownerPackageStopped = true)

        assertFalse(decision.applies)
        assertNull(policy.actionDenialReason("session-b", 1_001L, ownerPackageStopped = false))
    }

    @Test
    fun `parser selects stopped state for the requested user`() {
        val output = """
            User 0: installed=true stopped=false enabled=0
            User 10: installed=true stopped=true enabled=0
            User 10:
        """.trimIndent()

        assertEquals(false, PackageStoppedStateParser.parse(output, 0))
        assertEquals(true, PackageStoppedStateParser.parse(output, 10))
        assertNull(PackageStoppedStateParser.parse(output, 11))
    }
}
