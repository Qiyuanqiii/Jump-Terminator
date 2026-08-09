param(
    [ValidateRange(1, 20)]
    [int]$RecentsCycles = 5,
    [ValidateRange(1, 20)]
    [int]$SplitScreenCycles = 5,
    [ValidateRange(1, 5)]
    [int]$ScreenLockCycles = 1,
    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 120,
    [ValidateRange(30, 600)]
    [int]$UnlockWaitSeconds = 180,
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
$writer = $null
$currentScenario = ''
$currentCycle = 0
$currentSessionId = ''
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
        throw 'The regular S0 observer is armed. Disarm it before S0.7.'
    }
}

function Get-DeviceSnapshot {
    $activityState = (Invoke-AdbText @('shell', 'dumpsys', 'activity', 'activities')) -join "`n"
    $powerState = (Invoke-AdbText @('shell', 'dumpsys', 'power')) -join "`n"
    $windowState = (Invoke-AdbText @('shell', 'dumpsys', 'window')) -join "`n"
    $components = [System.Collections.Generic.List[string]]::new()
    foreach ($line in ($activityState -split "`n")) {
        if ($line -match 'topResumedActivity=.* u\d+ (?<component>[^}\s]+)') {
            if (-not $components.Contains($Matches.component)) {
                $components.Add($Matches.component)
            }
        }
    }
    $wakefulness = if ($powerState -match 'mWakefulness=(?<state>\w+)') {
        $Matches.state
    } else {
        'unknown'
    }
    $interactive = if ($wakefulness -eq 'Awake') {
        $true
    } elseif ($wakefulness -in @('Asleep', 'Dozing', 'Dreaming')) {
        $false
    } else {
        $null
    }
    $keyguardMatches = [regex]::Matches(
        $windowState,
        '(?:mDreamingLockscreen|mShowingLockscreen|isStatusBarKeyguard|mInputRestricted)=(true|false)'
    )
    $keyguardLocked = $null
    if ($keyguardMatches.Count -gt 0) {
        $keyguardLocked = [bool](@($keyguardMatches | Where-Object { $_.Groups[1].Value -eq 'true' }).Count)
    }
    return [ordered]@{
        interactive = $interactive
        wakefulness = $wakefulness
        keyguardLocked = $keyguardLocked
        topResumedComponents = @($components)
        splitScreenMarkerCount = [regex]::Matches($activityState, 'mInSplitScreen=true').Count
    }
}

function Wait-DeviceState {
    param(
        [bool]$Interactive,
        [object]$KeyguardLocked = $null,
        [int]$Seconds,
        [ValidateRange(0, 10000)]
        [int]$StableMilliseconds = 0
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $stableSince = $null
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        $snapshot = Get-DeviceSnapshot
        $interactiveMatches = $snapshot.interactive -is [bool] -and $snapshot.interactive -eq $Interactive
        $keyguardMatches = $null -eq $KeyguardLocked -or (
            $snapshot.keyguardLocked -is [bool] -and
            $snapshot.keyguardLocked -eq [bool]$KeyguardLocked
        )
        if ($interactiveMatches -and $keyguardMatches) {
            if ($null -eq $stableSince) {
                $stableSince = [DateTimeOffset]::UtcNow
            }
            $stableFor = ([DateTimeOffset]::UtcNow - $stableSince).TotalMilliseconds
            if ($stableFor -ge $StableMilliseconds) { return $snapshot }
        } else {
            $stableSince = $null
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for interactive=$Interactive keyguard=$KeyguardLocked"
}

function Wait-SourceAbsentFromTop {
    param([int]$Seconds)
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        $snapshot = Get-DeviceSnapshot
        if ($sourceComponent -notin @($snapshot.topResumedComponents)) { return $snapshot }
        Start-Sleep -Milliseconds 300
    }
    throw 'Source activity remained top-resumed after opening recents.'
}

function Wait-TestActivitiesResumed {
    param([int]$Seconds)
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        $snapshot = Get-DeviceSnapshot
        $components = @($snapshot.topResumedComponents)
        if (
            $sourceComponent -in $components -and
            $targetComponent -in $components -and
            $snapshot.splitScreenMarkerCount -gt 0
        ) {
            return $snapshot
        }
        Start-Sleep -Milliseconds 300
    }
    throw 'Both test activities did not become top-resumed in split-screen.'
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
            $script:companionEventLines.Add($candidate)
        }
    }
}

