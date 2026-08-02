package com.jumpterminator.app.core

data class TransitionCandidate(
    val sourcePackage: String,
    val targetPackage: String,
    val sourceEnteredElapsedMs: Long,
    val targetEnteredElapsedMs: Long,
    val evidence: String,
) {
    val transitionLatencyMs: Long
        get() = targetEnteredElapsedMs - sourceEnteredElapsedMs
}

/**
 * Minimal S0 attribution state machine. It creates at most one candidate per
 * observed source foreground session and refuses materially out-of-order
 * observations. Source context remains valid while the source is still the
 * last observed foreground package; explicit context breakers invalidate it.
 */
class TransitionTracker(
    protectedSource: String,
    private var contextBreakPackages: Set<String>,
) {
    private var protectedSourcePackage = protectedSource
    private var sourceEnteredElapsedMs: Long? = null
    private var candidateConsumed = false
    private var currentPackageName: String? = null
    private var latestObservationElapsedMs = Long.MIN_VALUE

    @Synchronized
    fun updateConfiguration(protectedSource: String, breakers: Set<String>) {
        if (protectedSourcePackage != protectedSource) {
            protectedSourcePackage = protectedSource
            clearSourceContext()
        }
        contextBreakPackages = breakers
    }

    @Synchronized
    fun observeForeground(
        packageName: String,
        eventElapsedMs: Long,
        evidence: String,
    ): TransitionCandidate? {
        val observedPackage = packageName.trim()
        if (observedPackage.isEmpty()) return null

        // A delayed second signal must never rewind foreground state or reopen
        // a source context that a newer observation has already consumed.
        if (latestObservationElapsedMs != Long.MIN_VALUE && eventElapsedMs < latestObservationElapsedMs) {
            return null
        }
        latestObservationElapsedMs = maxOf(latestObservationElapsedMs, eventElapsedMs)

        if (observedPackage == currentPackageName) return null

        if (observedPackage in contextBreakPackages) {
            currentPackageName = observedPackage
            clearSourceContext()
            return null
        }

        if (observedPackage == protectedSourcePackage) {
            currentPackageName = observedPackage
            sourceEnteredElapsedMs = eventElapsedMs
            candidateConsumed = false
            return null
        }

        val sourceEntered = sourceEnteredElapsedMs
        val directlyLeftSource = currentPackageName == protectedSourcePackage &&
            sourceEntered != null &&
            eventElapsedMs >= sourceEntered

        currentPackageName = observedPackage
        if (!candidateConsumed && directlyLeftSource) {
            candidateConsumed = true
            return TransitionCandidate(
                sourcePackage = protectedSourcePackage,
                targetPackage = observedPackage,
                sourceEnteredElapsedMs = sourceEntered!!,
                targetEnteredElapsedMs = eventElapsedMs,
                evidence = evidence,
            )
        }

        clearSourceContext()
        return null
    }

    @Synchronized
    fun reset() {
        currentPackageName = null
        latestObservationElapsedMs = Long.MIN_VALUE
        clearSourceContext()
    }

    @Synchronized
    fun currentPackage(): String? = currentPackageName

    private fun clearSourceContext() {
        sourceEnteredElapsedMs = null
        candidateConsumed = false
    }

}
