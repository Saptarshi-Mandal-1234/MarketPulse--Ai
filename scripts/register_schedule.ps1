$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$taskName = 'MarketPulse AI Daily'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Project Python environment is missing.' }
if ((Get-TimeZone).Id -ne 'India Standard Time') { throw 'Set the intended Indian schedule timezone before registration.' }
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.Actions.WorkingDirectory -ne $projectRoot) {
    throw 'A task with this name belongs to another project; leaving it unchanged.'
}
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-m marketpulse.pipeline --daily' -WorkingDirectory $projectRoot
$triggers = @((New-ScheduledTaskTrigger -Daily -At '16:00'))
$accountSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$principal = New-ScheduledTaskPrincipal -UserId $accountSid -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Refresh MarketPulse 30 minutes after the regular 15:30 NSE close (16:00 IST). Laptop must be on and user logged in.' -Force | Out-Null
$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
$receipt = [ordered]@{ task = $taskName; state = [string]$task.State; times_ist = @('16:00'); next_run = $info.NextRunTime.ToString('o'); interactive_logon_required = $true; project = $projectRoot }
$receipt | ConvertTo-Json | Set-Content (Join-Path $projectRoot 'reports\pipeline\schedule.json') -Encoding utf8
$receipt | ConvertTo-Json
