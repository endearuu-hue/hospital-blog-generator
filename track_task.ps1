# 매일 아침 9시에 순위 추적 캡처를 돌리는 윈도우 예약 작업을 등록한다.
# PC가 그 시각에 꺼져 있었으면 켜진 뒤 바로 한 번 돈다. 지우려면: Unregister-ScheduledTask -TaskName HospitalBlogRankTrack
$dir = $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "$dir\.venv\Scripts\pythonw.exe" -Argument "-m services.tracker" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "HospitalBlogRankTrack" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
"등록됨: 매일 오전 9시 (HospitalBlogRankTrack)"
