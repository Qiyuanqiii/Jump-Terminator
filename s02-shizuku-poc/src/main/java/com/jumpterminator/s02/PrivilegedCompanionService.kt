package com.jumpterminator.s02

import android.os.IBinder
import android.os.SystemClock
import android.util.Log
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.ArrayDeque

/**
 * Shizuku UserService: loaded in a dedicated shell/root process, not in the
 * normal application UID that MIUI froze during S0. The PoC intentionally
 * keeps the exact test-package gate and a bounded action count.
 */
class PrivilegedCompanionService : IPrivilegedCompanion.Stub() {
    private val lock = Any()
    private val queuedEvents = ArrayDeque<String>()
    private val authorization = OwnerAuthorizationPolicy(CRASH_GRACE_MS)

    @Volatile
    private var running = false

    @Volatile
    private var stopRequested = false

    @Volatile
    private var worker: Thread? = null

    @Volatile
    private var activeSession = "none"

    @Volatile
    private var activeScenario = "none"

    @Volatile
    private var detections = 0

    @Volatile
    private var actions = 0

    @Volatile
    private var ownerToken: IBinder? = null

    @Volatile
    private var ownerDeathRecipient: IBinder.DeathRecipient? = null

    @Volatile
    private var activeOwnerUserId = -1

    @Volatile
    private var processExitScheduled = false

    override fun startMonitor(
        sessionId: String,
        requestedBlock: Int,
        requestedAllowed: Int,
        armed: Boolean,
        ownerUid: Int,
        ownerToken: IBinder,
    ): String {
        require(SESSION_PATTERN.matches(sessionId)) { "invalid sessionId" }
        require(ownerUid >= 0) { "invalid ownerUid" }
        val ownerUserId = ownerUid / PER_USER_RANGE
        val scenario = when {
            requestedBlock in ALLOWED_COUNTS && requestedAllowed == 0 -> "block"
            requestedBlock == 0 && requestedAllowed in 1..MAX_ALLOWED_PROBES -> {
                require(armed) { "allowed-negative must be armed" }
                "allowed-negative"
            }
            else -> throw IllegalArgumentException("invalid bounded sample request")
        }
        synchronized(lock) {
            check(!running) { "monitor is already running" }
            check(!processExitScheduled) { "service exit is already scheduled" }
            installOwnerLocked(sessionId, ownerUserId, ownerToken)
            running = true
            stopRequested = false
            activeSession = sessionId
            activeScenario = scenario
            detections = 0
            actions = 0
            queuedEvents.clear()
            worker = Thread(
                {
                    runMonitor(
                        sessionId,
                        scenario,
                        requestedBlock,
                        requestedAllowed,
                        armed,
                    )
                },
                "jt-s02-privileged-monitor",
            ).apply {
                isDaemon = true
                start()
            }
        }
        return status()
    }

    override fun status(): String {
        val owner = authorization.snapshot()
        return JSONObject()
            .put("running", running)
            .put("sessionId", activeSession)
            .put("scenario", activeScenario)
            .put("detections", detections)
            .put("actions", actions)
            .put("ownerAttached", owner.ownerAttached)
            .put("ownerRevokedReason", owner.revokedReason)
            .toString()
    }

    override fun drainEvents(): String = synchronized(lock) {
        buildString {
            while (queuedEvents.isNotEmpty()) {
                if (isNotEmpty()) append('\n')
                append(queuedEvents.removeFirst())
            }
        }
    }

    override fun stopMonitor() {
        stopRequested = true
        worker?.interrupt()
    }

    override fun destroy() {
        authorization.revoke(activeSession, "destroy_requested")
        stopMonitor()
        worker?.join(2_000L)
        synchronized(lock) {
            detachOwnerLocked()
            authorization.clear()
        }
        System.exit(0)
    }

