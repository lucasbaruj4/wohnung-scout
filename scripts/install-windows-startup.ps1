param([Parameter(Mandatory=$true)][string]$Distro)
$ErrorActionPreference = 'Stop'
$taskName = 'Wohnung Scout'
$folder = Join-Path $env:LOCALAPPDATA 'WohnungScout'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$launcher = Join-Path $folder 'keep-running.ps1'
$escapedDistro = $Distro.Replace("'", "''")
$content = @"
`$ErrorActionPreference = 'Stop'
& "`$env:SystemRoot\System32\wsl.exe" -d '$escapedDistro' --exec /bin/bash -lc 'systemctl --user start wohnung-scout.service && exec /usr/bin/sleep infinity'
exit `$LASTEXITCODE
"@
if (!(Test-Path $launcher) -or (Get-Content $launcher -Raw) -ne $content) {
    Set-Content -Path $launcher -Value $content -Encoding UTF8 -NoNewline
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$running = $existing -and $existing.State -eq 'Running'
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Keep the local Wohnung Scout WSL service running while Windows is awake.' -Force | Out-Null
if (!$running) { Start-ScheduledTask -TaskName $taskName }
$task = Get-ScheduledTask -TaskName $taskName
Write-Output "Windows logon task '$taskName' is installed. State: $($task.State)."
