package com.jumpterminator.app.data

import android.content.Context
import android.os.Process
import android.os.UserManager

data class UserIdentity(
    val userId: Int?,
    val userSerial: Long?,
    val known: Boolean,
    val basis: String,
)

object UserIdentityResolver {
    fun resolve(context: Context): UserIdentity = try {
        val handle = Process.myUserHandle()
        // Android's public SDK exposes the current UserHandle and its serial,
        // but not the hidden numeric getIdentifier() API. hashCode is retained
        // only as a local handle marker; the stable serial is the action gate.
        val userId = handle.hashCode()
        val manager = context.getSystemService(UserManager::class.java)
        val serial = manager?.getSerialNumberForUser(handle)?.takeIf { it >= 0L }
        UserIdentity(
            userId = userId.takeIf { it >= 0 },
            userSerial = serial,
            known = userId >= 0 && serial != null,
            basis = "service_process_user",
        )
    } catch (_: SecurityException) {
        UserIdentity(null, null, false, "security_exception")
    } catch (_: RuntimeException) {
        UserIdentity(null, null, false, "runtime_error")
    }
}
