param(
    [ValidateRange(1, 20)]
    [int]$CrashCycles = 5,
    [ValidateSet(1, 10, 100)]
    [int]$RepeatedTargets = 10,
    [ValidateRange(1, 10)]
    [int]$ReauthorizationCycles = 3,
    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 120,
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
$targetPackage = 'com.jumpterminator.testtarget'
$shizukuPackage = 'moe.shizuku.privileged.api'
$shizukuPermission = 'moe.shizuku.manager.permission.API_V23'
$companionLogTag = 'JT_S02_SHIZUKU'
$reauthorizationWriter = $null

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

function Get-ShizukuServerPid {
    $serverPids = @(
        foreach ($line in Invoke-AdbText @('shell', 'ps', '-A')) {
            if ($line -match '^shell\s+(?<pid>\d+)\s+\d+.*\bshizuku_server\s*$') {
                [int]$Matches.pid
            }
        }
    )
    if ($serverPids.Count -gt 1) { throw 'Multiple exact Shizuku server processes found.' }
    if ($serverPids.Count -eq 0) { return 0 }
    return $serverPids[0]
}

function Test-ShizukuServerRunning {
    return (Get-ShizukuServerPid) -ne 0
}

function Stop-ShizukuServer {
    $processId = Get-ShizukuServerPid
    if ($processId -eq 0) { return }
    $null = Invoke-AdbText @('shell', 'kill', "$processId")
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 3) {
        Start-Sleep -Milliseconds 200
        if ((Get-ShizukuServerPid) -eq 0) { return }
    }
    $null = Invoke-AdbText @('shell', 'kill', '-9', "$processId")
    Start-Sleep -Milliseconds 500
    if ((Get-ShizukuServerPid) -ne 0) {
        throw 'Unable to stop the exact Shizuku server process.'
    }
}

function Start-ShizukuServer {
    if (Test-ShizukuServerRunning) { return }
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
        if (Test-ShizukuServerRunning) { return }
    }
    throw 'Shizuku server did not start.'
}

function Test-ShizukuPermissionGranted {
    $packageState = (Invoke-AdbText @('shell', 'dumpsys', 'package', $pocPackage)) -join "`n"
    return $packageState -match ([regex]::Escape($shizukuPermission) + ': granted=true')
}

function Get-SessionReadyEvents {
    param([string]$SessionId)
    $events = @()
    $lines = @(& $adb -s $script:Serial logcat -d -v raw -s "${companionLogTag}:I" '*:S')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read Shizuku companion logcat.' }
    foreach ($line in $lines) {
        $candidate = $line.Trim()
        if (-not $candidate.StartsWith('{') -or -not $candidate.Contains($SessionId)) {
            continue
        }
        try { $event = $candidate | ConvertFrom-Json } catch { continue }
        if (
            $event.schema -eq 's0.2-1' -and
            $event.sessionId -eq $SessionId -and
            $event.kind -eq 'ready'
        ) {
            $events += $event
        }
    }
    return @($events)
}

function Wait-ForReady {
    param(
        [string]$SessionId,
        [int]$Seconds
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        $events = @(Get-SessionReadyEvents -SessionId $SessionId)
        if ($events.Count -gt 0) { return $events.Count }
        Start-Sleep -Milliseconds 250
    }
    return 0
}

