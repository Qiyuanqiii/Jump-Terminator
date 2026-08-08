package com.jumpterminator.s02

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class OwnerAuthorizationPolicyTest {
    @Test
    fun `force stopped owner is revoked immediately after binder death`() {
        val policy = policyWithActive()

        val decision = policy.ownerDied(SESSION_A, CAPABILITY_A, 1_000L, true)

        assertTrue(decision.applies)
        assertEquals("owner_package_stopped", decision.revokedReason)
        assertEquals(
            "owner_package_stopped",
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_A,
                1_001L,
                environment(ownerPackageStopped = true),
            ),
        )
    }

    @Test
    fun `ordinary crash receives only the bounded grace interval`() {
        val policy = policyWithActive(leaseDurationMs = 20_000L)

        val decision = policy.ownerDied(SESSION_A, CAPABILITY_A, 1_000L, false)

        assertEquals(11_000L, decision.graceDeadlineElapsedMs)
        assertNull(
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_A,
                10_999L,
                environment(),
            ),
        )
        assertEquals(
            "owner_crash_grace_expired",
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_A,
                11_000L,
                environment(),
            ),
        )
    }

    @Test
    fun `lease is an upper bound on crash grace`() {
        val policy = policyWithActive(leaseDurationMs = 5_000L)

        val decision = policy.ownerDied(SESSION_A, CAPABILITY_A, 1_000L, false)

        assertEquals(5_000L, decision.graceDeadlineElapsedMs)
        assertEquals(
            "authorization_lease_expired",
            policy.expirationReason(SESSION_A, CAPABILITY_A, 5_000L),
        )
    }

    @Test
    fun `action check rejects force stop even before death callback runs`() {
        val policy = policyWithActive()

        assertEquals(
            "owner_package_stopped",
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_A,
                1_000L,
                environment(ownerPackageStopped = true),
            ),
        )
    }

    @Test
    fun `unknown package state fails safe`() {
        val policy = policyWithActive()

        assertEquals(
            "owner_state_unknown",
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_A,
                1_000L,
                environment(ownerPackageStopped = null),
            ),
        )
    }

    @Test
    fun `final foreground mismatch fails safe`() {
        val policy = policyWithActive()

        assertEquals(
            "target_not_foreground",
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_A,
                1_000L,
                environment(topComponent = SOURCE_COMPONENT),
            ),
        )
    }

    @Test
    fun `unknown final foreground fails safe`() {
        val policy = policyWithActive()

        assertEquals(
            "foreground_state_unknown",
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_A,
                1_000L,
                environment(topComponent = "unknown"),
            ),
        )
    }

    @Test
    fun `stale owner death cannot revoke a newer session`() {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        assertTrue(policy.begin(authorization(SESSION_A, CAPABILITY_A)).accepted)
        assertTrue(policy.begin(authorization(SESSION_B, CAPABILITY_B)).accepted)

        val decision = policy.ownerDied(SESSION_A, CAPABILITY_A, 1_000L, true)

        assertFalse(decision.applies)
        assertNull(
            policy.actionDenialReason(
                SESSION_B,
                CAPABILITY_B,
                1_001L,
                environment(),
            ),
        )
    }

    @Test
    fun `replayed session id is rejected`() {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        assertTrue(policy.begin(authorization(SESSION_A, CAPABILITY_A)).accepted)

        val replay = policy.begin(authorization(SESSION_A, CAPABILITY_B))

        assertFalse(replay.accepted)
        assertEquals("session_replayed", replay.denialReason)
    }

    @Test
    fun `replayed capability is rejected`() {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        assertTrue(policy.begin(authorization(SESSION_A, CAPABILITY_A)).accepted)

        val replay = policy.begin(authorization(SESSION_B, CAPABILITY_A))

        assertFalse(replay.accepted)
        assertEquals("capability_replayed", replay.denialReason)
    }

    @Test
    fun `bounded replay history fails closed when exhausted`() {
        val policy = OwnerAuthorizationPolicy(
            crashGraceMs = 10_000L,
            replayHistoryLimit = 1,
        )
        assertTrue(policy.begin(authorization(SESSION_A, CAPABILITY_A)).accepted)

        val exhausted = policy.begin(authorization(SESSION_B, CAPABILITY_B))

        assertFalse(exhausted.accepted)
        assertEquals("replay_history_exhausted", exhausted.denialReason)
    }

    @Test
    fun `monotonic lease expiry denies action`() {
        val policy = policyWithActive(leaseDurationMs = 5_000L)

        assertEquals(
            "authorization_lease_expired",
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_A,
                5_000L,
                environment(),
            ),
        )
    }

    @Test
    fun `wrong capability cannot use active session`() {
        val policy = policyWithActive()

        assertEquals(
            "capability_mismatch",
            policy.actionDenialReason(
                SESSION_A,
                CAPABILITY_B,
                1_000L,
                environment(),
            ),
        )
    }

    @Test
    fun `authorized launcher runs exactly once`() {
        val policy = policyWithActive()
        var launches = 0

        val result = policy.launchAuthorized(
            SESSION_A,
            CAPABILITY_A,
            nowElapsedProvider = { 1_000L },
            environmentProvider = { environment() },
            launcher = {
                launches += 1
                "started"
            },
        )

        assertTrue(result.launched)
        assertEquals("started", result.value)
        assertEquals(1, launches)
    }

    @Test
    fun `revocation visible at final serialization point prevents launch`() {
        val policy = policyWithActive()
        var launches = 0

        val result = policy.launchAuthorized(
            SESSION_A,
            CAPABILITY_A,
            nowElapsedProvider = { 1_000L },
            environmentProvider = {
                assertTrue(policy.revoke(SESSION_A, CAPABILITY_A, "race_revoked"))
                environment()
            },
            launcher = {
                launches += 1
                "started"
            },
        )

        assertFalse(result.launched)
        assertEquals("race_revoked", result.denialReason)
        assertEquals(0, launches)
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

    @Test
    fun `rule snapshot commits to capability without exposing it`() {
        val first = authorization(SESSION_A, CAPABILITY_A)
        val second = authorization(SESSION_A, CAPABILITY_B)

        assertNotEquals(first.capabilityFingerprint, second.capabilityFingerprint)
        assertNotEquals(first.ruleSnapshotSha256, second.ruleSnapshotSha256)
        assertFalse(first.capabilityFingerprint.contains(CAPABILITY_A))
    }

    private fun policyWithActive(leaseDurationMs: Long = 90_000L): OwnerAuthorizationPolicy {
        val policy = OwnerAuthorizationPolicy(crashGraceMs = 10_000L)
        assertTrue(
            policy.begin(
                authorization(
                    SESSION_A,
                    CAPABILITY_A,
                    leaseDurationMs = leaseDurationMs,
                ),
            ).accepted,
        )
        return policy
    }

    private fun authorization(
        sessionId: String,
        capability: String,
        leaseDurationMs: Long = 90_000L,
    ): MonitorAuthorization = MonitorAuthorizationFactory.create(
        sessionId = sessionId,
        capability = capability,
        owner = OWNER,
        scenario = "block",
        requestedBlock = 1,
        requestedAllowed = 0,
        armed = true,
        sourceComponent = SOURCE_COMPONENT,
        targetComponent = TARGET_COMPONENT,
        action = "BACK",
        startedElapsedMs = 0L,
        leaseDurationMs = leaseDurationMs,
    )

    private fun environment(
        ownerPackageStopped: Boolean? = false,
        topComponent: String = TARGET_COMPONENT,
    ) = ActionEnvironment(ownerPackageStopped, topComponent)

    private companion object {
        const val SESSION_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        const val SESSION_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        const val CAPABILITY_A =
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        const val CAPABILITY_B =
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        const val SOURCE_COMPONENT = "com.jumpterminator.testsource/.SourceActivity"
        const val TARGET_COMPONENT = "com.jumpterminator.testtarget/.TargetActivity"
        val OWNER = OwnerIdentity(
            uid = 10_420,
            userId = 0,
            packageName = "com.jumpterminator.s02",
            signingCertificateSha256 = listOf("c".repeat(64)),
        )
    }
}

