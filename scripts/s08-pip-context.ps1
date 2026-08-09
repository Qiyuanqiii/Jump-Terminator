param(
    [ValidateRange(1, 20)]
    [int]$TargetPreexistingPipCycles = 5,
    [ValidateRange(1, 20)]
    [int]$SourcePipTargetCycles = 5,
    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 120,
    [ValidateRange(2, 15)]
    [int]$ObservationSeconds = 3,
    [string]$Serial = '',
    [string]$OutputDirectory = '',
    [string]$ReportOutput = ''
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$androidSdk = Join-Path $env:USERPROFILE '.cache\jump-terminator\toolchain\android-sdk'
$adb = Join-Path $androidSdk 'platform-tools\adb.exe'
$mainPackage = 'com.jumpterminator.app'
$pocPackage = 'com.jumpterminator.s02'
$pocComponent = 'com.jumpterminator.s02/.MainActivity'
$pocAutomationComponent = 'com.jumpterminator.s02/.AutomationActivity'
$sourcePackage = 'com.jumpterminator.testsource'
$sourceComponent = 'com.jumpterminator.testsource/.SourceActivity'
$targetPackage = 'com.jumpterminator.testtarget'
$targetComponent = 'com.jumpterminator.testtarget/.TargetActivity'
$shizukuPackage = 'moe.shizuku.privileged.api'
$shizukuPermission = 'moe.shizuku.manager.permission.API_V23'
$companionProcess = 'com.jumpterminator.s02:s02_companion'
$companionLogTag = 'JT_S02_SHIZUKU'
$pipLogTag = 'JT_S08_PIP'
$writer = $null
$currentScenario = ''
$currentCycle = 0
$currentSessionId = ''
$seenCompanionEvents = [System.Collections.Generic.HashSet[string]]::new()
$companionEventLines = [System.Collections.Generic.List[string]]::new()
$seenPipEvents = [System.Collections.Generic.HashSet[string]]::new()
$pipEventLines = [System.Collections.Generic.List[string]]::new()
$embeddedEventsWritten = $false

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

function Get-DeviceElapsedRealtimeMs {
    $uptime = ((Invoke-AdbText @('shell', 'cat', '/proc/uptime')) -join '').Trim()
    $token = ($uptime -split '\s+')[0]
    $seconds = [double]::Parse(
        $token,
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::InvariantCulture
    )
    return [int64][Math]::Round($seconds * 1000.0)
}

function Get-Sha256 {
    param([string]$Value)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        $digest = $algorithm.ComputeHash($bytes)
        return ([BitConverter]::ToString($digest)).Replace('-', '')
    } finally {
        $algorithm.Dispose()
    }
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
    $null = $processLines[0] -match '^\S+\s+(?<pid>\d+)'
    return [int]$Matches.pid
}

function Stop-ExactShellProcess {
    param([string]$ProcessName)
    $processId = Get-ExactProcessPid (Get-ProcessTable) $ProcessName 'shell'
    if ($processId -eq 0) { return }
    $null = Invoke-AdbText @('shell', 'kill', "$processId")
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 3) {
        Start-Sleep -Milliseconds 200
        if ((Get-ExactProcessPid (Get-ProcessTable) $ProcessName 'shell') -eq 0) { return }
    }
    $null = Invoke-AdbText @('shell', 'kill', '-9', "$processId")
    Start-Sleep -Milliseconds 500
    if ((Get-ExactProcessPid (Get-ProcessTable) $ProcessName 'shell') -ne 0) {
        throw "Unable to stop exact shell process: $ProcessName"
    }
}

function Get-ShizukuServerPid {
    return Get-ExactProcessPid (Get-ProcessTable) 'shizuku_server' 'shell'
}

function Start-ShizukuServer {
    if ((Get-ShizukuServerPid) -ne 0) { return }
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
        if ((Get-ShizukuServerPid) -ne 0) { return }
    }
    throw 'Shizuku server did not start.'
}

function Test-ShizukuPermissionGranted {
    $packageState = (Invoke-AdbText @('shell', 'dumpsys', 'package', $pocPackage)) -join "`n"
    return $packageState -match ([regex]::Escape($shizukuPermission) + ': granted=true')
}

