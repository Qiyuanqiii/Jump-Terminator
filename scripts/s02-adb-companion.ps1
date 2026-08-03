param(
    [ValidateSet('block', 'allowed-negative')]
    [string]$Scenario = 'block',
    [ValidateSet(1, 10, 100)]
    [int]$BatchCount = 10,
    [ValidateRange(1, 20)]
    [int]$AllowedRepeats = 5,
    [switch]$Arm,
    [ValidateRange(0, 3600)]
    [int]$TimeoutSeconds = 0,
    [string]$Serial = '',
    [string]$Output = '',
    [string]$ReportOutput = ''
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$androidSdk = Join-Path $env:USERPROFILE '.cache\jump-terminator\toolchain\android-sdk'
$adb = Join-Path $androidSdk 'platform-tools\adb.exe'
$sourcePackage = 'com.jumpterminator.testsource'
$sourceComponent = 'com.jumpterminator.testsource/.SourceActivity'
$targetPackage = 'com.jumpterminator.testtarget'
$targetComponent = 'com.jumpterminator.testtarget/.TargetActivity'
$mainPackage = 'com.jumpterminator.app'

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

function Get-TopComponent {
    $lines = Invoke-AdbText @('shell', 'dumpsys', 'activity', 'activities')
    $topLine = $lines | Where-Object { $_ -match 'topResumedActivity=' } | Select-Object -First 1
    if ($topLine -match ' u\d+ (?<component>[^}\s]+)') { return $Matches.component }
    return 'unknown'
}

function Write-LocalEvent {
    param(
        [System.IO.StreamWriter]$Writer,
        [string]$Kind,
        [hashtable]$Data
    )
    $payload = [ordered]@{
        schema = 's0.2-1'
        sessionId = $script:sessionId
        kind = $Kind
        wallClockMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        data = $Data
    }
    $Writer.WriteLine(($payload | ConvertTo-Json -Depth 8 -Compress))
    $Writer.Flush()
}

function Start-BlockBatch {
    param([System.IO.StreamWriter]$Writer)
    Write-LocalEvent -Writer $Writer -Kind 'batch_requested' -Data @{
        scenario = 'block'
        requested = $BatchCount
        armed = [bool]$Arm
    }
    $null = Invoke-AdbText @('shell', 'am', 'force-stop', $targetPackage)
    $null = Invoke-AdbText @('shell', 'am', 'force-stop', $sourcePackage)
    $null = Invoke-AdbText @(
        'shell', 'am', 'start', '-n', $sourceComponent,
        '--ei', 'jt_s02_batch_count', "$BatchCount"
    )
}

function Start-AllowedProbes {
    param(
        [System.IO.StreamWriter]$Writer,
        [string]$StopFile
    )
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
            Write-LocalEvent -Writer $Writer -Kind 'allowed_probe' -Data @{
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
    $null = Invoke-AdbText @('shell', 'touch', $StopFile)
}

Resolve-DeviceSerial

foreach ($packageName in @($mainPackage, $sourcePackage, $targetPackage)) {
    $packagePath = Invoke-AdbText @('shell', 'pm', 'path', $packageName)
    if (-not $packagePath) { throw "Required package is not installed: $packageName" }
}

$settingsXml = (Invoke-AdbText @(
    'shell', 'run-as', $mainPackage, 'cat', 'shared_prefs/s0_settings.xml'
)) -join "`n"
if ($settingsXml -match '<boolean name="armed" value="true"') {
    throw 'The regular S0 observer is armed. Disarm it before running the S0.2 companion.'
}
if ($Scenario -eq 'allowed-negative' -and -not $Arm) {
    throw 'The allowed-negative scenario must use -Arm to test the armed companion safety boundary.'
}

if ($TimeoutSeconds -eq 0) {
    $TimeoutSeconds = if ($Scenario -eq 'block') {
        [Math]::Max(90, ($BatchCount * 8) + 60)
    } else {
        [Math]::Max(90, ($AllowedRepeats * 3 * 3) + 30)
    }
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $Output) {
    $modeName = if ($Arm) { 'armed' } else { 'observe' }
    $Output = Join-Path $workspaceRoot (
        "docs\s02\results\s02-adb-$Scenario-$modeName-$timestamp.jsonl"
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
$stopFile = "/data/local/tmp/jt-s02-stop-$sessionId"
$armValue = if ($Arm) { '1' } else { '0' }
$modeValue = if ($Arm) { 'armed' } else { 'observe' }
$requestedBlock = if ($Scenario -eq 'block') { $BatchCount } else { 0 }
$requestedAllowed = if ($Scenario -eq 'allowed-negative') { $AllowedRepeats * 3 } else { 0 }
$null = Invoke-AdbText @('shell', 'rm', '-f', $stopFile)

$remoteScript = @'
SOURCE_COMPONENT='com.jumpterminator.testsource/.SourceActivity'
TARGET_COMPONENT='com.jumpterminator.testtarget/.TargetActivity'
SESSION='__SESSION__'
SCENARIO='__SCENARIO__'
MODE='__MODE__'
ARM=__ARM__
MAX=__MAX__
REQUESTED_BLOCK=__REQUESTED_BLOCK__
REQUESTED_ALLOWED=__REQUESTED_ALLOWED__
STOP_FILE='__STOP_FILE__'
TIMEOUT_MS=__TIMEOUT_MS__
start_wall=$(date +%s%3N)
deadline=$((start_wall + TIMEOUT_MS))
sequence=0
actions=0
last_state=''
source_context=0
target_handled=0
pending_leave=0
last_source_sample=$start_wall
entry_lower_bound=$start_wall

printf '{"schema":"s0.2-1","sessionId":"%s","kind":"ready","wallClockMs":%s,"data":{"scenario":"%s","mode":"%s","requestedBlock":%s,"requestedAllowed":%s,"sourceComponent":"%s","targetComponent":"%s"}}\n' \
    "$SESSION" "$start_wall" "$SCENARIO" "$MODE" "$REQUESTED_BLOCK" "$REQUESTED_ALLOWED" "$SOURCE_COMPONENT" "$TARGET_COMPONENT"

while true; do
    poll_start=$(date +%s%3N)
    top_line=$(dumpsys activity activities 2>/dev/null | grep -m1 'topResumedActivity=')
    poll_end=$(date +%s%3N)
    component=$(echo "$top_line" | sed -n 's/.* u[0-9][0-9]* \([^} ]*\).*/\1/p')
    if [ -z "$component" ]; then component='unknown'; fi

    if [ "$component" = "$SOURCE_COMPONENT" ]; then
        state='source'
    elif [ "$component" = "$TARGET_COMPONENT" ]; then
        state='target'
    elif [ "$component" = 'unknown' ]; then
        state='unknown'
    else
        state='other'
    fi

    if [ "$state" != "$last_state" ]; then
        printf '{"schema":"s0.2-1","sessionId":"%s","kind":"foreground_changed","wallClockMs":%s,"packageName":"%s","data":{"state":"%s","component":"%s"}}\n' \
            "$SESSION" "$poll_end" "$component" "$state" "$component"
    fi

    if [ "$pending_leave" -eq 1 ] && [ "$state" != 'target' ] && [ "$state" != 'unknown' ]; then
        leave_upper=$((poll_end - entry_lower_bound))
        if [ "$state" = 'source' ]; then returned_source=true; else returned_source=false; fi
        printf '{"schema":"s0.2-1","sessionId":"%s","kind":"left_target","wallClockMs":%s,"packageName":"%s","data":{"sequence":%s,"leftTarget":true,"returnedSource":%s,"observedComponent":"%s","leaveUpperBoundMs":%s}}\n' \
            "$SESSION" "$poll_end" "$TARGET_COMPONENT" "$sequence" "$returned_source" "$component" "$leave_upper"
        pending_leave=0
    fi

    if [ "$state" = 'source' ]; then
        source_context=1
        target_handled=0
        last_source_sample=$poll_end
    elif [ "$state" = 'target' ]; then
        if [ "$source_context" -eq 1 ] && [ "$target_handled" -eq 0 ]; then
            sequence=$((sequence + 1))
            target_handled=1
            source_context=0
            pending_leave=1
            entry_lower_bound=$last_source_sample
            detection_upper=$((poll_end - entry_lower_bound))
            poll_duration=$((poll_end - poll_start))
            printf '{"schema":"s0.2-1","sessionId":"%s","kind":"target_detected","wallClockMs":%s,"packageName":"%s","data":{"sequence":%s,"sourceComponent":"%s","targetComponent":"%s","entryLowerBoundWallMs":%s,"detectionUpperBoundMs":%s,"pollDurationMs":%s}}\n' \
                "$SESSION" "$poll_end" "$TARGET_COMPONENT" "$sequence" "$SOURCE_COMPONENT" "$TARGET_COMPONENT" "$entry_lower_bound" "$detection_upper" "$poll_duration"
            if [ "$ARM" -eq 1 ]; then
                action_start=$(date +%s%3N)
                input keyevent 4 >/dev/null 2>&1
                dispatch_status=$?
                action_end=$(date +%s%3N)
                if [ "$dispatch_status" -eq 0 ]; then dispatched=true; else dispatched=false; fi
                actions=$((actions + 1))
                action_upper=$((action_start - entry_lower_bound))
                input_duration=$((action_end - action_start))
                printf '{"schema":"s0.2-1","sessionId":"%s","kind":"back_requested","wallClockMs":%s,"packageName":"%s","data":{"sequence":%s,"dispatched":%s,"sourceComponent":"%s","targetComponent":"%s","requestUpperBoundMs":%s,"inputDurationMs":%s}}\n' \
                    "$SESSION" "$action_start" "$TARGET_COMPONENT" "$sequence" "$dispatched" "$SOURCE_COMPONENT" "$TARGET_COMPONENT" "$action_upper" "$input_duration"
            fi
        fi
    elif [ "$state" = 'other' ]; then
        source_context=0
    fi

    last_state=$state

    if [ "$SCENARIO" = 'block' ] && [ "$sequence" -ge "$MAX" ] && [ "$pending_leave" -eq 0 ] && [ "$state" = 'source' ]; then
        now=$(date +%s%3N)
        printf '{"schema":"s0.2-1","sessionId":"%s","kind":"complete","wallClockMs":%s,"data":{"reason":"count_reached","detections":%s,"actions":%s}}\n' \
            "$SESSION" "$now" "$sequence" "$actions"
        break
    fi

    if [ -f "$STOP_FILE" ]; then
        rm -f "$STOP_FILE"
        now=$(date +%s%3N)
        printf '{"schema":"s0.2-1","sessionId":"%s","kind":"complete","wallClockMs":%s,"data":{"reason":"stop_requested","detections":%s,"actions":%s}}\n' \
            "$SESSION" "$now" "$sequence" "$actions"
        break
    fi

    if [ "$poll_end" -ge "$deadline" ]; then
        printf '{"schema":"s0.2-1","sessionId":"%s","kind":"timeout","wallClockMs":%s,"data":{"detections":%s,"actions":%s}}\n' \
            "$SESSION" "$poll_end" "$sequence" "$actions"
        break
    fi
    sleep 0.03
done
'@

$remoteScript = $remoteScript.Replace('__SESSION__', $sessionId)
$remoteScript = $remoteScript.Replace('__SCENARIO__', $Scenario)
$remoteScript = $remoteScript.Replace('__MODE__', $modeValue)
$remoteScript = $remoteScript.Replace('__ARM__', $armValue)
$remoteScript = $remoteScript.Replace('__MAX__', "$BatchCount")
$remoteScript = $remoteScript.Replace('__REQUESTED_BLOCK__', "$requestedBlock")
$remoteScript = $remoteScript.Replace('__REQUESTED_ALLOWED__', "$requestedAllowed")
$remoteScript = $remoteScript.Replace('__STOP_FILE__', $stopFile)
$remoteScript = $remoteScript.Replace('__TIMEOUT_MS__', "$($TimeoutSeconds * 1000)")

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $adb
$startInfo.Arguments = "-s $Serial shell sh"
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.CreateNoWindow = $true
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $startInfo
$writer = [System.IO.StreamWriter]::new(
    $outputPath,
    $false,
    [System.Text.UTF8Encoding]::new($false)
)
$scenarioStarted = $false
$processStarted = $false

try {
    if (-not $process.Start()) { throw 'Failed to start the ADB companion process.' }
    $processStarted = $true
    $process.StandardInput.Write($remoteScript)
    $process.StandardInput.Close()

    while (-not $process.StandardOutput.EndOfStream) {
        $line = $process.StandardOutput.ReadLine()
        if (-not $line) { continue }
        try {
            $event = $line | ConvertFrom-Json
        } catch {
            Write-Warning "Ignored non-JSON companion output: $line"
            continue
        }
        $writer.WriteLine($line)
        $writer.Flush()

        if ($event.kind -eq 'ready' -and -not $scenarioStarted) {
            $scenarioStarted = $true
            if ($Scenario -eq 'block') {
                Start-BlockBatch -Writer $writer
            } else {
                Start-AllowedProbes -Writer $writer -StopFile $stopFile
            }
        }
    }

    $process.WaitForExit()
    $errorText = $process.StandardError.ReadToEnd().Trim()
    Write-LocalEvent -Writer $writer -Kind 'companion_process_exit' -Data @{
        exitCode = $process.ExitCode
        stderr = $errorText
    }
    if (-not $scenarioStarted) { throw 'The companion never reached its ready state.' }
    if ($process.ExitCode -ne 0) { throw "ADB companion exited with code $($process.ExitCode)." }
} finally {
    if ($processStarted -and -not $process.HasExited) {
        try { $null = Invoke-AdbText @('shell', 'touch', $stopFile) } catch { }
        if (-not $process.WaitForExit(5000)) { $process.Kill() }
    }
    $writer.Dispose()
    try { $null = Invoke-AdbText @('shell', 'rm', '-f', $stopFile) } catch { }
    try { $null = Invoke-AdbText @('shell', 'input', 'keyevent', '3') } catch { }
    $process.Dispose()
}

& python (Join-Path $PSScriptRoot 's02_report.py') $outputPath --output $reportPath
if ($LASTEXITCODE -ne 0) { throw "S0.2 report generation failed with exit code $LASTEXITCODE" }

Get-Item -LiteralPath $outputPath, $reportPath | Select-Object FullName, Length, LastWriteTime
