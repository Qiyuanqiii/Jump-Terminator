package com.jumpterminator.app.core

enum class S0Mode {
    RECORD_ONLY,
    ARMED_BLOCK,
}

data class S0PolicyInput(
    val mode: S0Mode,
    val sourcePackage: String,
    val targetPackage: String,
    val configuredSourcePackage: String,
    val configuredTargetPackage: String,
    val identityKnown: Boolean,
    val safePackages: Set<String>,
)

data class S0PolicyDecision(
    val shouldAct: Boolean,
    val reason: String,
)

/** Hard safety boundary for the feasibility build: it can only act on the bundled harness. */
object S0Policy {
    const val HARNESS_SOURCE_PACKAGE = "com.jumpterminator.testsource"
    const val HARNESS_TARGET_PACKAGE = "com.jumpterminator.testtarget"

    fun evaluate(input: S0PolicyInput): S0PolicyDecision = when {
        input.mode != S0Mode.ARMED_BLOCK -> reject("record_only")
        !input.identityKnown -> reject("identity_unknown")
        input.configuredSourcePackage != HARNESS_SOURCE_PACKAGE -> reject("source_not_s0_harness")
        input.configuredTargetPackage != HARNESS_TARGET_PACKAGE -> reject("target_not_s0_harness")
        input.sourcePackage != input.configuredSourcePackage -> reject("source_mismatch")
        input.targetPackage != input.configuredTargetPackage -> reject("target_mismatch")
        input.targetPackage in input.safePackages -> reject("safe_package")
        else -> S0PolicyDecision(shouldAct = true, reason = "armed_exact_harness_match")
    }

    private fun reject(reason: String) = S0PolicyDecision(shouldAct = false, reason = reason)
}
