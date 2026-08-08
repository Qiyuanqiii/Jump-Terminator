package com.jumpterminator.s02

enum class AutomationCommandIngress {
    PUBLIC_LAUNCHER,
    ADB_DEBUG_AUTOMATION,
}

/**
 * Automation commands are never accepted by the exported launcher Activity.
 * The only allowed ingress is a debug-source-set Activity protected by android.permission.DUMP.
 */
internal object AutomationCommandGate {
    fun allows(ingress: AutomationCommandIngress): Boolean =
        ingress == AutomationCommandIngress.ADB_DEBUG_AUTOMATION
}
