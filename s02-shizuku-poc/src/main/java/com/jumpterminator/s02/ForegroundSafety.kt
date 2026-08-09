package com.jumpterminator.s02

internal data class ForegroundSnapshot(
    val topComponent: String,
    val resumedComponents: List<String>,
    val pinnedPackages: List<String>,
    val pictureInPictureActive: Boolean,
    val ambiguous: Boolean,
)

internal object ForegroundSnapshotParser {
    private val componentPattern = Regex(" u\\d+ ([^}\\s]+)")
    private val pinnedTaskPackagePattern = Regex(
        "Task\\{[^\\r\\n]*\\bA=\\d+:([^\\s}]+)[^\\r\\n]*\\bmode=pinned\\b",
    )
    private val activePictureInPicturePattern = Regex(
        "(?:\\bmode=pinned\\b|\\bmWindowingMode=pinned\\b|" +
            "\\bmLastReportedPictureInPictureMode=true\\b)",
    )

    fun parse(output: String): ForegroundSnapshot {
        val components = output.lineSequence()
            .filter { it.contains("topResumedActivity=") }
            .mapNotNull { line ->
                componentPattern.find(line)?.groupValues?.getOrNull(1)
            }
            .distinct()
            .toList()
        val pinnedPackages = pinnedTaskPackagePattern.findAll(output)
            .map { match -> match.groupValues[1] }
            .distinct()
            .toList()
        val pictureInPictureActive = activePictureInPicturePattern.containsMatchIn(output)
        return ForegroundSnapshot(
            topComponent = components.firstOrNull() ?: "unknown",
            resumedComponents = components,
            pinnedPackages = pinnedPackages,
            pictureInPictureActive = pictureInPictureActive,
            ambiguous = components.size > 1 || pictureInPictureActive,
        )
    }
}

internal data class DeviceInteractionState(
    val interactive: Boolean?,
    val keyguardLocked: Boolean?,
)

internal object DeviceInteractionStateParser {
    private val wakefulnessPattern = Regex("mWakefulness=(\\w+)")
    private val keyguardPattern = Regex(
        "(?:mDreamingLockscreen|mShowingLockscreen|isStatusBarKeyguard|" +
            "mInputRestricted)=(true|false)",
    )

    fun parse(output: String): DeviceInteractionState {
        val interactive = when (
            wakefulnessPattern.find(output)?.groupValues?.getOrNull(1)
        ) {
            "Awake" -> true
            "Asleep", "Dozing", "Dreaming" -> false
            else -> null
        }
        val keyguardValues = keyguardPattern.findAll(output)
            .map { it.groupValues[1] == "true" }
            .toList()
        val keyguardLocked = when {
            keyguardValues.any { it } -> true
            keyguardValues.isNotEmpty() -> false
            else -> null
        }
        return DeviceInteractionState(
            interactive = interactive,
            keyguardLocked = keyguardLocked,
        )
    }
}
