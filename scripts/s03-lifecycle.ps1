param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('ui-kill', 'ui-force-stop', 'shizuku-graceful-stop', 'shizuku-disconnect', 'disconnect-recovery', 'reboot', 'post-reboot-recovery')]
    [string]$Scenario,
    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 120,
    [string]$Serial = '',
    [string]$Output = ''
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$androidSdk = Join-Path $env:USERPROFILE '.cache\jump-terminator\toolchain\android-sdk'
$adb = Join-Path $androidSdk 'platform-tools\adb.exe'
$mainPackage = 'com.jumpterminator.app'
$pocPackage = 'com.jumpterminator.s02'
$pocComponent = 'com.jumpterminator.s02/.MainActivity'
$sourcePackage = 'com.jumpterminator.testsource'
$sourceComponent = 'com.jumpterminator.testsource/.SourceActivity'
$targetPackage = 'com.jumpterminator.testtarget'
$shizukuPackage = 'moe.shizuku.privileged.api'
$companionLogTag = 'JT_S02_SHIZUKU'
$sessionId = [Guid]::NewGuid().ToString('N')
$seenCompanionEvents = [System.Collections.Generic.HashSet[string]]::new()
$companionEventLines = [System.Collections.Generic.List[string]]::new()

if (-not (Test-Path -LiteralPath $adb)) { throw "adb not found: $adb" }

function Resolve-DeviceSerial {
    $deviceLines = & $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" }
    $serials = @($deviceLines | ForEach-Object { ($_ -split "\t")[0] })
    if ($script:Serial) {
        if ($script:Serial -notmatch '^[A-Za-z0-9._:-]+$') {
            throw 'Device serial contains invalid characters.'
        }
        if ($script:Serial -notin $serials) {
            throw "Specified device is not connected: $script:Serial"
        }
        return
    }
    if ($serials.Count -eq 0) { throw 'No authorized ADB device found.' }
    if ($serials.Count -gt 1) { throw 'Multiple devices connected; select one with -Serial.' }
    $script:Serial = $serials[0]
}

