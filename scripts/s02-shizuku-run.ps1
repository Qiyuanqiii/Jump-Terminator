param(
    [ValidateSet('block', 'allowed-negative')]
    [string]$Scenario = 'block',
    [ValidateSet(1, 10, 100)]
    [int]$BatchCount = 10,
    [ValidateRange(1, 20)]
    [int]$AllowedRepeats = 5,
    [switch]$Arm,
    [ValidateRange(0, 1800)]
    [int]$TimeoutSeconds = 0,
    [string]$Serial = '',
    [string]$Output = '',
    [string]$ReportOutput = ''
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$androidSdk = Join-Path $env:USERPROFILE '.cache\jump-terminator\toolchain\android-sdk'
$adb = Join-Path $androidSdk 'platform-tools\adb.exe'
$mainPackage = 'com.jumpterminator.app'
$pocPackage = 'com.jumpterminator.s02'
$pocAutomationComponent = 'com.jumpterminator.s02/.AutomationActivity'
$sourcePackage = 'com.jumpterminator.testsource'
$sourceComponent = 'com.jumpterminator.testsource/.SourceActivity'
$targetPackage = 'com.jumpterminator.testtarget'
$targetComponent = 'com.jumpterminator.testtarget/.TargetActivity'
$shizukuPackage = 'moe.shizuku.privileged.api'
$logTag = 'JT_S02_SHIZUKU'

if (-not (Test-Path -LiteralPath $adb)) { throw "adb not found: $adb" }
if ($Scenario -eq 'allowed-negative' -and -not $Arm) {
    throw 'The allowed-negative scenario must be armed.'
}

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

function Invoke-PocAutomation {
    param([string[]]$Arguments)
    return Invoke-AdbText (
        @('shell', 'am', 'start', '-n', $pocAutomationComponent) +
        $Arguments
    )
}

function Get-TopComponent {
    $lines = Invoke-AdbText @('shell', 'dumpsys', 'activity', 'activities')
    $topLine = $lines | Where-Object { $_ -match 'topResumedActivity=' } | Select-Object -First 1
    if ($topLine -match ' u\d+ (?<component>[^}\s]+)') { return $Matches.component }
    return 'unknown'
}

function Get-PackageUid {
    param([string]$PackageName)
    $lines = Invoke-AdbText @('shell', 'dumpsys', 'package', $PackageName)
    $uidLine = $lines | Where-Object { $_ -match '^\s*userId=(?<uid>\d+)\s*$' } |
        Select-Object -First 1
    if (-not $uidLine) { throw "Unable to resolve package UID: $PackageName" }
    if ($uidLine -notmatch '^\s*userId=(?<uid>\d+)\s*$') {
        throw "Unable to parse package UID: $PackageName"
    }
    return [int]$Matches.uid
}

function Collect-SessionEvents {
    $lines = @(& $adb -s $script:Serial logcat -d -v raw -s "${logTag}:I" '*:S')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read the Shizuku companion log.' }
    foreach ($line in $lines) {
        $candidate = $line.Trim()
        if (-not $candidate.StartsWith('{') -or -not $candidate.Contains($script:sessionId)) {
            continue
        }
        try {
            $event = $candidate | ConvertFrom-Json
        } catch {
            continue
        }
        if ($event.schema -ne 's0.2-1' -or $event.sessionId -ne $script:sessionId) {
            continue
        }
        if ($script:seenEvents.Add($candidate)) {
            $script:eventLines.Add($candidate)
        }
    }
}

function Add-LocalEvent {
    param(
        [string]$Kind,
        [hashtable]$Data
    )
    $line = [ordered]@{
        schema = 's0.2-1'
        sessionId = $script:sessionId
        kind = $Kind
        wallClockMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        data = $Data
    } | ConvertTo-Json -Depth 8 -Compress
    if ($script:seenEvents.Add($line)) {
        $script:eventLines.Add($line)
    }
}

function Test-HasEventKind {
    param([string[]]$Kinds)
    foreach ($line in $script:eventLines) {
        $event = $line | ConvertFrom-Json
        if ($event.kind -in $Kinds) { return $true }
    }
    return $false
}

function Wait-ForEventKind {
    param(
        [string[]]$Kinds,
        [int]$Seconds
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        Collect-SessionEvents
        if (Test-HasEventKind -Kinds $Kinds) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for event kind: $($Kinds -join ', ')"
}

function Start-AllowedProbes {
    $probeTypes = @('settings', 'browser', 'home')
    $probeNumber = 0
    foreach ($repeat in 1..$AllowedRepeats) {
        foreach ($probeType in $probeTypes) {
            $probeNumber += 1
            $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3')
            $null = Invoke-AdbText @('shell', 'am', 'force-stop', $sourcePackage)
            $null = Invoke-AdbText @(
                'shell', 'am', 'start', '-n', $sourceComponent,
                '--es', 'jt_s02_allowed_probe', $probeType
            )
            Start-Sleep -Milliseconds 1500
            Collect-SessionEvents
            $observedComponent = Get-TopComponent
            $passed = switch ($probeType) {
                'settings' { $observedComponent.StartsWith('com.android.settings/'); break }
                'home' { $observedComponent.StartsWith('com.miui.home/'); break }
                default {
                    $observedComponent.StartsWith('com.android.chrome/') -or
                        $observedComponent.StartsWith('com.miui.securitycenter/') -or
                        $observedComponent.StartsWith('android/')
                }
            }
            Add-LocalEvent -Kind 'allowed_probe' -Data @{
                sequence = $probeNumber
                repeat = $repeat
                probeType = $probeType
                observedComponent = $observedComponent
                passed = [bool]$passed
            }
            $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3')
            Start-Sleep -Milliseconds 250
        }
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
    throw 'Device is locked. Unlock it before running an interactive S0.2/S0.4 scenario.'
}

$settingsXml = (Invoke-AdbText @(
    'shell', 'run-as', $mainPackage, 'cat', 'shared_prefs/s0_settings.xml'
)) -join "`n"
if ($settingsXml -match '<boolean name="armed" value="true"') {
    throw 'The regular S0 observer is armed. Disarm it before running S0.2.'
}

$processes = (Invoke-AdbText @('shell', 'ps', '-A')) -join "`n"
if ($processes -notmatch '(?m)^shell\s+\d+\s+\d+.*\bshizuku_server\s*$') {
    throw 'Shizuku is not running as the shell user.'
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $Output) {
    $modeName = if ($Arm) { 'armed' } else { 'observe' }
    $Output = Join-Path $workspaceRoot (
        "docs\s02\results\s02-shizuku-$Scenario-$modeName-$timestamp.jsonl"
    )
}
$outputPath = [System.IO.Path]::GetFullPath($Output)
if (-not $ReportOutput) {
    $ReportOutput = [System.IO.Path]::ChangeExtension($outputPath, '.report.json')
}
$reportPath = [System.IO.Path]::GetFullPath($ReportOutput)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($outputPath)) | Out-Null
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($reportPath)) | Out-Null

$sessionId = [Guid]::NewGuid().ToString('N')
$seenEvents = [System.Collections.Generic.HashSet[string]]::new()
$eventLines = [System.Collections.Generic.List[string]]::new()
$requestedBlock = if ($Scenario -eq 'block') { $BatchCount } else { 0 }
$requestedAllowed = if ($Scenario -eq 'allowed-negative') { $AllowedRepeats * 3 } else { 0 }
if ($TimeoutSeconds -eq 0) {
    $TimeoutSeconds = if ($Scenario -eq 'block') {
        [Math]::Max(90, ($BatchCount * 8) + 60)
    } else {
        [Math]::Max(90, ($requestedAllowed * 4) + 30)
    }
}
$armedValue = if ($Arm) { 'true' } else { 'false' }
$runFailed = $false

try {
    $null = Invoke-PocAutomation @(
        '--es', 'jt_s02_session', $sessionId,
        '--ei', 'jt_s02_max_actions', "$requestedBlock",
        '--ei', 'jt_s02_requested_allowed', "$requestedAllowed",
        '--ez', 'jt_s02_armed', $armedValue
    )
    Wait-ForEventKind -Kinds @('ready') -Seconds 20

    Add-LocalEvent -Kind 'owner_identity_expected' -Data @{
        packageName = $pocPackage
        packageUid = Get-PackageUid -PackageName $pocPackage
        uidSource = 'dumpsys_package'
    }

    Add-LocalEvent -Kind 'batch_requested' -Data @{
        scenario = $Scenario
        requestedBlock = $requestedBlock
        requestedAllowed = $requestedAllowed
        armed = [bool]$Arm
    }

    if ($Scenario -eq 'block') {
        $null = Invoke-AdbText @('shell', 'am', 'force-stop', $targetPackage)
        $null = Invoke-AdbText @('shell', 'am', 'force-stop', $sourcePackage)
        $null = Invoke-AdbText @(
            'shell', 'am', 'start', '-n', $sourceComponent,
            '--ei', 'jt_s02_batch_count', "$BatchCount"
        )
    } else {
        Start-AllowedProbes
        $null = Invoke-PocAutomation @(
            '--es', 'jt_s02_control', 'stop'
        )
    }

    Wait-ForEventKind -Kinds @('complete', 'timeout', 'service_error') -Seconds $TimeoutSeconds
    Collect-SessionEvents
} catch {
    $runFailed = $true
    Add-LocalEvent -Kind 'runner_error' -Data @{
        type = $_.Exception.GetType().FullName
        message = $_.Exception.Message
    }
    throw
} finally {
    if ($runFailed) {
        try {
            $null = Invoke-PocAutomation @(
                '--es', 'jt_s02_control', 'stop'
            )
            Start-Sleep -Milliseconds 500
        } catch { }
    }
    try { Collect-SessionEvents } catch { }
    [System.IO.File]::WriteAllLines(
        $outputPath,
        $eventLines,
        [System.Text.UTF8Encoding]::new($false)
    )
    try { $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3') } catch { }
    Write-Output "Timeline: $outputPath"
    Write-Output "Session: $sessionId"
}

if (-not $runFailed) {
    & python (Join-Path $workspaceRoot 'scripts\s02_report.py') $outputPath --output $reportPath
    if ($LASTEXITCODE -ne 0) { throw "Report generation failed with exit code $LASTEXITCODE" }
    Write-Output "Report: $reportPath"
}
