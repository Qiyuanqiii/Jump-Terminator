package com.jumpterminator.app.service

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.accessibility.AccessibilityEvent
import com.jumpterminator.app.core.S0Policy
import com.jumpterminator.app.core.S0PolicyInput
import com.jumpterminator.app.core.TransitionCandidate
import com.jumpterminator.app.core.TransitionTracker
import com.jumpterminator.app.data.S0SettingsRepository
import com.jumpterminator.app.data.TimelineRecorder
import com.jumpterminator.app.data.UserIdentityResolver
import com.jumpterminator.app.platform.UsageStatsCollector
import java.util.concurrent.Executors

class JumpAccessibilityService : AccessibilityService() {
    private val handler = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()

    private lateinit var recorder: TimelineRecorder
    private lateinit var settingsRepository: S0SettingsRepository
    private lateinit var transitionTracker: TransitionTracker
    private lateinit var usageStatsCollector: UsageStatsCollector
    private var contextBreakPackages: Set<String> = emptySet()
    private var actionInFlight = false

    override fun onServiceConnected() {
        super.onServiceConnected()
        recorder = TimelineRecorder(this)
        settingsRepository = S0SettingsRepository(this)
        contextBreakPackages = resolveContextBreakPackages()
        transitionTracker = TransitionTracker(
            protectedSource = settingsRepository.load().sourcePackage,
            contextBreakPackages = contextBreakPackages,
        )
        usageStatsCollector = UsageStatsCollector(
            context = this,
            handler = handler,
            executor = executor,
            recorder = recorder,
            onForeground = ::processForeground,
            onClockJump = { driftMs ->
                transitionTracker.reset()
                recorder.record(
                    kind = "source_context_reset",
                    data = mapOf("reason" to "clock_jump", "driftMs" to driftMs),
                )
            },
        )
        val identity = UserIdentityResolver.resolve(this)
        recorder.record(
            kind = "service_connected",
            packageName = packageName,
            data = mapOf(
                "identityKnown" to identity.known,
                "userId" to identity.userId,
                "userSerial" to identity.userSerial,
                "breakPackages" to contextBreakPackages.sorted().joinToString(","),
            ),
        )
        handler.postDelayed(::observeForegroundSnapshot, FOREGROUND_SNAPSHOT_DELAY_MS)
        usageStatsCollector.start()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null || !::recorder.isInitialized) return
        val observedPackage = event.packageName?.toString()
        val receiptElapsedMs = SystemClock.elapsedRealtime()
        val eventElapsedMs = receiptElapsedMs - SystemClock.uptimeMillis() + event.eventTime

        recorder.record(
            kind = "accessibility_signal",
            packageName = observedPackage,
            elapsedRealtimeMs = eventElapsedMs,
            data = mapOf(
                "eventType" to AccessibilityEvent.eventTypeToString(event.eventType),
                "className" to event.className?.toString(),
                "rawEventUptimeMs" to event.eventTime,
                "receiptDelayMs" to (receiptElapsedMs - eventElapsedMs),
            ),
        )