function Invoke-AdbText {
    param([string[]]$Arguments)
    $allArguments = @('-s', $script:Serial) + $Arguments
    $output = & $adb @allArguments
    if ($LASTEXITCODE -ne 0) {
        throw "adb command failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
    return $output
}

function Write-LifecycleEvent {
    param(
        [System.IO.StreamWriter]$Writer,
        [string]$Kind,
        [System.Collections.IDictionary]$Data
    )
    $payload = [ordered]@{
        schema = 's0.3-1'
        sessionId = $script:sessionId
        scenario = $Scenario
        kind = $Kind
        wallClockMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        data = $Data
    }
    $Writer.WriteLine(($payload | ConvertTo-Json -Depth 8 -Compress))
    $Writer.Flush()
}

function Get-ProcessTable {
    return @((Invoke-AdbText @('shell', 'ps', '-A')))
}

function Get-ExactProcessPid {
    param(
        [string[]]$ProcessTable,
        [string]$ProcessName,
        [string]$ExpectedUser = ''
    )
    $escapedName = [regex]::Escape($ProcessName)
    $processLines = @(
        foreach ($line in $ProcessTable) {
            if ($line -match "^(?<user>\S+)\s+(?<pid>\d+)\s+\d+.*\s${escapedName}$") {
                if (-not $ExpectedUser -or $Matches.user -eq $ExpectedUser) { $line }
            }
        }
    )
    if ($processLines.Count -gt 1) { throw "Multiple exact processes found: $ProcessName" }
    if ($processLines.Count -eq 0) { return 0 }
    $null = $processLines[0] -match "^\S+\s+(?<pid>\d+)"
    return [int]$Matches.pid
}

function Get-PackageUid {
    param([string]$PackageName)
    $lines = Invoke-AdbText @('shell', 'dumpsys', 'package', $PackageName)
    $uidLine = $lines | Where-Object { $_ -match '^\s*userId=(?<uid>\d+)\s*$' } |
        Select-Object -First 1
    if (-not $uidLine -or $uidLine -notmatch '^\s*userId=(?<uid>\d+)\s*$') {
        throw "Unable to resolve package UID: $PackageName"
    }
    return [int]$Matches.uid
}

function Get-Snapshot {
    $processTable = Get-ProcessTable
    $bootId = ((Invoke-AdbText @('shell', 'cat', '/proc/sys/kernel/random/boot_id')) -join '').Trim()
    $windowState = (Invoke-AdbText @('shell', 'dumpsys', 'window')) -join "`n"
    return [ordered]@{
        bootId = $bootId
        bootCompleted = (((Invoke-AdbText @('shell', 'getprop', 'sys.boot_completed')) -join '').Trim() -eq '1')
        shizukuServerPid = Get-ExactProcessPid $processTable 'shizuku_server' 'shell'
        companionPid = Get-ExactProcessPid $processTable 'com.jumpterminator.s02:s02_companion' 'shell'
        uiPid = Get-ExactProcessPid $processTable 'com.jumpterminator.s02'
        sourcePid = Get-ExactProcessPid $processTable 'com.jumpterminator.testsource'
        targetPid = Get-ExactProcessPid $processTable 'com.jumpterminator.testtarget'
        pocPackageUid = Get-PackageUid $pocPackage
        keyguardLocked = [bool]($windowState -match 'mDreamingLockscreen=true|mShowingLockscreen=true|isStatusBarKeyguard=true')
    }
}

function Stop-ExactShellProcess {
    param(
        [string]$ProcessName,
        [switch]$Force,
        [switch]$NoEscalation
    )
    $processTable = Get-ProcessTable
    $processId = Get-ExactProcessPid $processTable $ProcessName 'shell'
    if ($processId -eq 0) { return }
    if ($Force) {
        $null = Invoke-AdbText @('shell', 'kill', '-9', "$processId")
        Start-Sleep -Milliseconds 500
        if ((Get-ExactProcessPid (Get-ProcessTable) $ProcessName 'shell') -ne 0) {
            throw "Unable to force-stop exact shell process: $ProcessName"
        }
        return
    }
    $null = Invoke-AdbText @('shell', 'kill', "$processId")
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 3) {
        Start-Sleep -Milliseconds 200
        if ((Get-ExactProcessPid (Get-ProcessTable) $ProcessName 'shell') -eq 0) { return }
    }
    if ($NoEscalation) {
        throw "Exact shell process did not stop after TERM: $ProcessName"
    }
    $null = Invoke-AdbText @('shell', 'kill', '-9', "$processId")
    Start-Sleep -Milliseconds 500
    if ((Get-ExactProcessPid (Get-ProcessTable) $ProcessName 'shell') -ne 0) {
        throw "Unable to stop exact shell process: $ProcessName"
    }
}

function Start-ShizukuServer {
    if ((Get-ExactProcessPid (Get-ProcessTable) 'shizuku_server' 'shell') -ne 0) { return }
    $baseApk = ((Invoke-AdbText @('shell', 'pm', 'path', $shizukuPackage)) -replace '^package:', '').Trim()
    if ($baseApk -notmatch '^/data/app/.+/base\.apk$') {
        throw "Unexpected Shizuku package path: $baseApk"
    }
    $starter = $baseApk -replace '/base\.apk$', '/lib/arm64/libshizuku.so'
    $starterInfo = Invoke-AdbText @('shell', 'ls', '-l', $starter)
    if (-not $starterInfo) { throw 'Official Shizuku starter library is unavailable.' }
    $null = Invoke-AdbText @('shell', $starter)
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 10) {
        Start-Sleep -Milliseconds 250
        if ((Get-ExactProcessPid (Get-ProcessTable) 'shizuku_server' 'shell') -ne 0) { return }
    }
    throw 'Shizuku server did not start.'
}