    private fun runMonitor(
        sessionId: String,
        scenario: String,
        requestedBlock: Int,
        requestedAllowed: Int,
        armed: Boolean,
    ) {
        val mode = if (armed) "armed" else "observe"
        val boundedWork = if (scenario == "block") requestedBlock else requestedAllowed
        val timeoutAt = System.currentTimeMillis() + maxOf(
            90_000L,
            boundedWork * 8_000L + 60_000L,
        )
        var lastState = ""
        var sourceContext = false
        var targetHandled = false
        var pendingLeave = false
        var lastSourceSample = System.currentTimeMillis()
        var entryLowerBound = lastSourceSample

        emit(
            sessionId,
            "ready",
            data = mapOf(
                "scenario" to scenario,
                "mode" to mode,
                "requestedBlock" to requestedBlock,
                "requestedAllowed" to requestedAllowed,
                "sourceComponent" to SOURCE_COMPONENT,
                "targetComponent" to TARGET_COMPONENT,
                "executor" to "shizuku_user_service",
                "ownerBound" to true,
                "ownerUserId" to activeOwnerUserId,
                "crashGraceMs" to CRASH_GRACE_MS,
            ),
        )

        try {
            while (!stopRequested && System.currentTimeMillis() < timeoutAt) {
                val expirationReason = authorization.expirationReason(
                    sessionId,
                    SystemClock.elapsedRealtime(),
                )
                if (expirationReason != null) {
                    emitAuthorizationRevoked(sessionId, expirationReason)
                    scheduleProcessExit(sessionId, expirationReason)
                    return
                }
                val pollStart = System.currentTimeMillis()
                val component = readTopComponent()
                val pollEnd = System.currentTimeMillis()
                val state = when (component) {
                    SOURCE_COMPONENT -> "source"
                    TARGET_COMPONENT -> "target"
                    "unknown" -> "unknown"
                    else -> "other"
                }

                if (state != lastState) {
                    emit(
                        sessionId,
                        "foreground_changed",
                        packageName = component,
                        timeMs = pollEnd,
                        data = mapOf("state" to state, "component" to component),
                    )
                }

                if (pendingLeave && state != "target" && state != "unknown") {
                    emit(
                        sessionId,
                        "left_target",
                        packageName = TARGET_COMPONENT,
                        timeMs = pollEnd,
                        data = mapOf(
                            "sequence" to detections,
                            "leftTarget" to true,
                            "returnedSource" to (state == "source"),
                            "observedComponent" to component,
                            "leaveUpperBoundMs" to (pollEnd - entryLowerBound),
                        ),
                    )
                    pendingLeave = false
                }

                when (state) {
                    "source" -> {
                        sourceContext = true
                        targetHandled = false
                        lastSourceSample = pollEnd
                    }
                    "target" -> if (sourceContext && !targetHandled) {
                        detections += 1
                        sourceContext = false
                        targetHandled = true
                        pendingLeave = true
                        entryLowerBound = lastSourceSample
                        emit(
                            sessionId,
                            "target_detected",
                            packageName = TARGET_COMPONENT,
                            timeMs = pollEnd,
                            data = mapOf(
                                "sequence" to detections,
                                "sourceComponent" to SOURCE_COMPONENT,
                                "targetComponent" to TARGET_COMPONENT,
                                "entryLowerBoundWallMs" to entryLowerBound,
                                "detectionUpperBoundMs" to (pollEnd - entryLowerBound),
                                "pollDurationMs" to (pollEnd - pollStart),
                            ),
                        )
                        if (armed && !dispatchBack(sessionId, entryLowerBound)) return
                    }
                    "other" -> sourceContext = false
                }

                lastState = state
                if (
                    scenario == "block" &&
                    detections >= requestedBlock &&
                    !pendingLeave &&
                    state == "source"
                ) {
                    emit(
                        sessionId,
                        "complete",
                        data = mapOf(
                            "reason" to "count_reached",
                            "detections" to detections,
                            "actions" to actions,
                        ),
                    )
                    return
                }
                Thread.sleep(POLL_SLEEP_MS)
            }

            if (stopRequested) {
                emit(
                    sessionId,
                    "complete",
                    data = mapOf(
                        "reason" to "stop_requested",
                        "detections" to detections,
                        "actions" to actions,
                    ),
                )
            } else {
                emit(
                    sessionId,
                    "timeout",
                    data = mapOf("detections" to detections, "actions" to actions),
                )
            }
        } catch (_: InterruptedException) {
            emit(
                sessionId,
                "complete",
                data = mapOf(
                    "reason" to "stop_requested",
                    "detections" to detections,
                    "actions" to actions,
                ),
            )
        } catch (error: Throwable) {
            emit(
                sessionId,
                "service_error",
                data = mapOf(
                    "type" to error.javaClass.name,
                    "message" to (error.message ?: "unknown"),
                ),
            )
        } finally {
            running = false
            worker = null
            if (authorization.shouldExitWhenIdle(sessionId)) {
                scheduleProcessExit(sessionId, "owner_detached_after_session")
            }
        }
    }

