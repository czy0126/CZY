# Run on a genuine signed ADI LTspice 26 Windows *interactive desktop*.
# This script DOES NOT initialize LTspice, accept consent dialogs, change any
# Windows preferences, or claim any hardware qualification.
# Example:
#   pwsh -File tools/run_poc_windows_desktop.ps1 -Case smoke
#   pwsh -File tools/run_poc_windows_desktop.ps1 -Case 5a -Mode off
#   pwsh -File tools/run_poc_windows_desktop.ps1 -Case 5a -Mode both -TimeoutSec 1200
param(
    [ValidateSet("smoke", "5a", "10a")]
    [string] $Case = "smoke",
    [ValidateSet("off", "on", "both")]
    [string] $Mode = "off",
    [string] $LTspicePath = "",
    [ValidateRange(5,7200)]
    [int] $TimeoutSec = 1200
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python 3 is required on the desktop."
    }
    if (-not $LTspicePath) {
        $paths = @()
        if ($env:LOCALAPPDATA) {
            $paths += (Join-Path $env:LOCALAPPDATA "Programs\ADI\LTspice\LTspice.exe")
        }
        if ($env:ProgramFiles) {
            $paths += (Join-Path $env:ProgramFiles "ADI\LTspice\LTspice.exe")
        }
        $LTspicePath = @($paths | Where-Object { Test-Path -LiteralPath $_ } |
                         Select-Object -First 1) | Select-Object -First 1
    }
    if (-not $LTspicePath -or -not (Test-Path -LiteralPath $LTspicePath)) {
        throw "Official LTspice.exe not found: install ADI LTspice 26 and supply -LTspicePath."
    }
    $LTspicePath = (Resolve-Path -LiteralPath $LTspicePath).Path
    $signature = Get-AuthenticodeSignature -LiteralPath $LTspicePath
    if ($signature.Status -ne "Valid" -or
        -not $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -notmatch "Analog Devices") {
        throw "LTspice executable is not Authenticode-verified as signed by Analog Devices."
    }
    $exeHash = (Get-FileHash -LiteralPath $LTspicePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "ADI LTspice executable verified: $LTspicePath"
    Write-Host "Executable SHA256: $exeHash"
    Write-Host "Model-only, never a fabrication or 48V hardware-on authorization."
    & python tools/poc_low_current_decks.py --check
    if ($LASTEXITCODE -ne 0) { throw "Source-generated PoC decks are not current." }

    # Even when requested case is 5a/10a, require a new valid trivial 1V smoke
    # on THIS Windows user session; hosted headless CI is known to stall here.
    & python tools/ltspice_batch_smoke.py --ltspice $LTspicePath --out-dir sim/v3 --timeout-sec 45
    if ($LASTEXITCODE -ne 0) {
        throw ("1V smoke failed; read sim/v3/_ltspice_batch_smoke.json. " +
               "Run the officially installed LTspice interactively and handle " +
               "any first-run UI yourself; never automate telemetry consent.")
    }
    if ($Case -eq "smoke") {
        Write-Host "Trivial 1V batch preflight passed. D1 power model NOT run."
        exit 0
    }
    $record = @{
        status = "DESKTOP_MODEL_ATTEMPT_NOT_PROOF"
        case = $Case
        mode = $Mode
        executable_path = $LTspicePath
        executable_sha256 = $exeHash
        start_utc = (Get-Date).ToUniversalTime().ToString("o")
        hardware_qualified = $false
        source_decks_checked = $true
        smoke_was_required_and_passed = $true
        note = "Check poc_<case>_comparison_model_only.json and real RAW/LOG."
    }
    $recordPath = "sim/v3/poc_" + $Case + "_desktop_launcher.json"
    $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $recordPath -Encoding utf8
    & python tools/run_poc_low_current.py --case $Case --mode $Mode --run --ltspice $LTspicePath --timeout-sec $TimeoutSec
    $resultCode = $LASTEXITCODE
    if ($resultCode -ne 0) {
        throw ("LTspice model case returned $resultCode; results are NOT complete. " +
               "Review actual .log/.raw and comparison_model_only.json; " +
               "a partial RAW is not qualified. See $recordPath.")
    }
    Write-Host "Actual model run completed; assess RAW, .meas and stresses. NO hardware release."
} finally {
    Pop-Location
}
