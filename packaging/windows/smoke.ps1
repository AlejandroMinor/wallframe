# Opens the package at $args[0] and fails unless it keeps running on its own DLLs.
param([Parameter(Mandatory)] [string] $Package)

$ErrorActionPreference = "Stop"
$folder = (Resolve-Path $Package).Path
Remove-Item Env:MSYSTEM -ErrorAction SilentlyContinue
$env:Path = "$env:SystemRoot\system32;$env:SystemRoot"
Start-Process (Join-Path $folder "wallframe.exe")
Start-Sleep -Seconds 15

$running = Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$folder*" }
if (-not $running) { throw "wallframe did not keep running" }
$outside = $running.Modules.FileName | Where-Object { $_ -like "*msys64*" }
if ($outside) { throw "wallframe loaded DLLs from MSYS2: $outside" }
Write-Host "wallframe runs with $($running.Modules.Count) modules, none from MSYS2"
$running | Stop-Process -Force