    private fun dispatchBack(sessionId: String, entryLowerBound: Long): Boolean {
        val packageStopped = readOwnerPackageStopped(activeOwnerUserId)
        val denialReason = authorization.actionDenialReason(
            sessionId,
            SystemClock.elapsedRealtime(),
            packageStopped,
        )
        if (denialReason != null) {
            emitAuthorizationRevoked(sessionId, denialReason)
            scheduleProcessExit(sessionId, denialReason)
            return false
        }
        val actionStart = System.currentTimeMillis()
        val process = ProcessBuilder(INPUT, "keyevent", "4")
            .redirectErrorStream(true)
            .start()
        process.inputStream.use { stream ->
            val buffer = ByteArray(256)
            while (stream.read(buffer) >= 0) {
                // Drain the tiny command output without relying on a Java 11-only sink.
            }
        }
        val dispatched = process.waitFor() == 0
        val actionEnd = System.currentTimeMillis()
        actions += 1
        emit(
            sessionId,
            "back_requested",
            packageName = TARGET_COMPONENT,
            timeMs = actionStart,
            data = mapOf(
                "sequence" to detections,
                "dispatched" to dispatched,
                "sourceComponent" to SOURCE_COMPONENT,
                "targetComponent" to TARGET_COMPONENT,
                "requestUpperBoundMs" to (actionStart - entryLowerBound),
                "inputDurationMs" to (actionEnd - actionStart),
            ),
        )
        return true
    }

    private fun installOwnerLocked(sessionId: String, ownerUserId: Int, token: IBinder) {
        detachOwnerLocked()
        authorization.begin(sessionId)
        val recipient = IBinder.DeathRecipient {
            handleOwnerDeath(sessionId, ownerUserId)
        }
        this.ownerToken = token
        ownerDeathRecipient = recipient
        activeOwnerUserId = ownerUserId
        try {
            token.linkToDeath(recipient, 0)
            check(token.isBinderAlive) { "owner binder is already dead" }
        } catch (error: Throwable) {
            this.ownerToken = null
            ownerDeathRecipient = null
            activeOwnerUserId = -1
            authorization.revoke(sessionId, "owner_binder_unavailable")
            throw IllegalStateException("unable to bind monitor ownership", error)
        }
    }

    private fun detachOwnerLocked() {
        val token = ownerToken
        val recipient = ownerDeathRecipient
        if (token != null && recipient != null) {
            try {
                token.unlinkToDeath(recipient, 0)
            } catch (_: Throwable) {
                // A dead owner is already detached from the Binder driver.
            }
        }
        ownerToken = null
        ownerDeathRecipient = null
        activeOwnerUserId = -1
    }

    private fun handleOwnerDeath(sessionId: String, ownerUserId: Int) {
        Thread(
            {
                val packageStopped = readOwnerPackageStopped(ownerUserId)
                val decision = authorization.ownerDied(
                    sessionId,
                    SystemClock.elapsedRealtime(),
                    packageStopped,
                )
                if (!decision.applies) return@Thread
                val revokedReason = decision.revokedReason
                if (revokedReason != null) {
                    emitAuthorizationRevoked(sessionId, revokedReason)
                    scheduleProcessExit(sessionId, revokedReason)
                    return@Thread
                }

                val deadline = decision.graceDeadlineElapsedMs ?: return@Thread
                emit(
                    sessionId,
                    "owner_detached",
                    data = mapOf(
                        "reason" to "owner_process_died",
                        "ownerPackageStopped" to false,
                        "graceDeadlineElapsedMs" to deadline,
                    ),
                )
                val remaining = (deadline - SystemClock.elapsedRealtime()).coerceAtLeast(1L)
                try {
                    Thread.sleep(remaining)
                } catch (_: InterruptedException) {
                    return@Thread
                }
                val expirationReason = authorization.expirationReason(
                    sessionId,
                    SystemClock.elapsedRealtime(),
                ) ?: return@Thread
                emitAuthorizationRevoked(sessionId, expirationReason)
                scheduleProcessExit(sessionId, expirationReason)
            },
            "jt-s02-owner-death",
        ).apply {
            isDaemon = true
            start()
        }
    }

