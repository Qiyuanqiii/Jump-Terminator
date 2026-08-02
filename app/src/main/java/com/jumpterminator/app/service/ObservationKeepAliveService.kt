package com.jumpterminator.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import com.jumpterminator.app.MainActivity
import com.jumpterminator.app.R
import com.jumpterminator.app.data.TimelineRecorder

class ObservationKeepAliveService : Service() {
    private lateinit var recorder: TimelineRecorder

    override fun onCreate() {
        super.onCreate()
        recorder = TimelineRecorder(this)
        createNotificationChannel()
        isRunning = true
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            recorder.record(
                kind = "keepalive_stopped",
                packageName = packageName,
                data = mapOf("reason" to "user_request"),
            )
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }

        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        recorder.record(
            kind = "keepalive_started",
            packageName = packageName,
            data = mapOf(
                "foregroundServiceType" to "specialUse",
                "restartPolicy" to "START_NOT_STICKY",
            ),
        )
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        isRunning = false
        if (::recorder.isInitialized) {
            recorder.record(
                kind = "keepalive_destroyed",
                packageName = packageName,
            )
        }
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                getString(R.string.observation_channel_name),
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = getString(R.string.observation_notification_text)
                setShowBadge(false)
            },
        )
    }

    private fun buildNotification(): Notification {
        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, ObservationKeepAliveService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle(getString(R.string.observation_notification_title))
            .setContentText(getString(R.string.observation_notification_text))
            .setCategory(Notification.CATEGORY_SERVICE)
            .setContentIntent(contentIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(
                Notification.Action.Builder(
                    null,
                    getString(R.string.observation_notification_stop),
                    stopIntent,
                ).build(),
            )
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "s0_observation_status"
        private const val NOTIFICATION_ID = 4101
        private const val ACTION_START = "com.jumpterminator.app.action.START_KEEPALIVE"
        private const val ACTION_STOP = "com.jumpterminator.app.action.STOP_KEEPALIVE"

        @Volatile
        var isRunning: Boolean = false
            private set

        fun start(context: Context) {
            context.startForegroundService(
                Intent(context, ObservationKeepAliveService::class.java).setAction(ACTION_START),
            )
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, ObservationKeepAliveService::class.java))
        }
    }
}
