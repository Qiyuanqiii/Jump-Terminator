package com.jumpterminator.s02

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import java.nio.charset.StandardCharsets
import java.security.MessageDigest

internal data class OwnerIdentity(
    val uid: Int,
    val userId: Int,
    val packageName: String,
    val signingCertificateSha256: List<String>,
)

internal data class MonitorAuthorization(
    val sessionId: String,
    val capability: String,
    val capabilityFingerprint: String,
    val owner: OwnerIdentity,
    val scenario: String,
    val requestedBlock: Int,
    val requestedAllowed: Int,
    val armed: Boolean,
    val sourceComponent: String,
    val targetComponent: String,
    val action: String,
    val startedElapsedMs: Long,
    val leaseDurationMs: Long,
    val leaseDeadlineElapsedMs: Long,
    val ruleSnapshotSha256: String,
)

internal data class ActionEnvironment(
    val ownerPackageStopped: Boolean?,
    val topComponent: String,
)

internal data class AuthorizedLaunch<T>(
    val value: T? = null,
    val denialReason: String? = null,
) {
    val launched: Boolean
        get() = denialReason == null && value != null
}

internal object OwnerIdentityValidator {
    private val digestPattern = Regex("[a-f0-9]{64}")

    fun resolve(
        callingUid: Int,
        ownerUserId: Int,
        expectedPackage: String,
        packagesForUid: Collection<String>?,
        signingCertificateSha256: Collection<String>?,
    ): OwnerIdentity {
        if (callingUid < 0 || ownerUserId < 0) {
            throw SecurityException("caller_identity_invalid")
        }
        if (packagesForUid == null || expectedPackage !in packagesForUid) {
            throw SecurityException("caller_package_mismatch")
        }
        val normalizedDigests = signingCertificateSha256
            ?.map { it.lowercase() }
            ?.filter { digestPattern.matches(it) }
            ?.distinct()
            ?.sorted()
            .orEmpty()
        if (normalizedDigests.isEmpty()) {
            throw SecurityException("owner_signing_identity_unknown")
        }
        return OwnerIdentity(
            uid = callingUid,
            userId = ownerUserId,
            packageName = expectedPackage,
            signingCertificateSha256 = normalizedDigests,
        )
    }
}

internal class AndroidOwnerIdentityResolver(
    private val context: Context?,
    private val expectedPackage: String,
) {
    fun resolve(callingUid: Int): OwnerIdentity {
        val serviceContext = context
            ?: throw SecurityException("user_service_context_unavailable")
        val packageManager = try {
            serviceContext.packageManager
        } catch (error: Throwable) {
            throw SecurityException("package_manager_unavailable", error)
        }
        val packagesForUid = try {
            packageManager.getPackagesForUid(callingUid)?.asList()
        } catch (error: Throwable) {
            throw SecurityException("caller_packages_unavailable", error)
        }
        val packageInfo = try {
            if (Build.VERSION.SDK_INT >= 33) {
                packageManager.getPackageInfo(
                    expectedPackage,
                    PackageManager.PackageInfoFlags.of(
                        PackageManager.GET_SIGNING_CERTIFICATES.toLong(),
                    ),
                )
            } else {
                @Suppress("DEPRECATION")
                packageManager.getPackageInfo(
                    expectedPackage,
                    PackageManager.GET_SIGNING_CERTIFICATES,
                )
            }
        } catch (error: Throwable) {
            throw SecurityException("owner_package_info_unavailable", error)
        }
        val signingDigests = packageInfo.signingInfo
            ?.apkContentsSigners
            ?.map { signature -> sha256Hex(signature.toByteArray()) }
            .orEmpty()
        val userId = callingUid / PER_USER_RANGE
        return OwnerIdentityValidator.resolve(
            callingUid = callingUid,
            ownerUserId = userId,
            expectedPackage = expectedPackage,
            packagesForUid = packagesForUid,
            signingCertificateSha256 = signingDigests,
        )
    }
}

internal object MonitorAuthorizationFactory {
    private val sessionPattern = Regex("[a-f0-9]{32}")
    private val capabilityPattern = Regex("[a-f0-9]{64}")

    fun create(
        sessionId: String,
        capability: String,
        owner: OwnerIdentity,
        scenario: String,
        requestedBlock: Int,
        requestedAllowed: Int,
        armed: Boolean,
        sourceComponent: String,
        targetComponent: String,
        action: String,
        startedElapsedMs: Long,
        leaseDurationMs: Long,
    ): MonitorAuthorization {
        require(sessionPattern.matches(sessionId)) { "invalid sessionId" }
        require(capabilityPattern.matches(capability)) { "invalid capability" }
        require(startedElapsedMs >= 0L) { "invalid start time" }
        require(leaseDurationMs > 0L) { "invalid lease duration" }

        val capabilityFingerprint = sha256Hex(
            capability.toByteArray(StandardCharsets.UTF_8),
        )
        val leaseDeadlineElapsedMs = saturatedAdd(startedElapsedMs, leaseDurationMs)
        val canonicalSnapshot = listOf(
            "protocol=s0.4-1",
            "sessionId=$sessionId",
            "capabilityFingerprint=$capabilityFingerprint",
            "ownerUid=${owner.uid}",
            "ownerUserId=${owner.userId}",
            "ownerPackage=${owner.packageName}",
            "ownerSigningCertificateSha256=${owner.signingCertificateSha256.joinToString(",")}",
            "scenario=$scenario",
            "requestedBlock=$requestedBlock",
            "requestedAllowed=$requestedAllowed",
            "armed=$armed",
            "sourceComponent=$sourceComponent",
            "targetComponent=$targetComponent",
            "action=$action",
            "startedElapsedMs=$startedElapsedMs",
            "leaseDurationMs=$leaseDurationMs",
            "leaseDeadlineElapsedMs=$leaseDeadlineElapsedMs",
        ).joinToString("\n")
        return MonitorAuthorization(
            sessionId = sessionId,
            capability = capability,
            capabilityFingerprint = capabilityFingerprint,
            owner = owner,
            scenario = scenario,
            requestedBlock = requestedBlock,
            requestedAllowed = requestedAllowed,
            armed = armed,
            sourceComponent = sourceComponent,
            targetComponent = targetComponent,
            action = action,
            startedElapsedMs = startedElapsedMs,
            leaseDurationMs = leaseDurationMs,
            leaseDeadlineElapsedMs = leaseDeadlineElapsedMs,
            ruleSnapshotSha256 = sha256Hex(
                canonicalSnapshot.toByteArray(StandardCharsets.UTF_8),
            ),
        )
    }

    private fun saturatedAdd(left: Long, right: Long): Long =
        if (left > Long.MAX_VALUE - right) Long.MAX_VALUE else left + right
}

internal fun sha256Hex(value: ByteArray): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(value)
    return buildString(digest.size * 2) {
        digest.forEach { byte ->
            val unsigned = byte.toInt() and 0xff
            append(HEX[unsigned ushr 4])
            append(HEX[unsigned and 0x0f])
        }
    }
}

private const val HEX = "0123456789abcdef"
private const val PER_USER_RANGE = 100_000