        if (
            observedPackage != null &&
            (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED ||
                event.eventType == AccessibilityEvent.TYPE_WINDOWS_CHANGED)
        ) {
            processForeground(observedPackage, eventElapsedMs, "accessibility")
        }
    }

    override fun onInterrupt() {
        if (::recorder.isInitialized) {
            recorder.record(kind = "service_interrupted", packageName = packageName)
        }
    }

    override fun onUnbind(intent: Intent?): Boolean {
        stopCollectors("service_unbound")
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        stopCollectors("service_destroyed")
        super.onDestroy()
    }

    private fun stopCollectors(reason: String) {
        if (::usageStatsCollector.isInitialized) usageStatsCollector.stop()
        handler.removeCallbacksAndMessages(null)
        executor.shutdownNow()
        if (::recorder.isInitialized) recorder.record(kind = reason, packageName = packageName)
    }

    private fun processForeground(packageName: String, elapsedMs: Long, evidence: String) {
        if (!::transitionTracker.isInitialized) return
        val settings = settingsRepository.load()
        transitionTracker.updateConfiguration(settings.sourcePackage, contextBreakPackages)
        val candidate = transitionTracker.observeForeground(packageName, elapsedMs, evidence) ?: return

        recorder.record(
            kind = "transition_candidate",
            packageName = candidate.targetPackage,
            data = mapOf(
                "sourcePackage" to candidate.sourcePackage,
                "targetPackage" to candidate.targetPackage,
                "sourceEnteredElapsedMs" to candidate.sourceEnteredElapsedMs,
                "targetEnteredElapsedMs" to candidate.targetEnteredElapsedMs,
                "transitionLatencyMs" to candidate.transitionLatencyMs,
                "signalAgeMs" to (SystemClock.elapsedRealtime() - candidate.targetEnteredElapsedMs),
                "evidence" to candidate.evidence,
            ),
        )

        val identity = UserIdentityResolver.resolve(this)
        val decision = S0Policy.evaluate(
            S0PolicyInput(
                mode = settings.mode,
                sourcePackage = candidate.sourcePackage,
                targetPackage = candidate.targetPackage,
                configuredSourcePackage = settings.sourcePackage,
                configuredTargetPackage = settings.targetPackage,
                identityKnown = identity.known,
                safePackages = contextBreakPackages,
            ),
        )

        val effectiveReason = if (decision.shouldAct && actionInFlight) {
            "action_in_flight"
        } else {
            decision.reason
        }
        val shouldAct = decision.shouldAct && !actionInFlight
        recorder.record(
            kind = "policy_decision",
            packageName = candidate.targetPackage,
            data = mapOf(
                "sourcePackage" to candidate.sourcePackage,
                "targetPackage" to candidate.targetPackage,
                "targetEnteredElapsedMs" to candidate.targetEnteredElapsedMs,
                "mode" to settings.mode.name,
                "shouldAct" to shouldAct,
                "reason" to effectiveReason,
                "identityKnown" to identity.known,
            ),
        )
        if (shouldAct) executeOneShot(candidate, settings.homeFallbackEnabled)
    }

    private fun observeForegroundSnapshot() {
        if (!::transitionTracker.isInitialized || !::recorder.isInitialized) return
        val observedPackage = try {
            rootInActiveWindow?.packageName?.toString()
                ?: windows.firstOrNull { it.isActive }?.root?.packageName?.toString()
        } catch (_: RuntimeException) {
            null
        }
        recorder.record(
            kind = "foreground_snapshot",
            packageName = observedPackage,
            data = mapOf("available" to (observedPackage != null)),
        )
        if (observedPackage != null) {
            transitionTracker.observeForeground(
                packageName = observedPackage,
                eventElapsedMs = SystemClock.elapsedRealtime(),
                evidence = "accessibility_snapshot",
            )
        }
    }

    private fun executeOneShot(candidate: TransitionCandidate, homeFallbackEnabled: Boolean) {
        actionInFlight = true
        handler.postDelayed({
            val foregroundBeforeAction = resolveForegroundPackage()
            if (foregroundBeforeAction != candidate.targetPackage) {
                recorder.record(
                    kind = "action_cancelled",
                    packageName = candidate.targetPackage,
                    data = mapOf(
                        "reason" to "target_no_longer_foreground",
                        "observedPackage" to foregroundBeforeAction,
                    ),
                )
                actionInFlight = false
                return@postDelayed
            }

            val dispatched = performGlobalAction(GLOBAL_ACTION_BACK)
            recorder.record(
                kind = "action_attempt",
                packageName = candidate.targetPackage,
                data = mapOf(
                    "stage" to "back",
                    "dispatched" to dispatched,
                    "dispatchIsNotSuccessProof" to true,
                    "candidateAgeMs" to (SystemClock.elapsedRealtime() - candidate.targetEnteredElapsedMs),
                ),
            )
            handler.postDelayed(
                { verifyAfterBack(candidate, homeFallbackEnabled) },
                VERIFY_DELAY_MS,
            )
        }, PRE_ACTION_CONFIRM_DELAY_MS)
    }

    private fun verifyAfterBack(candidate: TransitionCandidate, homeFallbackEnabled: Boolean) {
        val observedPackage = resolveForegroundPackage()
        val leftTarget = observedPackage != candidate.targetPackage
        recorder.record(
            kind = "action_verification",
            packageName = candidate.targetPackage,
            data = mapOf(
                "stage" to "back",
                "leftTarget" to leftTarget,
                "observedPackage" to observedPackage,
                "totalLatencyMs" to (SystemClock.elapsedRealtime() - candidate.targetEnteredElapsedMs),
            ),
        )
        if (leftTarget || !homeFallbackEnabled) {
            actionInFlight = false
            return
        }

        val dispatched = performGlobalAction(GLOBAL_ACTION_HOME)
        recorder.record(
            kind = "action_attempt",
            packageName = candidate.targetPackage,
            data = mapOf(
                "stage" to "home",
                "dispatched" to dispatched,
                "dispatchIsNotSuccessProof" to true,
            ),
        )
        handler.postDelayed({
            val afterHomePackage = resolveForegroundPackage()
            recorder.record(
                kind = "action_verification",
                packageName = candidate.targetPackage,
                data = mapOf(
                    "stage" to "home",
                    "leftTarget" to (afterHomePackage != candidate.targetPackage),
                    "observedPackage" to afterHomePackage,
                    "totalLatencyMs" to (SystemClock.elapsedRealtime() - candidate.targetEnteredElapsedMs),
                ),
            )
            actionInFlight = false
        }, VERIFY_DELAY_MS)
    }

    private fun resolveForegroundPackage(): String? = try {
        rootInActiveWindow?.packageName?.toString() ?: transitionTracker.currentPackage()
    } catch (_: RuntimeException) {
        transitionTracker.currentPackage()
    }

    private fun resolveContextBreakPackages(): Set<String> {
        val packages = mutableSetOf(
            packageName,
            "com.android.systemui",
            "com.android.settings",
            "com.google.android.packageinstaller",
            "com.android.packageinstaller",
        )
        val homeIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        packageManager.queryIntentActivities(homeIntent, 0)
            .mapTo(packages) { it.activityInfo.packageName }
        return packages
    }

    companion object {
        private const val FOREGROUND_SNAPSHOT_DELAY_MS = 150L
        private const val PRE_ACTION_CONFIRM_DELAY_MS = 120L
        private const val VERIFY_DELAY_MS = 600L
    }
}
