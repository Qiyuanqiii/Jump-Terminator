package com.jumpterminator.s02

/**
 * Requires the platform runtime grant and Shizuku's authorization view to agree.
 *
 * Shizuku caches a positive authorization result for the lifetime of an attached
 * client. Checking the platform grant separately keeps a directly revoked app
 * from opening a new privileged session with that stale positive result.
 */
internal object ShizukuPermissionGate {
    fun isGranted(
        platformPermissionGranted: Boolean,
        shizukuPermissionGranted: Boolean,
    ): Boolean = platformPermissionGranted && shizukuPermissionGranted
}