function Assert-RegularObserverDisarmed {
    $settingsXml = (Invoke-AdbText @(
        'shell', 'run-as', $mainPackage, 'cat', 'shared_prefs/s0_settings.xml'
    )) -join "`n"
    if ($settingsXml -match '<boolean name="armed" value="true"') {
        throw 'The regular S0 observer is armed. Disarm it before S0.8.'
    }
}

function Get-ActivitySnapshot {
    $activityState = (Invoke-AdbText @('shell', 'dumpsys', 'activity', 'activities')) -join "`n"
    $captureWallClockMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $captureElapsedRealtimeMs = Get-DeviceElapsedRealtimeMs
    $displayIds = [System.Collections.Generic.HashSet[int]]::new()
    $topKeys = [System.Collections.Generic.HashSet[string]]::new()
    $topResumed = [System.Collections.Generic.List[object]]::new()
    $tasks = [System.Collections.Generic.List[object]]::new()
    $taskMap = @{}
    $currentDisplayId = -1
    $activeTask = $null

    foreach ($line in ($activityState -split "`n")) {
        if ($line -match '^Display #(?<displayId>\d+)') {
            $currentDisplayId = [int]$Matches.displayId
            $null = $displayIds.Add($currentDisplayId)
            $activeTask = $null
            continue
        }
        if ($currentDisplayId -lt 0) { continue }

        if ($line -match '^\s*\* Task\{.*#(?<taskId>\d+).*\bmode=(?<mode>[A-Za-z0-9_-]+)') {
            $taskId = [int]$Matches.taskId
            $windowingMode = $Matches.mode
            $packageName = $null
            if ($line -match '\sA=\d+:(?<package>[A-Za-z0-9._]+)(?:\s|$)') {
                $packageName = $Matches.package
            } elseif ($line -match '\sI=(?<component>[A-Za-z0-9._]+/[A-Za-z0-9._$]+)(?:\s|$)') {
                $packageName = ($Matches.component -split '/')[0]
            }
            $visible = $null
            if ($line -match '\bvisible=(?<visible>true|false)') {
                $visible = $Matches.visible -eq 'true'
            }
            $key = "$currentDisplayId|$taskId|$windowingMode|$packageName"
            if ($taskMap.ContainsKey($key)) {
                $activeTask = $taskMap[$key]
            } else {
                $activeTask = [pscustomobject]([ordered]@{
                    displayId = $currentDisplayId
                    taskId = $taskId
                    packageName = $packageName
                    windowingMode = $windowingMode
                    visible = $visible
                    activityComponents = [System.Collections.Generic.List[string]]::new()
                })
                $taskMap[$key] = $activeTask
                $null = $tasks.Add($activeTask)
            }
            continue
        }

        if ($line -match 'topResumedActivity=.*\su\d+\s+(?<component>[A-Za-z0-9._]+/[A-Za-z0-9._$]+)') {
            $component = $Matches.component
            $key = "$currentDisplayId|$component"
            if ($topKeys.Add($key)) {
                $null = $topResumed.Add([pscustomobject]([ordered]@{
                    displayId = $currentDisplayId
                    component = $component
                }))
            }
        }

        if (
            $activeTask -ne $null -and
            $line -match 'ActivityRecord\{[^}]*\su\d+\s+(?<component>[A-Za-z0-9._]+/[A-Za-z0-9._$]+)'
        ) {
            $component = $Matches.component
            if (-not $activeTask.activityComponents.Contains($component)) {
                $null = $activeTask.activityComponents.Add($component)
            }
        }
    }

    $normalizedTasks = @(
        $tasks |
            Where-Object { $_.visible -eq $true } |
            Sort-Object displayId, taskId, windowingMode, packageName |
            ForEach-Object {
                [pscustomobject]([ordered]@{
                    displayId = $_.displayId
                    taskId = $_.taskId
                    packageName = $_.packageName
                    windowingMode = $_.windowingMode
                    visible = $_.visible
                    activityComponents = @($_.activityComponents)
                })
            }
    )
    $normalizedTop = @($topResumed | Sort-Object displayId, component)
    $displays = @(
        foreach ($displayId in @($displayIds | Sort-Object)) {
            [pscustomobject]([ordered]@{
                displayId = $displayId
                topResumedComponents = @(
                    $normalizedTop |
                        Where-Object { $_.displayId -eq $displayId } |
                        ForEach-Object { $_.component }
                )
                tasks = @($normalizedTasks | Where-Object { $_.displayId -eq $displayId })
            })
        }
    )
    $pinnedTasks = @($normalizedTasks | Where-Object { $_.windowingMode -eq 'pinned' })
    return [pscustomobject]([ordered]@{
        schema = 's0.8-activity-snapshot-1'
        capturedWallClockMs = $captureWallClockMs
        capturedElapsedRealtimeMs = $captureElapsedRealtimeMs
        rawActivitySha256 = Get-Sha256 $activityState
        pictureInPictureActive = $pinnedTasks.Count -gt 0
        pictureInPictureReportedCount = [regex]::Matches(
            $activityState,
            'mLastReportedPictureInPictureMode=true'
        ).Count
        displays = $displays
        topResumed = $normalizedTop
        windowingTasks = $normalizedTasks
        pinnedTasks = $pinnedTasks
    })
}

