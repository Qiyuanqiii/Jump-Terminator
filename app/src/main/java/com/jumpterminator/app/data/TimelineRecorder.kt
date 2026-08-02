package com.jumpterminator.app.data

import android.content.Context
import android.os.SystemClock
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream
import java.nio.charset.StandardCharsets
import java.util.UUID

class TimelineRecorder(context: Context) {
    private val appContext = context.applicationContext
    private val identity = UserIdentityResolver.resolve(appContext)
    private val directory = File(appContext.filesDir, "s0")
    private val activeFile = File(directory, ACTIVE_FILE_NAME)

    fun record(
        kind: String,
        packageName: String? = null,
        elapsedRealtimeMs: Long = SystemClock.elapsedRealtime(),
        data: Map<String, Any?> = emptyMap(),
    ) {
        val event = JSONObject()
            .put("schema", SCHEMA_VERSION)
            .put("eventId", UUID.randomUUID().toString())
            .put("wallClockMs", System.currentTimeMillis())
            .put("elapsedRealtimeMs", elapsedRealtimeMs)
            .put("kind", kind)
            .put("packageName", packageName ?: JSONObject.NULL)
            .put("userId", identity.userId ?: JSONObject.NULL)
            .put("userSerial", identity.userSerial ?: JSONObject.NULL)
            .put("identityKnown", identity.known)
            .put("identityBasis", identity.basis)
            .put("data", JSONObject(data.mapValues { (_, value) -> value ?: JSONObject.NULL }))

        appendLine(event.toString())
    }

    fun tail(maxLines: Int = 80): List<String> = synchronized(FILE_LOCK) {
        if (!activeFile.exists()) return@synchronized emptyList()
        activeFile.readLines(StandardCharsets.UTF_8).takeLast(maxLines)
    }

    fun exportTo(output: OutputStream) = synchronized(FILE_LOCK) {
        listOf(File(directory, ROTATED_FILE_2), File(directory, ROTATED_FILE_1), activeFile)
            .filter { it.exists() }
            .forEach { file ->
                file.inputStream().use { input -> input.copyTo(output) }
            }
        output.flush()
    }

    fun clear() = synchronized(FILE_LOCK) {
        listOf(activeFile, File(directory, ROTATED_FILE_1), File(directory, ROTATED_FILE_2))
            .forEach { it.delete() }
    }

    fun totalBytes(): Long = synchronized(FILE_LOCK) {
        listOf(activeFile, File(directory, ROTATED_FILE_1), File(directory, ROTATED_FILE_2))
            .filter { it.exists() }
            .sumOf { it.length() }
    }

    private fun appendLine(line: String) = synchronized(FILE_LOCK) {
        directory.mkdirs()
        val bytes = (line + "\n").toByteArray(StandardCharsets.UTF_8)
        if (activeFile.exists() && activeFile.length() + bytes.size > MAX_FILE_BYTES) {
            rotate()
        }
        FileOutputStream(activeFile, true).use { output -> output.write(bytes) }
    }

    private fun rotate() {
        val oldest = File(directory, ROTATED_FILE_2)
        val previous = File(directory, ROTATED_FILE_1)
        oldest.delete()
        if (previous.exists()) previous.renameTo(oldest)
        if (activeFile.exists()) activeFile.renameTo(previous)
    }

    companion object {
        private val FILE_LOCK = Any()
        private const val SCHEMA_VERSION = "s0-1"
        private const val ACTIVE_FILE_NAME = "timeline.jsonl"
        private const val ROTATED_FILE_1 = "timeline.1.jsonl"
        private const val ROTATED_FILE_2 = "timeline.2.jsonl"
        private const val MAX_FILE_BYTES = 2L * 1024L * 1024L
    }
}
