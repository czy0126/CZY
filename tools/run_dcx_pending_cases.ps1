<#
.PURPOSE
  Local Windows LTspice batch launcher for previously UNRUN DCX cases.
  Nothing is simulated by committing this script.
.EXAMPLE
  pwsh -File tools/run_dcx_pending_cases.ps1
  pwsh -File tools/run_dcx_pending_cases.ps1 -LTspice "C:\Program Files\ADI\LTspice\LTspice.exe" -Execute
#>
param(
    [string]$LTspice = "",
    [switch]$Execute,
    [string[]]$Cases = @("50V110", "50V120", "48V120Cold", "48V120Fault")
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Allow = @{
    "50V110" = "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.cir"
    "50V120" = "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir"
    "48V120Cold" = "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir"
    "48V120Fault" = "sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.cir"
}

if ($Execute -and (!(Test-Path -LiteralPath $LTspice -PathType Leaf))) {
    throw "Provide an existing LTspice.exe in -LTspice; simulation is unavailable without an actual local executable."
}

foreach ($Case in $Cases) {
    if (!$Allow.ContainsKey($Case)) {
        throw "Unknown case '$Case'. Allowed: $($Allow.Keys -join ', ')"
    }
    $Deck = Join-Path $Repo $Allow[$Case]
    if (!(Test-Path -LiteralPath $Deck -PathType Leaf)) { throw "Missing deck $Deck" }
    Write-Output "CASE $Case : $Deck (simulation NOT YET VERIFIED)"
    if (!$Execute) { continue }
    $Log = [IO.Path]::ChangeExtension($Deck, ".log")
    $Raw = [IO.Path]::ChangeExtension($Deck, ".raw")
    # Fail if existing output could be mistaken for the just-run result.
    if (Test-Path -LiteralPath $Log) { throw "Existing log must be archived/moved first: $Log" }
    if (Test-Path -LiteralPath $Raw) { throw "Existing raw must be archived/moved first: $Raw" }
    & $LTspice -b $Deck
    if ($LASTEXITCODE -ne 0) { throw "LTspice failed for $Case (exit $LASTEXITCODE)" }
    if (!(Test-Path -LiteralPath $Log -PathType Leaf) -or
        !(Test-Path -LiteralPath $Raw -PathType Leaf)) {
        throw "LTspice returned but output .log/.raw missing for $Case"
    }
    $Txt = Get-Content -LiteralPath $Log -Raw -Encoding Default
    if ($Txt -notmatch "(?i)vout_avg\s*[:=]") {
        throw "Output files exist but VOUT_AVG measurement not present for $Case; inspect solver."
    }
    Write-Output "COMPLETE FILES ONLY $Case; verify waveforms, control and OC before publishing results."
}
if (!$Execute) {
    Write-Output "DRY RUN ONLY. Run again with -LTspice <real path> -Execute; no performance results generated."
}