function Collect-CompanionEvents {
    $lines = @(& $adb -s $script:Serial logcat -d -v raw -s "${companionLogTag}:I" '*:S')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read companion logcat.' }
    foreach ($line in $lines) {
        $candidate = $line.Trim()
        if (-not $candidate.StartsWith('{') -or -not $candidate.Contains($script:sessionId)) {
            continue
        }
        try { $event = $candidate | ConvertFrom-Json } catch { continue }
        if ($event.schema -ne 's0.2-1' -or $event.sessionId -ne $script:sessionId) { continue }
        if ($script:seenCompanionEvents.Add($candidate)) {
            $script:companionEventLines.Add($candidate)
        }
    }
}

function Test-CompanionKind {
    param([string[]]$Kinds)
    foreach ($line in $script:companionEventLines) {
        $event = $line | ConvertFrom-Json
        if ($event.kind -in $Kinds) { return $true }
    }
    return $false
}

function Wait-CompanionKind {
    param(
        [string[]]$Kinds,
        [int]$Seconds
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        Collect-CompanionEvents
        if (Test-CompanionKind $Kinds) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for companion event: $($Kinds -join ', ')"
}

function Get-CompanionSummary {
    Collect-CompanionEvents
    $events = @($script:companionEventLines | ForEach-Object { $_ | ConvertFrom-Json })
    $detections = @($events | Where-Object kind -eq 'target_detected')
    $backs = @($events | Where-Object kind -eq 'back_requested')
    $leaves = @($events | Where-Object kind -eq 'left_target')
    $revocations = @($events | Where-Object kind -eq 'authorization_revoked')
    $readyEvent = @($events | Where-Object kind -eq 'ready' | Select-Object -Last 1)
    $terminal = @($events | Where-Object kind -in @('complete', 'timeout', 'service_error') | Select-Object -Last 1)
    $ownerSigningDigests = [System.Collections.Generic.List[string]]::new()
    if ($readyEvent.Count) {
        foreach ($digest in @($readyEvent[0].data.ownerSigningCertificateSha256)) {
            if ($null -ne $digest) { $ownerSigningDigests.Add([string]$digest) }
        }
    }
    return [ordered]@{
        ready = [bool](@($events | Where-Object kind -eq 'ready').Count)
        detections = $detections.Count
        backs = $backs.Count
        dispatchedBacks = @($backs | Where-Object { $_.data.dispatched }).Count
        leaves = $leaves.Count
        returnedSource = @($leaves | Where-Object { $_.data.returnedSource }).Count
        terminalKind = if ($terminal.Count) { $terminal[0].kind } else { $null }
        terminalReason = if ($terminal.Count) { $terminal[0].data.reason } else { $null }
        serviceErrors = @($events | Where-Object kind -eq 'service_error').Count
        timeouts = @($events | Where-Object kind -eq 'timeout').Count
        authorizationRevocations = $revocations.Count
        authorizationReasons = @($revocations | ForEach-Object { $_.data.reason } | Sort-Object -Unique)
        ownerDetachments = @($events | Where-Object kind -eq 'owner_detached').Count
        serviceExitRequests = @($events | Where-Object kind -eq 'service_exit_requested').Count
        authorizationProtocol = if ($readyEvent.Count) { $readyEvent[0].data.authorizationProtocol } else { $null }
        ownerUidSource = if ($readyEvent.Count) { $readyEvent[0].data.ownerUidSource } else { $null }
        ownerUid = if ($readyEvent.Count) { $readyEvent[0].data.ownerUid } else { $null }
        ownerUserId = if ($readyEvent.Count) { $readyEvent[0].data.ownerUserId } else { $null }
        ownerPackage = if ($readyEvent.Count) { $readyEvent[0].data.ownerPackage } else { $null }
        ownerSigningCertificateSha256 = $ownerSigningDigests
        oneTimeCapability = if ($readyEvent.Count) { $readyEvent[0].data.oneTimeCapability } else { $false }
        capabilityFingerprint = if ($readyEvent.Count) { $readyEvent[0].data.capabilityFingerprint } else { $null }
        ruleSnapshotSha256 = if ($readyEvent.Count) { $readyEvent[0].data.ruleSnapshotSha256 } else { $null }
        leaseDurationMs = if ($readyEvent.Count) { $readyEvent[0].data.leaseDurationMs } else { $null }
        finalActionSerialization = if ($readyEvent.Count) { $readyEvent[0].data.finalActionSerialization } else { $null }
    }
}

function Assert-RegularObserverDisarmed {
    $settingsXml = (Invoke-AdbText @(
        'shell', 'run-as', $mainPackage, 'cat', 'shared_prefs/s0_settings.xml'
    )) -join "`n"
    if ($settingsXml -match '<boolean name="armed" value="true"') {
        throw 'The regular S0 observer is armed. Disarm it before lifecycle testing.'
    }
}

function Start-CompanionProbe {
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $pocComponent,
        '--es', 'jt_s02_session', $script:sessionId,
        '--ei', 'jt_s02_max_actions', '1',
        '--ei', 'jt_s02_requested_allowed', '0',
        '--ez', 'jt_s02_armed', 'true'
    )
    Wait-CompanionKind @('ready') 20
}

