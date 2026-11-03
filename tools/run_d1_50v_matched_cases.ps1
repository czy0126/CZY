<#
PROT-03 50V/120A matched controls. Dry-run unless explicitly -Execute.
Retain all RAW/LOG and SHA256, including failed and truncated runs.
#>
param([switch]$Execute,[string]$RunId="",[string]$LTspice="",
  [string[]]$Cases=@("A_CONTROL","A_CANDIDATE","B_CONTROL","B_CANDIDATE"))
$ErrorActionPreference="Stop"
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SimDir=Join-Path $Root "sim/v3"
$Decks=@{
 "A_CONTROL"="sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v_thrmute_control.cir"
 "A_CANDIDATE"="sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v.cir"
 "B_CONTROL"="sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v_thrmute_control.cir"
 "B_CANDIDATE"="sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.cir"
}
foreach($Case in $Cases){
 if(!$Decks.ContainsKey($Case)){throw "Unknown case $Case"}
 $Txt=Get-Content -LiteralPath (Join-Path $SimDir $Decks[$Case]) -Raw -Encoding utf8
 if($Txt -notmatch '\.options\s+plotwinsize=0\s+method=gear\s+cshunt=1e-15'){throw "Solver options changed $Case"}
 if($Txt -notmatch '\.tran\s+0\s+2320u\s+2000u\s+5n\s+uic'){throw "320us save window changed $Case"}
 if($Txt -notmatch '\.include\s+\.\./\.\./models/'){throw "Model includes changed $Case"}
}
if(!$Execute){
 foreach($Case in $Cases){Write-Output "DRY_RUN $Case $($Decks[$Case])"}
 Write-Output "NO NEW RAW. Invoke -Execute -RunId unique_tag -LTspice exe_path."
 return
}
if($RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,35}$'){throw "RunId needs unique 3..36 permitted chars"}
if(!$LTspice){
 foreach($Guess in @((Join-Path $env:ProgramFiles "ADI/LTspice/LTspice.exe"),
   (Join-Path $env:LOCALAPPDATA "Programs/ADI/LTspice/LTspice.exe"))){
   if(Test-Path -LiteralPath $Guess -PathType Leaf){$LTspice=$Guess;break}
 }
}
if(!(Test-Path -LiteralPath $LTspice -PathType Leaf)){throw "Need installed LTspice.exe"}
$Archive=Join-Path $Root ("out/d1_50v/"+$RunId)
if(Test-Path -LiteralPath $Archive){throw "Refuse overwrite archive $Archive"}
New-Item -ItemType Directory -Path $Archive -Force | Out-Null
$Results=@()
foreach($Case in $Cases){
 $Source=Join-Path $SimDir $Decks[$Case]
 # Stage in SAME directory to preserve original ../../models includes.
 $Stage=Join-Path $SimDir ("d1_"+$RunId+"_"+$Case+".cir")
 $Raw=[IO.Path]::ChangeExtension($Stage,".raw")
 $Log=[IO.Path]::ChangeExtension($Stage,".log")
 foreach($File in @($Stage,$Raw,$Log)){if(Test-Path -LiteralPath $File){throw "Refuse overwrite $File"}}
 $CaseDir=Join-Path $Archive $Case
 New-Item -ItemType Directory -Path $CaseDir -Force | Out-Null
 $R=[ordered]@{case=$Case;source=$Decks[$Case];source_sha256=(Get-FileHash $Source -Algorithm SHA256).Hash.ToLower();
   state="NOT_RUN";solver_finished=$false;tail_us=$null;reached_320us=$false;
   raw_sha256=$null;log_sha256=$null;reason=""}
 Copy-Item -LiteralPath $Source -Destination $Stage
 try{
   & $LTspice -b -ascii $Stage
   if($LASTEXITCODE -ne 0){throw "LTspice exit $LASTEXITCODE"}
   if(!(Test-Path $Raw) -or !(Test-Path $Log)){throw "No raw/log"}
   $R.solver_finished=[bool]((Get-Content $Log -Raw -Encoding Default) -match "Total elapsed time")
   $TimeUs=& python -c 'import sys;sys.path.insert(0,sys.argv[1]);from ascii_raw_window import last_time;print(last_time(sys.argv[2])*1e6)' (Join-Path $Root "tools") $Raw
   if($LASTEXITCODE -ne 0){throw "ASCII raw tail parser failed"}
   $R.tail_us=[double]::Parse($TimeUs.Trim(),[Globalization.CultureInfo]::InvariantCulture)
   $R.reached_320us=($R.tail_us -ge 319.999)
   if($R.solver_finished -and $R.reached_320us){$R.state="DURATION_ONLY_PASS"}
   else{$R.state="INCOMPLETE_PREFIX"}
 }catch{$R.state="FAILED_KEEP_EVIDENCE";$R.reason=$_.Exception.Message}
 finally{
   foreach($File in @($Stage,$Raw,$Log)){
     if(Test-Path -LiteralPath $File -PathType Leaf){
       if($File -eq $Raw){$R.raw_sha256=(Get-FileHash $Raw -Algorithm SHA256).Hash.ToLower()}
       if($File -eq $Log){$R.log_sha256=(Get-FileHash $Log -Algorithm SHA256).Hash.ToLower()}
       Move-Item -LiteralPath $File -Destination (Join-Path $CaseDir ([IO.Path]::GetFileName($File)))
     }
   }
 }
 $Results += $R
 Write-Output "$Case $($R.state) t_last=$($R.tail_us)us"
}
$Manifest=[ordered]@{kind="LTSIM_ONLY";run_id=$RunId;pre_fault_1mV_paired_verified=$false;
  ten_physical_gate_shutdown_verified=$false;fabrication_approved=$false;cases=$Results}
$Report=Join-Path $Archive "run_manifest.json"
[IO.File]::WriteAllText($Report,($Manifest | ConvertTo-Json -Depth 7),[Text.UTF8Encoding]::new($false))
if(@($Results | Where-Object {$_.state -ne "DURATION_ONLY_PASS"}).Count -gt 0){
 throw "Incomplete runs retained at $Report"
}
Write-Output "Only 320us completeness checked; paired pre-fault, Vgs/Id and hardware safety NOT VERIFIED."