function Write-ReauthorizationEvent {
    param(
        [int]$Cycle,
        [string]$Kind,
        [hashtable]$Data
    )
    $event = [ordered]@{
        schema = 's0.6-reauth-1'
        cycle = $Cycle
        kind = $Kind
        wallClockMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    }
    foreach ($key in $Data.Keys) { $event[$key] = $Data[$key] }
    $script:reauthorizationWriter.WriteLine(
        ($event | ConvertTo-Json -Depth 8 -Compress)
    )
    $script:reauthorizationWriter.Flush()
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

foreach ($packageName in @(
    $mainPackage,
    $pocPackage,
    $sourcePackage,
    $targetPackage,
    $shizukuPackage
)) {
    $packagePath = Invoke-AdbText @('shell', 'pm', 'path', $packageName)
    if (-not $packagePath) { throw "Required package is not installed: $packageName" }
}

$windowState = (Invoke-AdbText @('shell', 'dumpsys', 'window')) -join "`n"
if ($windowState -match 'mDreamingLockscreen=true|mShowingLockscreen=true|isStatusBarKeyguard=true|mInputRestricted=true') {
    throw 'Device is locked. Unlock it before running S0.6 resilience stress.'
}

$settingsXml = (Invoke-AdbText @(
    'shell', 'run-as', $mainPackage, 'cat', 'shared_prefs/s0_settings.xml'
)) -join "`n"
if ($settingsXml -match '<boolean name="armed" value="true"') {
    throw 'The regular S0 observer is armed. Disarm it before S0.6.'
}

if (-not (Test-ShizukuPermissionGranted)) {
    throw 'The POC Shizuku permission must be granted before S0.6.'
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $workspaceRoot "docs\s06\results\s06-resilience-$timestamp"
}
$outputDirectoryPath = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($outputDirectoryPath) | Out-Null
if (-not $ReportOutput) {
    $ReportOutput = Join-Path $outputDirectoryPath 's06-resilience.report.json'
}
$reportPath = [System.IO.Path]::GetFullPath($ReportOutput)
$lifecyclePaths = [System.Collections.Generic.List[string]]::new()
$s03Runner = Join-Path $PSScriptRoot 's03-lifecycle.ps1'
$s02Runner = Join-Path $PSScriptRoot 's02-shizuku-run.ps1'
$blockTimeline = Join-Path $outputDirectoryPath 's06-repeated-targets.jsonl'
$blockReport = Join-Path $outputDirectoryPath 's06-repeated-targets.report.json'
$reauthorizationTimeline = Join-Path $outputDirectoryPath 's06-reauthorization.jsonl'
$runFailed = $false

try {
    foreach ($cycle in 1..$CrashCycles) {
        $path = Join-Path $outputDirectoryPath ("s06-ui-kill-{0:D2}.jsonl" -f $cycle)
        Invoke-ChildPowerShell -Path $s03Runner -Arguments @(
            '-Scenario', 'ui-kill',
            '-TimeoutSeconds', "$TimeoutSeconds",
            '-Serial', $script:Serial,
            '-Output', $path
        )
        $lifecyclePaths.Add($path)
    }

    Start-ShizukuServer
    Invoke-ChildPowerShell -Path $s02Runner -Arguments @(
        '-Scenario', 'block',
        '-BatchCount', "$RepeatedTargets",
        '-Arm',
        '-TimeoutSeconds', "$TimeoutSeconds",
        '-Serial', $script:Serial,
        '-Output', $blockTimeline,
        '-ReportOutput', $blockReport
    )

    $reauthorizationWriter = [System.IO.StreamWriter]::new(
        $reauthorizationTimeline,
        $false,
        [System.Text.UTF8Encoding]::new($false)
    )
    foreach ($cycle in 1..$ReauthorizationCycles) {
        Start-ShizukuServer
        $null = Invoke-AdbText @('shell', 'am', 'force-stop', $pocPackage)
        Start-Sleep -Seconds 1
        $null = Invoke-AdbText @('shell', 'pm', 'revoke', $pocPackage, $shizukuPermission)
        $grantedAfterRevoke = Test-ShizukuPermissionGranted
        Write-ReauthorizationEvent -Cycle $cycle -Kind 'permission_revoked' -Data @{
            granted = $grantedAfterRevoke
        }
        if ($grantedAfterRevoke) { throw "Cycle ${cycle}: Shizuku permission was not revoked" }

        $revokedSession = [Guid]::NewGuid().ToString('N')
        $null = Invoke-AdbText @(
            'shell', 'am', 'start', '-n', $pocAutomationComponent,
            '--es', 'jt_s02_session', $revokedSession,
            '--ei', 'jt_s02_max_actions', '1',
            '--ei', 'jt_s02_requested_allowed', '0',
            '--ez', 'jt_s02_armed', 'false'
        )
        Start-Sleep -Seconds 3
        $revokedReadyCount = @(Get-SessionReadyEvents -SessionId $revokedSession).Count
        Write-ReauthorizationEvent -Cycle $cycle -Kind 'revoked_probe' -Data @{
            sessionId = $revokedSession
            readyCount = $revokedReadyCount
        }
        if ($revokedReadyCount -ne 0) {
            throw "Cycle ${cycle}: privileged session became ready while permission was revoked"
        }

        $null = Invoke-AdbText @('shell', 'am', 'force-stop', $pocPackage)
        $null = Invoke-AdbText @('shell', 'pm', 'grant', $pocPackage, $shizukuPermission)
        $grantedAfterRestore = Test-ShizukuPermissionGranted
        Write-ReauthorizationEvent -Cycle $cycle -Kind 'permission_restored' -Data @{
            granted = $grantedAfterRestore
        }
        if (-not $grantedAfterRestore) {
            throw "Cycle ${cycle}: Shizuku permission was not restored"
        }

        $recoveredSession = [Guid]::NewGuid().ToString('N')
        $null = Invoke-AdbText @(
            'shell', 'am', 'start', '-n', $pocAutomationComponent,
            '--es', 'jt_s02_session', $recoveredSession,
            '--ei', 'jt_s02_max_actions', '1',
            '--ei', 'jt_s02_requested_allowed', '0',
            '--ez', 'jt_s02_armed', 'false'
        )
        $recoveredReadyCount = Wait-ForReady -SessionId $recoveredSession -Seconds 20
        Write-ReauthorizationEvent -Cycle $cycle -Kind 'recovered_probe' -Data @{
            sessionId = $recoveredSession
            readyCount = $recoveredReadyCount
        }
        if ($recoveredReadyCount -ne 1) {
            throw "Cycle ${cycle}: expected exactly one ready event after permission restore"
        }

        $null = Invoke-AdbText @(
            'shell', 'am', 'start', '-n', $pocAutomationComponent,
            '--es', 'jt_s02_control', 'stop'
        )
        Start-Sleep -Milliseconds 500
        $null = Invoke-AdbText @('shell', 'am', 'force-stop', $pocPackage)
        Start-Sleep -Seconds 1
    }
    $reauthorizationWriter.Dispose()
    $reauthorizationWriter = $null

    $reportArguments = [System.Collections.Generic.List[string]]::new()
    foreach ($path in $lifecyclePaths) {
        $reportArguments.Add('--lifecycle')
        $reportArguments.Add($path)
    }
    foreach ($value in @(
        '--block-timeline', $blockTimeline,
        '--block-report', $blockReport,
        '--reauthorization', $reauthorizationTimeline,
        '--expected-crash-cycles', "$CrashCycles",
        '--expected-targets', "$RepeatedTargets",
        '--expected-reauthorization-cycles', "$ReauthorizationCycles",
        '--output', $reportPath,
        '--strict'
    )) {
        $reportArguments.Add($value)
    }
    & python (Join-Path $PSScriptRoot 's06_resilience_report.py') @reportArguments
    if ($LASTEXITCODE -ne 0) {
        throw "S0.6 report gate failed with exit code $LASTEXITCODE"
    }
} catch {
    $runFailed = $true
    throw
} finally {
    if ($reauthorizationWriter -ne $null) {
        $reauthorizationWriter.Dispose()
        $reauthorizationWriter = $null
    }
    try { $null = Invoke-AdbText @('shell', 'pm', 'grant', $pocPackage, $shizukuPermission) } catch { }
    try { Stop-ShizukuServer } catch { }
    try { Start-ShizukuServer } catch { }
    foreach ($packageName in @($sourcePackage, $targetPackage, $pocPackage)) {
        try { $null = Invoke-AdbText @('shell', 'am', 'force-stop', $packageName) } catch { }
    }
    try {
        $null = Invoke-AdbText @('shell', 'am', 'start', '-n', $pocComponent)
        Start-Sleep -Milliseconds 300
        $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3')
    } catch { }
    Write-Output "Output directory: $outputDirectoryPath"
    Write-Output "Report: $reportPath"
}

if ($runFailed) { exit 1 }