    private fun emitAuthorizationRevoked(sessionId: String, reason: String) {
        emit(
            sessionId,
            "authorization_revoked",
            data = mapOf(
                "reason" to reason,
                "ownerUserId" to activeOwnerUserId,
            ),
        )
    }

    private fun scheduleProcessExit(sessionId: String, reason: String) {
        val shouldSchedule = synchronized(lock) {
            if (processExitScheduled) {
                false
            } else {
                processExitScheduled = true
                stopRequested = true
                worker?.interrupt()
                true
            }
        }
        if (!shouldSchedule) return
        emit(
            sessionId,
            "service_exit_requested",
            data = mapOf("reason" to reason),
        )
        Thread(
            {
                val activeWorker = worker
                if (activeWorker != null && activeWorker !== Thread.currentThread()) {
                    try {
                        activeWorker.join(2_000L)
                    } catch (_: InterruptedException) {
                        Thread.currentThread().interrupt()
                    }
                }
                synchronized(lock) {
                    detachOwnerLocked()
                    authorization.clear()
                }
                try {
                    Thread.sleep(EXIT_LOG_FLUSH_MS)
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                }
                System.exit(0)
            },
            "jt-s02-process-exit",
        ).apply {
            isDaemon = false
            start()
        }
    }

    private fun readOwnerPackageStopped(ownerUserId: Int): Boolean? {
        if (ownerUserId < 0) return null
        return try {
            val process = ProcessBuilder(DUMPSYS, "package", OWNER_PACKAGE)
                .redirectErrorStream(true)
                .start()
            val output = BufferedReader(InputStreamReader(process.inputStream)).use {
                it.readText()
            }
            if (process.waitFor() != 0) null else PackageStoppedStateParser.parse(output, ownerUserId)
        } catch (_: Throwable) {
            null
        }
    }

    private fun readTopComponent(): String = try {
        val process = ProcessBuilder(
            SH,
            "-c",
            "dumpsys activity activities 2>/dev/null | grep -m1 'topResumedActivity='",
        ).redirectErrorStream(true).start()
        val line = BufferedReader(InputStreamReader(process.inputStream)).use { it.readLine() }
        process.waitFor()
        TOP_COMPONENT.find(line.orEmpty())?.groupValues?.getOrNull(1) ?: "unknown"
    } catch (_: Throwable) {
        "unknown"
    }

    private fun emit(
        sessionId: String,
        kind: String,
        packageName: String? = null,
        timeMs: Long = System.currentTimeMillis(),
        data: Map<String, Any?> = emptyMap(),
    ) {
        val payload = JSONObject()
            .put("schema", "s0.2-1")
            .put("sessionId", sessionId)
            .put("kind", kind)
            .put("wallClockMs", timeMs)
        if (packageName != null) payload.put("packageName", packageName)
        val dataObject = JSONObject()
        data.forEach { (key, value) -> dataObject.put(key, value) }
        payload.put("data", dataObject)
        val line = payload.toString()
        synchronized(lock) {
            while (queuedEvents.size >= MAX_QUEUED_EVENTS) queuedEvents.removeFirst()
            queuedEvents.addLast(line)
        }
        Log.i(LOG_TAG, line)
    }

    companion object {
        private const val LOG_TAG = "JT_S02_SHIZUKU"
        private const val SOURCE_COMPONENT = "com.jumpterminator.testsource/.SourceActivity"
        private const val TARGET_COMPONENT = "com.jumpterminator.testtarget/.TargetActivity"
        private const val OWNER_PACKAGE = "com.jumpterminator.s02"
        private const val SH = "/system/bin/sh"
        private const val INPUT = "/system/bin/input"
        private const val DUMPSYS = "/system/bin/dumpsys"
        private const val POLL_SLEEP_MS = 30L
        private const val CRASH_GRACE_MS = 10_000L
        private const val EXIT_LOG_FLUSH_MS = 100L
        private const val PER_USER_RANGE = 100_000
        private const val MAX_QUEUED_EVENTS = 1_000
        private const val MAX_ALLOWED_PROBES = 60
        private val SESSION_PATTERN = Regex("[a-f0-9]{32}")
        private val ALLOWED_COUNTS = setOf(1, 10, 100)
        private val TOP_COMPONENT = Regex(" u\\d+ ([^}\\s]+)")
    }
}
