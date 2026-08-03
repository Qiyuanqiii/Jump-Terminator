package com.jumpterminator.s02

internal data class OwnerDeathDecision(
    val applies: Boolean,
    val revokedReason: String? = null,
    val graceDeadlineElapsedMs: Long? = null,
)

internal data class OwnerAuthorizationSnapshot(
    val sessionId: String?,
    val ownerAttached: Boolean,
    val graceDeadlineElapsedMs: Long?,
    val revokedReason: String?,
)

/**
 * Pure state machine for an owner-bound privileged session.
 *
 * The Android process/Binder layer supplies package stopped state and elapsed
 * realtime. Unknown owner state is deliberately fail-safe.
 */
internal class OwnerAuthorizationPolicy(
    private val crashGraceMs: Long,
) {
    private var sessionId: String? = null
    private var ownerAttached = false
    private var graceDeadlineElapsedMs: Long? = null
    private var revokedReason: String? = null

    init {
        require(crashGraceMs > 0L) { "crashGraceMs must be positive" }
    }

    @Synchronized
    fun begin(sessionId: String) {
        this.sessionId = sessionId
        ownerAttached = true
        graceDeadlineElapsedMs = null
        revokedReason = null
    }

    @Synchronized
    fun ownerDied(
        expectedSessionId: String,
        nowElapsedMs: Long,
        ownerPackageStopped: Boolean?,
    ): OwnerDeathDecision {
        if (sessionId != expectedSessionId) return OwnerDeathDecision(applies = false)
        ownerAttached = false
        return when (ownerPackageStopped) {
            true -> revokeLocked("owner_package_stopped")
            null -> revokeLocked("owner_state_unknown")
            false -> {
                val deadline = saturatedAdd(nowElapsedMs, crashGraceMs)
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
        nowElapsedMs: Long,
        ownerPackageStopped: Boolean?,
    ): String? {
        if (sessionId != expectedSessionId) return "session_mismatch"
        revokedReason?.let { return it }
        when (ownerPackageStopped) {
            true -> return setRevokedLocked("owner_package_stopped")
            null -> return setRevokedLocked("owner_state_unknown")
            false -> Unit
        }
        val deadline = graceDeadlineElapsedMs
        if (!ownerAttached && deadline != null && nowElapsedMs >= deadline) {
            return setRevokedLocked("owner_crash_grace_expired")
        }
        return null
    }

    @Synchronized
    fun expirationReason(expectedSessionId: String, nowElapsedMs: Long): String? {
        if (sessionId != expectedSessionId) return "session_mismatch"
        revokedReason?.let { return it }
        val deadline = graceDeadlineElapsedMs ?: return null
        return if (!ownerAttached && nowElapsedMs >= deadline) {
            setRevokedLocked("owner_crash_grace_expired")
        } else {
            null
        }
    }

    @Synchronized
    fun shouldExitWhenIdle(expectedSessionId: String): Boolean =
        sessionId == expectedSessionId && (!ownerAttached || revokedReason != null)

    @Synchronized
    fun revoke(expectedSessionId: String, reason: String): Boolean {
        if (sessionId != expectedSessionId) return false
        setRevokedLocked(reason)
        return true
    }

    @Synchronized
    fun clear() {
        sessionId = null
        ownerAttached = false
        graceDeadlineElapsedMs = null
        revokedReason = null
    }

    @Synchronized
    fun snapshot(): OwnerAuthorizationSnapshot = OwnerAuthorizationSnapshot(
        sessionId = sessionId,
        ownerAttached = ownerAttached,
        graceDeadlineElapsedMs = graceDeadlineElapsedMs,
        revokedReason = revokedReason,
    )

    private fun revokeLocked(reason: String): OwnerDeathDecision {
        setRevokedLocked(reason)
        return OwnerDeathDecision(applies = true, revokedReason = reason)
    }

    private fun setRevokedLocked(reason: String): String {
        revokedReason = reason
        graceDeadlineElapsedMs = null
        return reason
    }

    private fun saturatedAdd(left: Long, right: Long): Long =
        if (left > Long.MAX_VALUE - right) Long.MAX_VALUE else left + right
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