function Test-PinnedPackage {
    param(
        [object]$Snapshot,
        [string]$PackageName
    )
    return @(
        $Snapshot.pinnedTasks |
            Where-Object {
                $_.packageName -eq $PackageName -and $_.windowingMode -eq 'pinned'
            }
    ).Count -gt 0
}

function Test-TopComponent {
    param(
        [object]$Snapshot,
        [string]$Component
    )
    return @($Snapshot.topResumed | ForEach-Object { $_.component }) -contains $Component
}

function Wait-PinnedPackage {
    param(
        [string]$PackageName,
        [int]$Seconds = 20,
        [ValidateRange(0, 5000)]
        [int]$StableMilliseconds = 500
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $stableTimer = $null
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        $snapshot = Get-ActivitySnapshot
        if (Test-PinnedPackage $snapshot $PackageName) {
            if ($null -eq $stableTimer) {
                $stableTimer = [System.Diagnostics.Stopwatch]::StartNew()
            }
            if ($stableTimer.ElapsedMilliseconds -ge $StableMilliseconds) { return $snapshot }
        } else {
            $stableTimer = $null
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for system-confirmed mode=pinned package: $PackageName"
}

function Wait-TopComponent {
    param(
        [string]$Component,
        [string]$PinnedPackage = '',
        [string]$NotPinnedPackage = '',
        [int]$Seconds = 20,
        [ValidateRange(0, 5000)]
        [int]$StableMilliseconds = 350
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $stableTimer = $null
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        $snapshot = Get-ActivitySnapshot
        $matches = Test-TopComponent $snapshot $Component
        if ($PinnedPackage) {
            $matches = $matches -and (Test-PinnedPackage $snapshot $PinnedPackage)
        }
        if ($NotPinnedPackage) {
            $matches = $matches -and -not (Test-PinnedPackage $snapshot $NotPinnedPackage)
        }
        if ($matches) {
            if ($null -eq $stableTimer) {
                $stableTimer = [System.Diagnostics.Stopwatch]::StartNew()
            }
            if ($stableTimer.ElapsedMilliseconds -ge $StableMilliseconds) { return $snapshot }
        } else {
            $stableTimer = $null
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for top-resumed component: $Component"
}

function Initialize-SessionEventCollections {
    $script:seenCompanionEvents = [System.Collections.Generic.HashSet[string]]::new()
    $script:companionEventLines = [System.Collections.Generic.List[string]]::new()
    $script:seenPipEvents = [System.Collections.Generic.HashSet[string]]::new()
    $script:pipEventLines = [System.Collections.Generic.List[string]]::new()
    $script:embeddedEventsWritten = $false
}

function Collect-CompanionEvents {
    $lines = @(& $adb -s $script:Serial logcat -d -v raw -s "${companionLogTag}:I" '*:S')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read companion logcat.' }
    foreach ($line in $lines) {
        $candidate = $line.Trim()
        if (-not $candidate.StartsWith('{') -or -not $candidate.Contains($script:currentSessionId)) {
            continue
        }
        try { $event = $candidate | ConvertFrom-Json } catch { continue }
        if ($event.schema -ne 's0.2-1' -or $event.sessionId -ne $script:currentSessionId) { continue }
        if ($script:seenCompanionEvents.Add($candidate)) {
            $null = $script:companionEventLines.Add($candidate)
        }
    }
}

function Collect-PipEvents {
    $lines = @(& $adb -s $script:Serial logcat -d -v raw -s "${pipLogTag}:I" '*:S')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read PiP harness logcat.' }
    foreach ($line in $lines) {
        $candidate = $line.Trim()
        if (-not $candidate.StartsWith('{') -or -not $candidate.Contains($script:currentSessionId)) {
            continue
        }
        try { $event = $candidate | ConvertFrom-Json } catch { continue }
        if ($event.schema -ne 's0.8-pip-1' -or $event.sessionId -ne $script:currentSessionId) { continue }
        if ($script:seenPipEvents.Add($candidate)) {
            $null = $script:pipEventLines.Add($candidate)
        }
    }
}

function Get-EventValue {
    param(
        [object]$Event,
        [string]$Name
    )
    $property = $Event.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    $dataProperty = $Event.PSObject.Properties['data']
    if ($null -ne $dataProperty -and $null -ne $dataProperty.Value) {
        $nested = $dataProperty.Value.PSObject.Properties[$Name]
        if ($null -ne $nested) { return $nested.Value }
    }
    return $null
}

function Test-CompanionEvent {
    param(
        [string]$Kind,
        [hashtable]$ExpectedData = @{},
        [string[]]$RequiredComponents = @(),
        [string]$RequiredPinnedPackage = ''
    )
    foreach ($line in $script:companionEventLines) {
        $event = $line | ConvertFrom-Json
        if ($event.kind -ne $Kind) { continue }
        $matches = $true
        foreach ($key in $ExpectedData.Keys) {
            if ((Get-EventValue $event $key) -ne $ExpectedData[$key]) {
                $matches = $false
                break
            }
        }
        if (-not $matches) { continue }
        $components = @($event.data.resumedComponents)
        if (@($RequiredComponents | Where-Object { $_ -notin $components }).Count -gt 0) { continue }
        if ($RequiredPinnedPackage -and $RequiredPinnedPackage -notin @($event.data.pinnedPackages)) {
            continue
        }
        return $true
    }
    return $false
}

function Wait-CompanionEvent {
    param(
        [string]$Kind,
        [hashtable]$ExpectedData = @{},
        [string[]]$RequiredComponents = @(),
        [string]$RequiredPinnedPackage = '',
        [int]$Seconds = 20
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        Collect-CompanionEvents
        if (Test-CompanionEvent $Kind $ExpectedData $RequiredComponents $RequiredPinnedPackage) {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for companion event: kind=$Kind"
}

function Test-PipEvent {
    param(
        [string]$Role,
        [string]$Kind,
        [hashtable]$ExpectedData = @{}
    )
    foreach ($line in $script:pipEventLines) {
        $event = $line | ConvertFrom-Json
        if ($event.role -ne $Role -or $event.kind -ne $Kind) { continue }
        $matches = $true
        foreach ($key in $ExpectedData.Keys) {
            if ((Get-EventValue $event $key) -ne $ExpectedData[$key]) {
                $matches = $false
                break
            }
        }
        if ($matches) { return $true }
    }
    return $false
}

function Wait-PipEvent {
    param(
        [string]$Role,
        [string]$Kind,
        [hashtable]$ExpectedData = @{},
        [int]$Seconds = 20
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        Collect-PipEvents
        if (Test-PipEvent $Role $Kind $ExpectedData) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for PiP event: role=$Role kind=$Kind"
}

function Write-S08Event {
    param(
        [string]$Kind,
        [System.Collections.IDictionary]$Data
    )
    $elapsedRealtimeMs = $null
    try { $elapsedRealtimeMs = Get-DeviceElapsedRealtimeMs } catch { }
    $payload = [ordered]@{
        schema = 's0.8-1'
        scenario = $script:currentScenario
        cycle = $script:currentCycle
        sessionId = $script:currentSessionId
        kind = $Kind
        wallClockMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        elapsedRealtimeMs = $elapsedRealtimeMs
        data = $Data
    }
    $script:writer.WriteLine(($payload | ConvertTo-Json -Depth 24 -Compress))
    $script:writer.Flush()
}

function Write-EmbeddedEvents {
    if ($script:embeddedEventsWritten) { return }
    Collect-CompanionEvents
    Collect-PipEvents
    foreach ($line in $script:companionEventLines) {
        Write-S08Event 'companion_event' ([ordered]@{
            raw = $line
            event = ($line | ConvertFrom-Json)
        })
    }
    foreach ($line in $script:pipEventLines) {
        Write-S08Event 'pip_event' ([ordered]@{
            raw = $line
            event = ($line | ConvertFrom-Json)
        })
    }
    $script:embeddedEventsWritten = $true
}

function Stop-ProbeAndTestApps {
    try {
        if ((Get-ExactProcessPid (Get-ProcessTable) $companionProcess 'shell') -ne 0) {
            $null = Invoke-AdbText @(
                'shell', 'am', 'start', '-n', $pocAutomationComponent,
                '--es', 'jt_s02_control', 'stop'
            )
            Start-Sleep -Milliseconds 500
        }
    } catch { }
    foreach ($packageName in @($sourcePackage, $targetPackage, $pocPackage)) {
        try { $null = Invoke-AdbText @('shell', 'am', 'force-stop', $packageName) } catch { }
    }
    try { Stop-ExactShellProcess $companionProcess } catch { }
}

function Start-ProbeOnly {
    Start-ShizukuServer
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $pocAutomationComponent,
        '--es', 'jt_s02_session', $script:currentSessionId,
        '--ei', 'jt_s02_max_actions', '1',
        '--ei', 'jt_s02_requested_allowed', '0',
        '--ez', 'jt_s02_armed', 'true'
    )
    Wait-CompanionEvent -Kind 'ready' -Seconds 20
}

function Stop-ProbeMonitorAndCollect {
    Write-S08Event 'monitor_stop_requested' ([ordered]@{
        observationSeconds = $ObservationSeconds
    })
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $pocAutomationComponent,
        '--es', 'jt_s02_control', 'stop'
    )
    Wait-CompanionEvent `
        -Kind 'complete' `
        -ExpectedData @{ reason = 'stop_requested' } `
        -Seconds 20
    Start-Sleep -Milliseconds 500
    Collect-CompanionEvents
    Collect-PipEvents
}

function Invoke-TargetPreexistingPipScenario {
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $sourceComponent,
        '--es', 'jt_s08_session', $script:currentSessionId
    )
    $null = Wait-TopComponent -Component $sourceComponent -Seconds 20
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $targetComponent,
        '--ez', 'jt_s08_enter_pip', 'true',
        '--es', 'jt_s08_session', $script:currentSessionId
    )
    Wait-PipEvent -Role 'target' -Kind 'pip_requested' -ExpectedData @{ accepted = $true }
    Wait-PipEvent -Role 'target' -Kind 'pip_mode_changed' -ExpectedData @{ active = $true }
    $pinned = Wait-PinnedPackage -PackageName $targetPackage -Seconds 20
    Write-S08Event 'pip_entered' ([ordered]@{
        expectedPinnedPackage = $targetPackage
        snapshot = $pinned
    })

    Start-ProbeOnly
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $sourceComponent,
        '--es', 'jt_s08_session', $script:currentSessionId
    )
    $sourceWithPip = Wait-TopComponent `
        -Component $sourceComponent `
        -PinnedPackage $targetPackage `
        -Seconds 20
    Wait-CompanionEvent `
        -Kind 'foreground_changed' `
        -ExpectedData @{ state = 'picture_in_picture'; pictureInPictureActive = $true } `
        -RequiredPinnedPackage $targetPackage `
        -Seconds 20
    Write-S08Event 'source_presented_with_pip' ([ordered]@{
        snapshot = $sourceWithPip
    })

    $boundary = Wait-TopComponent `
        -Component $sourceComponent `
        -PinnedPackage $targetPackage `
        -Seconds 20
    Write-S08Event 'pip_boundary_observed' ([ordered]@{
        operation = 'expand_pinned_target'
        expectedPinnedPackage = $targetPackage
        snapshot = $boundary
    })
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $targetComponent,
        '--es', 'jt_s08_session', $script:currentSessionId
    )
    $presented = Wait-TopComponent `
        -Component $targetComponent `
        -NotPinnedPackage $targetPackage `
        -Seconds 20
    Write-S08Event 'target_presented' ([ordered]@{
        exitCode = 0
        transition = 'expanded_from_pip'
        snapshot = $presented
    })
    Wait-CompanionEvent `
        -Kind 'foreground_changed' `
        -RequiredComponents @($targetComponent) `
        -Seconds 20
}

function Invoke-SourcePipTargetScenario {
    Start-ProbeOnly
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $targetComponent,
        '--es', 'jt_s08_session', $script:currentSessionId
    )
    $targetUnderlay = Wait-TopComponent -Component $targetComponent -Seconds 20
    Write-S08Event 'target_underlay_ready' ([ordered]@{
        exitCode = 0
        snapshot = $targetUnderlay
    })

    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $sourceComponent,
        '--ez', 'jt_s08_enter_pip', 'true',
        '--es', 'jt_s08_session', $script:currentSessionId
    )
    Wait-PipEvent -Role 'source' -Kind 'pip_scheduled' -ExpectedData @{ delayMs = 1500 }
    Wait-CompanionEvent `
        -Kind 'foreground_changed' `
        -ExpectedData @{ state = 'source'; pictureInPictureActive = $false } `
        -RequiredComponents @($sourceComponent) `
        -Seconds 20
    $sourceObserved = Get-ActivitySnapshot
    Write-S08Event 'source_observed' ([ordered]@{
        snapshot = $sourceObserved
    })

    Wait-PipEvent -Role 'source' -Kind 'pip_requested' -ExpectedData @{ accepted = $true }
    Wait-PipEvent -Role 'source' -Kind 'pip_mode_changed' -ExpectedData @{ active = $true }
    $boundary = Wait-TopComponent `
        -Component $targetComponent `
        -PinnedPackage $sourcePackage `
        -Seconds 20
    Wait-CompanionEvent `
        -Kind 'foreground_changed' `
        -ExpectedData @{ state = 'picture_in_picture'; pictureInPictureActive = $true } `
        -RequiredComponents @($targetComponent) `
        -RequiredPinnedPackage $sourcePackage `
        -Seconds 20
    Wait-CompanionEvent `
        -Kind 'source_context_invalidated' `
        -ExpectedData @{ reason = 'picture_in_picture'; pictureInPictureActive = $true } `
        -RequiredPinnedPackage $sourcePackage `
        -Seconds 20
    Write-S08Event 'pip_boundary_observed' ([ordered]@{
        operation = 'source_pip_reveals_target'
        expectedPinnedPackage = $sourcePackage
        snapshot = $boundary
    })
    Write-S08Event 'target_presented' ([ordered]@{
        exitCode = 0
        transition = 'revealed_by_source_pip'
        snapshot = $boundary
    })
}

function Invoke-PipScenario {
    param(
        [ValidateSet('target-preexisting-pip', 'source-pip-target')]
        [string]$Scenario,
        [int]$Cycle
    )
    $script:currentScenario = $Scenario
    $script:currentCycle = $Cycle
    $script:currentSessionId = [Guid]::NewGuid().ToString('N')
    Initialize-SessionEventCollections
    Write-Output "S0.8 $Scenario cycle $Cycle started (session=$($script:currentSessionId))"
    try {
        Stop-ProbeAndTestApps
        Write-S08Event 'scenario_started' ([ordered]@{
            model = ((Invoke-AdbText @('shell', 'getprop', 'ro.product.model')) -join '').Trim()
            androidRelease = ((Invoke-AdbText @('shell', 'getprop', 'ro.build.version.release')) -join '').Trim()
        })
        if ($Scenario -eq 'target-preexisting-pip') {
            Invoke-TargetPreexistingPipScenario
        } else {
            Invoke-SourcePipTargetScenario
        }

        Start-Sleep -Seconds $ObservationSeconds
        Stop-ProbeMonitorAndCollect
        $targetDetections = @(
            $script:companionEventLines |
                Where-Object { (($_ | ConvertFrom-Json).kind) -eq 'target_detected' }
        ).Count
        $backRequests = @(
            $script:companionEventLines |
                Where-Object { (($_ | ConvertFrom-Json).kind) -eq 'back_requested' }
        ).Count
        $monitorCompletionObserved = Test-CompanionEvent `
            -Kind 'complete' `
            -ExpectedData @{ reason = 'stop_requested' }
        Write-EmbeddedEvents
        Write-S08Event 'scenario_complete' ([ordered]@{
            result = if ($targetDetections -eq 0 -and $backRequests -eq 0) {
                'zero_action_observed'
            } else {
                'unsafe_action_observed'
            }
            targetDetections = $targetDetections
            backRequests = $backRequests
            monitorCompletionObserved = $monitorCompletionObserved
        })
    } catch {
        try { Write-EmbeddedEvents } catch { }
        try {
            Write-S08Event 'runner_error' ([ordered]@{
                type = $_.Exception.GetType().FullName
                message = $_.Exception.Message
            })
        } catch { }
        Write-Warning "S0.8 $Scenario cycle $Cycle is NOT_READY: $($_.Exception.Message)"
    } finally {
        Stop-ProbeAndTestApps
        try { $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3') } catch { }
    }
}

function Invoke-ChildPowerShell {
    param(
        [string]$Path,
        [string[]]$Arguments
    )
    $powershell = Join-Path $PSHOME 'powershell.exe'
    & $powershell -NoProfile -ExecutionPolicy Bypass -File $Path @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Child runner failed with exit code ${LASTEXITCODE}: $Path"
    }
}

Resolve-DeviceSerial

foreach ($packageName in @($mainPackage, $pocPackage, $sourcePackage, $targetPackage, $shizukuPackage)) {
    $packagePath = Invoke-AdbText @('shell', 'pm', 'path', $packageName)
    if (-not $packagePath) { throw "Required package is not installed: $packageName" }
}
$pocPackageState = (Invoke-AdbText @('shell', 'dumpsys', 'package', $pocPackage)) -join "`n"
if ($pocPackageState -notmatch '(?m)^\s*versionName=0\.0\.8-s08\s*$') {
    throw 'S0.8 requires the 0.0.8-s08 POC APK.'
}
$sourcePackageState = (Invoke-AdbText @('shell', 'dumpsys', 'package', $sourcePackage)) -join "`n"
if ($sourcePackageState -notmatch '(?m)^\s*versionName=0\.0\.8-s08\s*$') {
    throw 'S0.8 requires the 0.0.8-s08 source harness APK.'
}
$targetPackageState = (Invoke-AdbText @('shell', 'dumpsys', 'package', $targetPackage)) -join "`n"
if ($targetPackageState -notmatch '(?m)^\s*versionName=0\.0\.4-s08\s*$') {
    throw 'S0.8 requires the 0.0.4-s08 target harness APK.'
}
$features = (Invoke-AdbText @('shell', 'pm', 'list', 'features')) -join "`n"
if ($features -notmatch '(?m)^feature:android\.software\.picture_in_picture\s*$') {
    throw 'The connected device does not advertise picture-in-picture support.'
}
Assert-RegularObserverDisarmed
Start-ShizukuServer
if (-not (Test-ShizukuPermissionGranted)) {
    throw 'The POC Shizuku permission must be granted before S0.8.'
}
$powerState = (Invoke-AdbText @('shell', 'dumpsys', 'power')) -join "`n"
$windowState = (Invoke-AdbText @('shell', 'dumpsys', 'window')) -join "`n"
if ($powerState -notmatch 'mWakefulness=Awake') {
    throw 'Device must be awake before S0.8.'
}
if ($windowState -match 'mDreamingLockscreen=true|mShowingLockscreen=true|isStatusBarKeyguard=true|mInputRestricted=true') {
    throw 'Device must be unlocked before S0.8.'
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $workspaceRoot "docs\s08\results\s08-pip-context-$timestamp"
}
$outputDirectoryPath = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($outputDirectoryPath) | Out-Null
$timelinePath = Join-Path $outputDirectoryPath 's08-pip-context.jsonl'
$positiveTimelinePath = Join-Path $outputDirectoryPath 's08-fullscreen-positive.jsonl'
$positiveReportPath = Join-Path $outputDirectoryPath 's08-fullscreen-positive.report.json'
if (-not $ReportOutput) {
    $ReportOutput = Join-Path $outputDirectoryPath 's08-pip-context.report.json'
}
$reportPath = [System.IO.Path]::GetFullPath($ReportOutput)
$script:writer = [System.IO.StreamWriter]::new(
    $timelinePath,
    $false,
    [System.Text.UTF8Encoding]::new($false)
)

try {
    foreach ($cycle in 1..$TargetPreexistingPipCycles) {
        Invoke-PipScenario -Scenario 'target-preexisting-pip' -Cycle $cycle
    }
    foreach ($cycle in 1..$SourcePipTargetCycles) {
        Invoke-PipScenario -Scenario 'source-pip-target' -Cycle $cycle
    }
} finally {
    if ($script:writer -ne $null) {
        $script:writer.Dispose()
        $script:writer = $null
    }
}

$positiveError = $null
try {
    Invoke-ChildPowerShell -Path (Join-Path $PSScriptRoot 's02-shizuku-run.ps1') -Arguments @(
        '-Scenario', 'block',
        '-BatchCount', '10',
        '-Arm',
        '-TimeoutSeconds', "$TimeoutSeconds",
        '-Serial', $script:Serial,
        '-Output', $positiveTimelinePath,
        '-ReportOutput', $positiveReportPath
    )
} catch {
    $positiveError = $_.Exception.Message
    Write-Warning "S0.8 fullscreen positive control is NOT_READY: $positiveError"
    if (-not (Test-Path -LiteralPath $positiveTimelinePath)) {
        [System.IO.File]::WriteAllText(
            $positiveTimelinePath,
            '',
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    if (-not (Test-Path -LiteralPath $positiveReportPath)) {
        $placeholder = [ordered]@{
            schema = 's0.8-positive-control-error-1'
            runnerError = $positiveError
        }
        [System.IO.File]::WriteAllText(
            $positiveReportPath,
            (($placeholder | ConvertTo-Json -Depth 5) + "`n"),
            [System.Text.UTF8Encoding]::new($false)
        )
    }
}

$reportExitCode = 0
try {
    & python (Join-Path $PSScriptRoot 's08_pip_report.py') @(
        '--timeline', $timelinePath,
        '--positive-timeline', $positiveTimelinePath,
        '--positive-report', $positiveReportPath,
        '--expected-target-preexisting-pip', "$TargetPreexistingPipCycles",
        '--expected-source-pip-target', "$SourcePipTargetCycles",
        '--output', $reportPath,
        '--strict'
    )
    $reportExitCode = $LASTEXITCODE
} finally {
    try { $null = Invoke-AdbText @('shell', 'pm', 'grant', $pocPackage, $shizukuPermission) } catch { }
    try { Start-ShizukuServer } catch { }
    Stop-ProbeAndTestApps
    try {
        $null = Invoke-AdbText @('shell', 'am', 'start', '-n', $pocComponent)
        Start-Sleep -Milliseconds 300
        $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3')
    } catch { }
    Write-Output "Output directory: $outputDirectoryPath"
    Write-Output "Timeline: $timelinePath"
    Write-Output "Report: $reportPath"
}

if ($reportExitCode -ne 0) {
    throw "S0.8 report gate did not pass (exit code $reportExitCode)."
}