class OwnerIdentityValidatorTest {
    @Test
    fun `binder identity resolves fixed package and normalized signing certificate`() {
        val identity = OwnerIdentityValidator.resolve(
            callingUid = 10_420,
            ownerUserId = 0,
            expectedPackage = "com.jumpterminator.s02",
            packagesForUid = listOf("com.jumpterminator.s02"),
            signingCertificateSha256 = listOf("A".repeat(64), "a".repeat(64)),
        )

        assertEquals(10_420, identity.uid)
        assertEquals(0, identity.userId)
        assertEquals(listOf("a".repeat(64)), identity.signingCertificateSha256)
    }

    @Test
    fun `uid without fixed owner package is rejected`() {
        val error = assertThrows(SecurityException::class.java) {
            OwnerIdentityValidator.resolve(
                callingUid = 10_421,
                ownerUserId = 0,
                expectedPackage = "com.jumpterminator.s02",
                packagesForUid = listOf("example.attacker"),
                signingCertificateSha256 = listOf("a".repeat(64)),
            )
        }

        assertEquals("caller_package_mismatch", error.message)
    }

    @Test
    fun `missing signing identity is rejected`() {
        val error = assertThrows(SecurityException::class.java) {
            OwnerIdentityValidator.resolve(
                callingUid = 10_420,
                ownerUserId = 0,
                expectedPackage = "com.jumpterminator.s02",
                packagesForUid = listOf("com.jumpterminator.s02"),
                signingCertificateSha256 = emptyList(),
            )
        }

        assertEquals("owner_signing_identity_unknown", error.message)
    }
}
