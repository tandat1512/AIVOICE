$target = 1600
$deadline = (Get-Date).AddMinutes(10)
Write-Output ("watching: need free RAM >= {0} MB (now {1} MB)" -f $target, [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024))
$launched = $false
while ((Get-Date) -lt $deadline) {
  $free = [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)
  if ($free -ge $target) {
    Write-Output ("RAM ok ({0} MB) -> launching" -f $free)
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -EA SilentlyContinue | Where-Object {$_.CommandLine -like '*uvicorn*'} | ForEach-Object { try{Stop-Process -Id $_.ProcessId -Force}catch{} }
    Start-Sleep 2
    Remove-Item server_out.log -EA SilentlyContinue; Remove-Item server_err.log -EA SilentlyContinue
    Start-Process powershell -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File","run.ps1","serve") -WorkingDirectory (Get-Location).Path -RedirectStandardOutput server_out.log -RedirectStandardError server_err.log -WindowStyle Hidden | Out-Null
    $launched = $true; break
  }
  Start-Sleep 5
}
if (-not $launched) { Write-Output "TIMEOUT in 10 min - free more RAM (close Chrome tabs)."; exit }
for ($i=0; $i -lt 18; $i++) {
  Start-Sleep 4
  if (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -EA SilentlyContinue).Count -gt 0) {
    Write-Output ("SERVER UP. free RAM {0} MB. Open http://localhost:8000" -f [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)); exit
  }
}
Write-Output "Launched but did not bind in 72s (still OOM - free more RAM)."