function Start-ControlledTransition {
    $null = Invoke-AdbText @('shell', 'am', 'force-stop', $targetPackage)
    $null = Invoke-AdbText @('shell', 'am', 'force-stop', $sourcePackage)
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $sourceComponent,
        '--ei', 'jt_s02_batch_count', '1'
    )
    Wait-CompanionKind @('complete', 'timeout', 'service_error') $TimeoutSeconds
}

function Start-UnmonitoredTransition {
    $null = Invoke-AdbText @('shell', 'am', 'force-stop', $targetPackage)
    $null = Invoke-AdbText @('shell', 'am', 'force-stop', $sourcePackage)
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $sourceComponent,
        '--ei', 'jt_s02_batch_count', '1'
    )
    Start-Sleep -Seconds 4
    Collect-CompanionEvents
}

function Wait-BootCompleted {
    $null = & $adb -s $script:Serial wait-for-device
    if ($LASTEXITCODE -ne 0) { throw 'adb wait-for-device failed after reboot.' }
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 240) {
        try {
            $value = ((Invoke-AdbText @('shell', 'getprop', 'sys.boot_completed')) -join '').Trim()
            if ($value -eq '1') { return }
        } catch { }
        Start-Sleep -Seconds 2
    }
    throw 'Device did not report sys.boot_completed=1 within 240 seconds.'
}

Resolve-DeviceSerial

foreach ($packageName in @($mainPackage, $pocPackage, $sourcePackage, $targetPackage, $shizukuPackage)) {
    $packagePath = Invoke-AdbText @('shell', 'pm', 'path', $packageName)
    if (-not $packagePath) { throw "Required package is not installed: $packageName" }
}
Assert-RegularObserverDisarmed

$initialSnapshot = Get-Snapshot
if ($Scenario -ne 'reboot' -and $initialSnapshot.keyguardLocked) {
    throw 'Device is locked. Unlock it before running an interactive lifecycle scenario.'
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $Output) {
    $Output = Join-Path $workspaceRoot "docs\s03\results\s03-$Scenario-$timestamp.jsonl"
}
$outputPath = [System.IO.Path]::GetFullPath($Output)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($outputPath)) | Out-Null
$writer = [System.IO.StreamWriter]::new($outputPath, $false, [System.Text.UTF8Encoding]::new($false))
$runFailed = $false

