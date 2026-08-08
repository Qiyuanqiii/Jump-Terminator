package com.jumpterminator.s02

import java.nio.charset.StandardCharsets
import java.security.MessageDigest

internal data class OwnerDeathDecision(
    val applies: Boolean,
    val revokedReason: String? = null,
    val graceDeadlineElapsedMs: Long? = null,
)

internal data class AuthorizationBeginDecision(
    val accepted: Boolean,
    val denialReason: String? = null,
)

internal data class OwnerAuthorizationSnapshot(
    val sessionId: String?,
    val capabilityFingerprint: String?,
    val owner: OwnerIdentity?,
    val ownerAttached: Boolean,
    val leaseDeadlineElapsedMs: Long?,
    val graceDeadlineElapsedMs: Long?,
    val ruleSnapshotSha256: String?,
    val revokedReason: String?,
    val consumedSessions: Int,
)

/**
 * Pure state machine for a caller-authenticated, capability-bound privileged session.
 *
 * The Android Binder layer supplies a server-derived owner identity. The final
 * package/foreground check and action launcher are invoked while holding this
 * policy's monitor, which defines the in-process authorization linearization point.
 */
internal class OwnerAuthorizationPolicy(
    private val crashGraceMs: Long,
    private val replayHistoryLimit: Int = DEFAULT_REPLAY_HISTORY_LIMIT,
) {
    private var active: MonitorAuthorization? = null
    private var ownerAttached = false
    private var graceDeadlineElapsedMs: Long? = null
    private var revokedReason: String? = null
    private val consumedSessionIds = LinkedHashSet<String>()
    private val consumedCapabilityFingerprints = LinkedHashSet<String>()

    init {
        require(crashGraceMs > 0L) { "crashGraceMs must be positive" }
        require(replayHistoryLimit > 0) { "replayHistoryLimit must be positive" }
    }

    @Synchronized
    fun begin(authorization: MonitorAuthorization): AuthorizationBeginDecision {
        if (authorization.sessionId in consumedSessionIds) {
            return AuthorizationBeginDecision(false, "session_replayed")
        }
        if (authorization.capabilityFingerprint in consumedCapabilityFingerprints) {
            return AuthorizationBeginDecision(false, "capability_replayed")
        }
        if (consumedSessionIds.size >= replayHistoryLimit) {
            return AuthorizationBeginDecision(false, "replay_history_exhausted")
        }
        consumedSessionIds += authorization.sessionId
        consumedCapabilityFingerprints += authorization.capabilityFingerprint
        active = authorization
        ownerAttached = true
        graceDeadlineElapsedMs = null
        revokedReason = null
        return AuthorizationBeginDecision(true)
    }

    @Synchronized
    fun ownerDied(
        expectedSessionId: String,
        expectedCapability: String,
        nowElapsedMs: Long,
        ownerPackageStopped: Boolean?,
    ): OwnerDeathDecision {
        if (!matchesActiveLocked(expectedSessionId, expectedCapability)) {
            return OwnerDeathDecision(applies = false)
        }
        ownerAttached = false
        if (nowElapsedMs >= requireActiveLocked().leaseDeadlineElapsedMs) {
            return revokeLocked("authorization_lease_expired")
        }
        return when (ownerPackageStopped) {
            true -> revokeLocked("owner_package_stopped")
            null -> revokeLocked("owner_state_unknown")
            false -> {
                val deadline = minOf(
                    saturatedAdd(nowElapsedMs, crashGraceMs),
                    requireActiveLocked().leaseDeadlineElapsedMs,
                )
                graceDeadlineElapsedMs = deadline
                OwnerDeathDecision(
                    applies = true,
                    graceDeadlineElapsedMs = deadline,
                )
            }
        }
    }

    @Synchronized
    fun actionDenialReason(
        expectedSessionId: String,
        expectedCapability: String,
        nowElapsedMs: Long,
        environment: ActionEnvironment,
    ): String? = actionDenialReasonLocked(
        expectedSessionId,
        expectedCapability,
        nowElapsedMs,
        environment,
    )

    @Synchronized
    fun <T> launchAuthorized(
        expectedSessionId: String,
        expectedCapability: String,
        nowElapsedProvider: () -> Long,
        environmentProvider: () -> ActionEnvironment,
        launcher: () -> T,
    ): AuthorizedLaunch<T> {
        val environment = try {
            environmentProvider()
        } catch (_: Throwable) {
            ActionEnvironment(
                ownerPackageStopped = null,
                topComponent = "unknown",
            )
        }
        val denialReason = actionDenialReasonLocked(
            expectedSessionId,
            expectedCapability,
            nowElapsedProvider(),
            environment,
        )
        if (denialReason != null) {
            return AuthorizedLaunch(denialReason = denialReason)
        }
        return AuthorizedLaunch(value = launcher())
    }

    @Synchronized
    fun expirationReason(
        expectedSessionId: String,
        expectedCapability: String,
        nowElapsedMs: Long,
    ): String? {
        if (!matchesActiveLocked(expectedSessionId, expectedCapability)) {
            return mismatchReasonLocked(expectedSessionId, expectedCapability)
        }
        revokedReason?.let { return it }
        val authorization = requireActiveLocked()
        if (nowElapsedMs >= authorization.leaseDeadlineElapsedMs) {
            return setRevokedLocked("authorization_lease_expired")
        }
        val graceDeadline = graceDeadlineElapsedMs
        return if (!ownerAttached && graceDeadline != null && nowElapsedMs >= graceDeadline) {
            setRevokedLocked("owner_crash_grace_expired")
        } else {
            null
        }
    }

    @Synchronized
    fun shouldExitWhenIdle(expectedSessionId: String, expectedCapability: String): Boolean =
        matchesActiveLocked(expectedSessionId, expectedCapability) &&
            (!ownerAttached || revokedReason != null)

    @Synchronized
    fun revoke(
        expectedSessionId: String,
        expectedCapability: String,
        reason: String,
    ): Boolean {
        if (!matchesActiveLocked(expectedSessionId, expectedCapability)) return false
        setRevokedLocked(reason)
        return true
    }

    @Synchronized
    fun revokeActive(reason: String): Boolean {
        if (active == null) return false
        setRevokedLocked(reason)
        return true
    }

    @Synchronized
    fun clearActive() {
        active = null
        ownerAttached = false
        graceDeadlineElapsedMs = null
        revokedReason = null
    }

    @Synchronized
    fun snapshot(): OwnerAuthorizationSnapshot = OwnerAuthorizationSnapshot(
        sessionId = active?.sessionId,
        capabilityFingerprint = active?.capabilityFingerprint,
        owner = active?.owner,
        ownerAttached = ownerAttached,
        leaseDeadlineElapsedMs = active?.leaseDeadlineElapsedMs,
        graceDeadlineElapsedMs = graceDeadlineElapsedMs,
        ruleSnapshotSha256 = active?.ruleSnapshotSha256,
        revokedReason = revokedReason,
        consumedSessions = consumedSessionIds.size,
    )

    private fun actionDenialReasonLocked(
        expectedSessionId: String,
        expectedCapability: String,
        nowElapsedMs: Long,
        environment: ActionEnvironment,
    ): String? {
        if (!matchesActiveLocked(expectedSessionId, expectedCapability)) {
            return mismatchReasonLocked(expectedSessionId, expectedCapability)
        }
        revokedReason?.let { return it }
        val authorization = requireActiveLocked()
        if (nowElapsedMs >= authorization.leaseDeadlineElapsedMs) {
            return setRevokedLocked("authorization_lease_expired")
        }
        val graceDeadline = graceDeadlineElapsedMs
        if (!ownerAttached && graceDeadline != null && nowElapsedMs >= graceDeadline) {
            return setRevokedLocked("owner_crash_grace_expired")
        }
        when (environment.ownerPackageStopped) {
            true -> return setRevokedLocked("owner_package_stopped")
            null -> return setRevokedLocked("owner_state_unknown")
            false -> Unit
        }
        if (environment.topComponent == "unknown") {
            return setRevokedLocked("foreground_state_unknown")
        }
        if (environment.topComponent != authorization.targetComponent) {
            return setRevokedLocked("target_not_foreground")
        }
        return null
    }

    private fun matchesActiveLocked(
        expectedSessionId: String,
        expectedCapability: String,
    ): Boolean {
        val authorization = active ?: return false
        return authorization.sessionId == expectedSessionId &&
            secureEquals(authorization.capability, expectedCapability)
    }

    private fun mismatchReasonLocked(
        expectedSessionId: String,
        expectedCapability: String,
    ): String {
        val authorization = active ?: return "session_missing"
        if (authorization.sessionId != expectedSessionId) return "session_mismatch"
        return if (!secureEquals(authorization.capability, expectedCapability)) {
            "capability_mismatch"
        } else {
            "session_mismatch"
        }
    }

    private fun requireActiveLocked(): MonitorAuthorization =
        checkNotNull(active) { "active authorization is missing" }

    private fun revokeLocked(reason: String): OwnerDeathDecision {
        setRevokedLocked(reason)
        return OwnerDeathDecision(applies = true, revokedReason = reason)
    }

    private fun setRevokedLocked(reason: String): String {
        revokedReason = reason
        graceDeadlineElapsedMs = null
        return reason
    }

    private fun secureEquals(left: String, right: String): Boolean =
        MessageDigest.isEqual(
            left.toByteArray(StandardCharsets.UTF_8),
            right.toByteArray(StandardCharsets.UTF_8),
        )

    private fun saturatedAdd(left: Long, right: Long): Long =
        if (left > Long.MAX_VALUE - right) Long.MAX_VALUE else left + right

    private companion object {
        const val DEFAULT_REPLAY_HISTORY_LIMIT = 256
    }
}

internal object PackageStoppedStateParser {
    fun parse(output: String, userId: Int): Boolean? {
        val userLine = Regex("(?m)^\\s*User\\s+${Regex.escape(userId.toString())}:\\s*(.*)$")
        val stoppedValue = Regex("\\bstopped=(true|false)\\b")
        for (match in userLine.findAll(output)) {
            val value = stoppedValue.find(match.groupValues[1])?.groupValues?.getOrNull(1)
            if (value != null) return value == "true"
        }
        return null
    }
}
