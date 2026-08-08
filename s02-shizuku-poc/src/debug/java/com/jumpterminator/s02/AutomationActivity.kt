package com.jumpterminator.s02

/** Debug-only command entry protected by the platform permission held by ADB shell. */
class AutomationActivity : MainActivity() {
    protected override val automationCommandIngress =
        AutomationCommandIngress.ADB_DEBUG_AUTOMATION
}