try {
    Write-LifecycleEvent $writer 'scenario_started' @{
        model = ((Invoke-AdbText @('shell', 'getprop', 'ro.product.model')) -join '').Trim()
        androidRelease = ((Invoke-AdbText @('shell', 'getprop', 'ro.build.version.release')) -join '').Trim()
    }

    if ($Scenario -eq 'reboot') {
        foreach ($packageName in @($sourcePackage, $targetPackage, $pocPackage)) {
            $null = Invoke-AdbText @('shell', 'am', 'force-stop', $packageName)
        }
        Stop-ExactShellProcess 'com.jumpterminator.s02:s02_companion'
        Stop-ExactShellProcess 'shizuku_server'
        Write-LifecycleEvent $writer 'pre_reboot' (Get-Snapshot)
        $null = Invoke-AdbText @('reboot')
        Wait-BootCompleted
        Start-Sleep -Seconds 5
        Write-LifecycleEvent $writer 'post_reboot' (Get-Snapshot)
        Write-LifecycleEvent $writer 'scenario_complete' @{ result = 'observed' }
    } else {
        Stop-ExactShellProcess 'com.jumpterminator.s02:s02_companion'
        Start-ShizukuServer
        Start-CompanionProbe
        Write-LifecycleEvent $writer 'probe_ready' (Get-Snapshot)

        switch ($Scenario) {
            'ui-kill' {
                $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3')
                Start-Sleep -Milliseconds 500
                $null = Invoke-AdbText @('shell', 'am', 'crash', '--user', '0', $pocPackage)
            }
            'ui-force-stop' {
                $null = Invoke-AdbText @('shell', 'am', 'force-stop', $pocPackage)
            }
            'shizuku-disconnect' {
                Stop-ExactShellProcess 'shizuku_server' -Force
            }
            'shizuku-graceful-stop' {
                Stop-ExactShellProcess 'shizuku_server' -NoEscalation
            }
            'post-reboot-recovery' {
                # No fault injection: this proves the server, grant, bind and action recover.
            }
            'disconnect-recovery' {
                # No fault injection: this proves restart, existing grant and rebind.
            }
        }
        Start-Sleep -Seconds 1
        $faultSnapshot = Get-Snapshot
        Write-LifecycleEvent $writer 'fault_injected' $faultSnapshot
        switch ($Scenario) {
            'ui-kill' {
                if ($faultSnapshot.uiPid -ne 0 -or $faultSnapshot.companionPid -eq 0) {
                    throw 'UI crash injection did not leave only the privileged companion alive.'
                }
            }
            'ui-force-stop' {
                if ($faultSnapshot.uiPid -ne 0) {
                    throw 'UI force-stop injection did not stop the package UI process.'
                }
            }
            'shizuku-disconnect' {
                if ($faultSnapshot.shizukuServerPid -ne 0) {
                    throw 'Abrupt Shizuku disconnect injection did not stop the server.'
                }
            }
            'shizuku-graceful-stop' {
                if ($faultSnapshot.shizukuServerPid -ne 0) {
                    throw 'Graceful Shizuku stop injection did not stop the server.'
                }
            }
        }
        if ($Scenario -in @('ui-force-stop', 'shizuku-disconnect', 'shizuku-graceful-stop')) {
            Start-UnmonitoredTransition
        } else {
            Start-ControlledTransition
        }
        Write-LifecycleEvent $writer 'companion_result' (Get-CompanionSummary)
        Write-LifecycleEvent $writer 'post_transition' (Get-Snapshot)
        Write-LifecycleEvent $writer 'scenario_complete' @{ result = 'observed' }
    }
} catch {
    $runFailed = $true
    Write-LifecycleEvent $writer 'runner_error' @{
        type = $_.Exception.GetType().FullName
        message = $_.Exception.Message
    }
    throw
} finally {
    try { Stop-ExactShellProcess 'com.jumpterminator.s02:s02_companion' } catch { }
    try { Stop-ExactShellProcess 'shizuku_server' } catch { }
    foreach ($packageName in @($sourcePackage, $targetPackage, $pocPackage)) {
        try { $null = Invoke-AdbText @('shell', 'am', 'force-stop', $packageName) } catch { }
    }
    try { $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3') } catch { }
    try { Write-LifecycleEvent $writer 'cleanup_complete' (Get-Snapshot) } catch { }
    $writer.Dispose()
    Write-Output "Timeline: $outputPath"
    Write-Output "Session: $sessionId"
}

if ($runFailed) { exit 1 }
