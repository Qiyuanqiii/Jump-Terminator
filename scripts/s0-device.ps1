param(
    [ValidateSet('status', 'install', 'export')]
    [string]$Action = 'status',
    [string]$Serial = '',
    [string]$Output = ''
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$androidSdk = Join-Path $env:USERPROFILE '.cache\jump-terminator\toolchain\android-sdk'
$adb = Join-Path $androidSdk 'platform-tools\adb.exe'

if (-not (Test-Path -LiteralPath $adb)) { throw "adb not found: $adb" }

function Invoke-AdbText {
    param([string[]]$Arguments)
    $allArguments = @()
    if ($Serial) { $allArguments += @('-s', $Serial) }
    $allArguments += $Arguments
    & $adb @allArguments
    if ($LASTEXITCODE -ne 0) { throw "adb command failed with exit code $LASTEXITCODE" }
}

function Resolve-DeviceSerial {
    $deviceLines = & $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" }
    $serials = @($deviceLines | ForEach-Object { ($_ -split "\t")[0] })
    if ($Serial) {
        if ($Serial -notmatch '^[A-Za-z0-9._:-]+$') { throw 'Device serial contains invalid characters.' }
        if ($Serial -notin $serials) { throw "Specified device is not connected: $Serial" }
        return
    }
    if ($serials.Count -eq 0) { throw 'No authorized ADB device found.' }
    if ($serials.Count -gt 1) { throw 'Multiple devices connected; select one with -Serial.' }
    $script:Serial = $serials[0]
}

function Export-RemoteFile {
    param(
        [string]$RemotePath,
        [System.IO.Stream]$Destination
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $adb
    $startInfo.Arguments = "-s $Serial exec-out run-as com.jumpterminator.app cat $RemotePath"
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::Start($startInfo)
    $process.StandardOutput.BaseStream.CopyTo($Destination)
    $errorText = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Error = $errorText }
}

function Test-RemoteFile {
    param([string]$RemotePath)
    & $adb -s $Serial shell run-as com.jumpterminator.app test -f $RemotePath 2>$null
    return $LASTEXITCODE -eq 0
}

Resolve-DeviceSerial

switch ($Action) {
    'status' {
        Invoke-AdbText @('shell', 'getprop', 'ro.product.manufacturer')
        Invoke-AdbText @('shell', 'getprop', 'ro.product.model')
        Invoke-AdbText @('shell', 'getprop', 'ro.build.version.release')
        Invoke-AdbText @('shell', 'getprop', 'ro.build.version.sdk')
        Invoke-AdbText @('shell', 'settings', 'get', 'secure', 'enabled_accessibility_services')
        Invoke-AdbText @('shell', 'appops', 'get', 'com.jumpterminator.app', 'GET_USAGE_STATS')
    }
    'install' {
        $apks = @(
            (Join-Path $workspaceRoot 'app\build\outputs\apk\debug\app-debug.apk'),
            (Join-Path $workspaceRoot 'test-target\build\outputs\apk\debug\test-target-debug.apk'),
            (Join-Path $workspaceRoot 'test-source\build\outputs\apk\debug\test-source-debug.apk')
        )
        foreach ($apk in $apks) {
            if (-not (Test-Path -LiteralPath $apk)) { throw "APK missing; run scripts/s0-build.ps1 first: $apk" }
            Invoke-AdbText @('install', '-r', $apk)
        }
        Invoke-AdbText @('shell', 'am', 'start', '-n', 'com.jumpterminator.app/.MainActivity')
    }
    'export' {
        if (-not $Output) {
            $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $Output = Join-Path $workspaceRoot "docs\s0\results\timeline-$timestamp.jsonl"
        }
        $outputPath = [System.IO.Path]::GetFullPath($Output)
        $outputDirectory = [System.IO.Path]::GetDirectoryName($outputPath)
        [System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
        $destination = [System.IO.File]::Open($outputPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
        try {
            $copied = 0
            foreach ($remote in @('files/s0/timeline.2.jsonl', 'files/s0/timeline.1.jsonl', 'files/s0/timeline.jsonl')) {
                if (-not (Test-RemoteFile -RemotePath $remote)) { continue }
                $result = Export-RemoteFile -RemotePath $remote -Destination $destination
                if ($result.ExitCode -eq 0) { $copied += 1 }
            }
        } finally {
            $destination.Dispose()
        }
        if ($copied -eq 0) { throw 'No S0 timeline was available on the device.' }
        Get-Item -LiteralPath $outputPath | Select-Object FullName, Length, LastWriteTime
    }
}
