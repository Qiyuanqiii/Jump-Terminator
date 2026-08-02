package com.jumpterminator.app.data

import android.content.Context
import com.jumpterminator.app.core.S0Mode
import com.jumpterminator.app.core.S0Policy

data class S0Settings(
    val sourcePackage: String,
    val targetPackage: String,
    val mode: S0Mode,
    val homeFallbackEnabled: Boolean,
)

class S0SettingsRepository(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun load(): S0Settings = S0Settings(
        sourcePackage = S0Policy.HARNESS_SOURCE_PACKAGE,
        targetPackage = S0Policy.HARNESS_TARGET_PACKAGE,
        mode = if (preferences.getBoolean(KEY_ARMED, false)) {
            S0Mode.ARMED_BLOCK
        } else {
            S0Mode.RECORD_ONLY
        },
        homeFallbackEnabled = preferences.getBoolean(KEY_HOME_FALLBACK, false),
    )

    fun save(armed: Boolean, homeFallbackEnabled: Boolean) {
        preferences.edit()
            .putBoolean(KEY_ARMED, armed)
            .putBoolean(KEY_HOME_FALLBACK, homeFallbackEnabled)
            .apply()
    }

    companion object {
        private const val PREFERENCES_NAME = "s0_settings"
        private const val KEY_ARMED = "armed"
        private const val KEY_HOME_FALLBACK = "home_fallback"
    }
}