function Test-CompanionEvent {
    param(
        [string]$Kind,
        [string]$DataName = '',
        [string]$DataValue = '',
        [string[]]$RequiredComponents = @()
    )
    foreach ($line in $script:companionEventLines) {
        $event = $line | ConvertFrom-Json
        if ($event.kind -ne $Kind) { continue }
        if ($DataName -and [string]$event.data.$DataName -ne $DataValue) { continue }
        $components = @($event.data.resumedComponents)
        if (@($RequiredComponents | Where-Object { $_ -notin $components }).Count -gt 0) { continue }
        return $true
    }
    return $false
}

function Wait-CompanionEvent {
    param(
        [string]$Kind,
        [string]$DataName = '',
        [string]$DataValue = '',
        [string[]]$RequiredComponents = @(),
        [int]$Seconds = 20
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        Collect-CompanionEvents
        if (Test-CompanionEvent $Kind $DataName $DataValue $RequiredComponents) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for companion event: kind=$Kind $DataName=$DataValue"
}

function Write-S07Event {
    param(
        [string]$Kind,
        [System.Collections.IDictionary]$Data
    )
    $payload = [ordered]@{
        schema = 's0.7-1'
        scenario = $script:currentScenario
        cycle = $script:currentCycle
        sessionId = $script:currentSessionId
        kind = $Kind
        wallClockMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        data = $Data
    }
    $script:writer.WriteLine(($payload | ConvertTo-Json -Depth 12 -Compress))
    $script:writer.Flush()
}

function Write-CompanionEvents {
    Collect-CompanionEvents
    foreach ($line in $script:companionEventLines) {
        Write-S07Event 'companion_event' @{
            event = ($line | ConvertFrom-Json)
        }
    }
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

function Start-Probe {
    $script:seenCompanionEvents = [System.Collections.Generic.HashSet[string]]::new()
    $script:companionEventLines = [System.Collections.Generic.List[string]]::new()
    Stop-ProbeAndTestApps
    Start-ShizukuServer
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $pocAutomationComponent,
        '--es', 'jt_s02_session', $script:currentSessionId,
        '--ei', 'jt_s02_max_actions', '1',
        '--ei', 'jt_s02_requested_allowed', '0',
        '--ez', 'jt_s02_armed', 'true'
    )
    Wait-CompanionEvent -Kind 'ready' -Seconds 20
    $null = Invoke-AdbText @('shell', 'am', 'start', '-n', $sourceComponent)
    Wait-CompanionEvent -Kind 'foreground_changed' -DataName 'state' -DataValue 'source' -Seconds 20
    Write-S07Event 'source_observed' (Get-DeviceSnapshot)
}

function Invoke-DeviceScenario {
    param(
        [ValidateSet('recents', 'split-screen', 'screen-lock')]
        [string]$Scenario,
        [int]$Cycle
    )
    $script:currentScenario = $Scenario
    $script:currentCycle = $Cycle
    $script:currentSessionId = [Guid]::NewGuid().ToString('N')
    Write-Output "S0.7 $Scenario cycle $Cycle started (session=$($script:currentSessionId))"
    try {
        Write-S07Event 'scenario_started' @{
            model = ((Invoke-AdbText @('shell', 'getprop', 'ro.product.model')) -join '').Trim()
            androidRelease = ((Invoke-AdbText @('shell', 'getprop', 'ro.build.version.release')) -join '').Trim()
        }
        Start-Probe
        switch ($Scenario) {
            'recents' {
                $null = Invoke-AdbText @('shell', 'input', 'keyevent', '187')
                $boundary = Wait-SourceAbsentFromTop -Seconds 15
                Write-S07Event 'boundary_injected' $boundary
                Wait-CompanionEvent -Kind 'source_context_invalidated' -DataName 'reason' -DataValue 'foreground_changed' -Seconds 20
                $null = Invoke-AdbText @('shell', 'am', 'start', '-n', $targetComponent)
                Wait-CompanionEvent -Kind 'foreground_changed' -DataName 'state' -DataValue 'target' -Seconds 20
                $targetSnapshot = Get-DeviceSnapshot
                Write-S07Event 'target_launched' ([ordered]@{
                    exitCode = 0
                    interactive = $targetSnapshot.interactive
                    keyguardLocked = $targetSnapshot.keyguardLocked
                    topResumedComponents = @($targetSnapshot.topResumedComponents)
                    splitScreenMarkerCount = $targetSnapshot.splitScreenMarkerCount
                })
            }
            'split-screen' {
                $null = Invoke-AdbText @(
                    'shell', 'am', 'start', '--windowingMode', '3', '-n', $sourceComponent
                )
                Start-Sleep -Milliseconds 700
                Write-S07Event 'boundary_injected' (Get-DeviceSnapshot)
                $null = Invoke-AdbText @(
                    'shell', 'am', 'start', '--windowingMode', '4', '-n', $targetComponent
                )
                $targetSnapshot = Wait-TestActivitiesResumed -Seconds 20
                Write-S07Event 'target_launched' ([ordered]@{
                    exitCode = 0
                    interactive = $targetSnapshot.interactive
                    keyguardLocked = $targetSnapshot.keyguardLocked
                    topResumedComponents = @($targetSnapshot.topResumedComponents)
                    splitScreenMarkerCount = $targetSnapshot.splitScreenMarkerCount
                })
                Wait-CompanionEvent -Kind 'foreground_changed' -DataName 'state' -DataValue 'ambiguous' -RequiredComponents @($sourceComponent, $targetComponent) -Seconds 20
                Wait-CompanionEvent -Kind 'source_context_invalidated' -DataName 'reason' -DataValue 'foreground_ambiguous' -Seconds 20
            }
            'screen-lock' {
                $null = Invoke-AdbText @('shell', 'input', 'keyevent', '223')
                $boundary = Wait-DeviceState -Interactive $false -KeyguardLocked $null -Seconds 20
                Write-S07Event 'boundary_injected' $boundary
                Wait-CompanionEvent -Kind 'source_context_invalidated' -DataName 'reason' -DataValue 'device_not_interactive' -Seconds 20
                $null = Invoke-AdbText @('shell', 'am', 'start', '-n', $targetComponent)
                $targetSnapshot = Get-DeviceSnapshot
                Write-S07Event 'target_launched' ([ordered]@{
                    exitCode = 0
                    interactive = $targetSnapshot.interactive
                    keyguardLocked = $targetSnapshot.keyguardLocked
                    topResumedComponents = @($targetSnapshot.topResumedComponents)
                    splitScreenMarkerCount = $targetSnapshot.splitScreenMarkerCount
                })
                Start-Sleep -Seconds 2
                $null = Invoke-AdbText @('shell', 'input', 'keyevent', '224')
                $null = Wait-DeviceState -Interactive $true -KeyguardLocked $null -Seconds 20
                $wakeSnapshot = Get-DeviceSnapshot
                if ($wakeSnapshot.keyguardLocked -ne $false) {
                    Write-Output 'PHONE_UNLOCK_REQUIRED: unlock the phone manually; the runner will wait.'
                }
                $recovery = Wait-DeviceState -Interactive $true -KeyguardLocked $false -Seconds $UnlockWaitSeconds -StableMilliseconds 3000
                Write-S07Event 'recovery_observed' $recovery
                Wait-CompanionEvent -Kind 'foreground_changed' -DataName 'state' -DataValue 'target' -Seconds 20
            }
        }
        Start-Sleep -Seconds 3
        Collect-CompanionEvents
        if (Test-CompanionEvent -Kind 'target_detected') {
            throw "$Scenario cycle $Cycle detected the target in a zero-action context."
        }
        if (Test-CompanionEvent -Kind 'back_requested') {
            throw "$Scenario cycle $Cycle requested Back in a zero-action context."
        }
        if (Test-CompanionEvent -Kind 'service_error') {
            throw "$Scenario cycle $Cycle emitted a service error."
        }
        Write-CompanionEvents
        Write-S07Event 'scenario_complete' @{ result = 'zero_action_observed' }
    } catch {
        try { Write-CompanionEvents } catch { }
        Write-S07Event 'runner_error' @{
            type = $_.Exception.GetType().FullName
            message = $_.Exception.Message
        }
        throw
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
if ($pocPackageState -notmatch '(?m)^\s*versionName=0\.0\.7-s07\s*$') {
    throw 'S0.7 requires the 0.0.7-s07 POC APK.'
}
Assert-RegularObserverDisarmed
Start-ShizukuServer
if (-not (Test-ShizukuPermissionGranted)) {
    throw 'The POC Shizuku permission must be granted before S0.7.'
}
$initialSnapshot = Get-DeviceSnapshot
if ($initialSnapshot.interactive -ne $true -or $initialSnapshot.keyguardLocked -ne $false) {
    throw 'Device must be awake and unlocked before S0.7.'
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $workspaceRoot "docs\s07\results\s07-device-state-$timestamp"
}
$outputDirectoryPath = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($outputDirectoryPath) | Out-Null
$timelinePath = Join-Path $outputDirectoryPath 's07-device-state.jsonl'
$positiveTimelinePath = Join-Path $outputDirectoryPath 's07-fullscreen-positive.jsonl'
$positiveReportPath = Join-Path $outputDirectoryPath 's07-fullscreen-positive.report.json'
if (-not $ReportOutput) {
    $ReportOutput = Join-Path $outputDirectoryPath 's07-device-state.report.json'
}
$reportPath = [System.IO.Path]::GetFullPath($ReportOutput)
$script:writer = [System.IO.StreamWriter]::new(
    $timelinePath,
    $false,
    [System.Text.UTF8Encoding]::new($false)
)
$runFailed = $false

try {
    foreach ($cycle in 1..$RecentsCycles) {
        Invoke-DeviceScenario -Scenario 'recents' -Cycle $cycle
    }
    foreach ($cycle in 1..$SplitScreenCycles) {
        Invoke-DeviceScenario -Scenario 'split-screen' -Cycle $cycle
    }
    foreach ($cycle in 1..$ScreenLockCycles) {
        Invoke-DeviceScenario -Scenario 'screen-lock' -Cycle $cycle
    }
    $script:writer.Dispose()
    $script:writer = $null

    Invoke-ChildPowerShell -Path (Join-Path $PSScriptRoot 's02-shizuku-run.ps1') -Arguments @(
        '-Scenario', 'block',
        '-BatchCount', '10',
        '-Arm',
        '-TimeoutSeconds', "$TimeoutSeconds",
        '-Serial', $script:Serial,
        '-Output', $positiveTimelinePath,
        '-ReportOutput', $positiveReportPath
    )

    & python (Join-Path $PSScriptRoot 's07_device_state_report.py') @(
        '--timeline', $timelinePath,
        '--positive-timeline', $positiveTimelinePath,
        '--positive-report', $positiveReportPath,
        '--expected-recents', "$RecentsCycles",
        '--expected-split-screen', "$SplitScreenCycles",
        '--expected-screen-lock', "$ScreenLockCycles",
        '--output', $reportPath,
        '--strict'
    )
    if ($LASTEXITCODE -ne 0) {
        throw "S0.7 report gate failed with exit code $LASTEXITCODE"
    }
} catch {
    $runFailed = $true
    throw
} finally {
    if ($script:writer -ne $null) {
        $script:writer.Dispose()
        $script:writer = $null
    }
    try { $null = Invoke-AdbText @('shell', 'input', 'keyevent', '224') } catch { }
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

if ($runFailed) { exit 1 }
