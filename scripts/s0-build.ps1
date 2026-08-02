param()

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$toolchainRoot = Join-Path $env:USERPROFILE '.cache\jump-terminator\toolchain'
$jdkRoot = Get-ChildItem -LiteralPath (Join-Path $toolchainRoot 'jdk') -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\java.exe') } |
    Select-Object -First 1
$androidSdk = Join-Path $toolchainRoot 'android-sdk'
$portableGradle = Join-Path $toolchainRoot 'gradle\gradle-9.1.0\bin\gradle.bat'

if ($null -eq $jdkRoot) {
    throw 'S0 portable JDK not found. Install JDK 17 or follow docs/s0/README.md.'
}
if (-not (Test-Path -LiteralPath (Join-Path $androidSdk 'platforms\android-36\android.jar'))) {
    throw 'Android API 36 SDK not found. Follow docs/s0/README.md.'
}

$env:JAVA_HOME = $jdkRoot.FullName
$env:ANDROID_SDK_ROOT = $androidSdk
$env:ANDROID_HOME = $androidSdk
$env:PATH = "$($jdkRoot.FullName)\bin;$(Join-Path $androidSdk 'platform-tools');$env:PATH"

Push-Location $workspaceRoot
try {
    if (Test-Path -LiteralPath $portableGradle) {
        & $portableGradle testDebugUnitTest assembleDebug --no-daemon
    } else {
        & (Join-Path $workspaceRoot 'gradlew.bat') testDebugUnitTest assembleDebug --no-daemon
    }
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed with exit code $LASTEXITCODE" }

    Get-Item -LiteralPath @(
        (Join-Path $workspaceRoot 'app\build\outputs\apk\debug\app-debug.apk'),
        (Join-Path $workspaceRoot 'test-source\build\outputs\apk\debug\test-source-debug.apk'),
        (Join-Path $workspaceRoot 'test-target\build\outputs\apk\debug\test-target-debug.apk')
    ) | Select-Object FullName, Length, LastWriteTime
} finally {
    Pop-Location
}
