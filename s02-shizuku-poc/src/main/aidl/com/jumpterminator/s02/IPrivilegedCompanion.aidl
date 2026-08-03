package com.jumpterminator.s02;

interface IPrivilegedCompanion {
    void destroy() = 16777114;
    String startMonitor(
        String sessionId,
        int requestedBlock,
        int requestedAllowed,
        boolean armed
    ) = 1;
    String status() = 2;
    String drainEvents() = 3;
    void stopMonitor() = 4;
}
