function Show-DashboardSummary {

    param(
        [array]$Results
    )

    $Healthy = @($Results | Where-Object Status -eq "HEALTHY").Count
    $Warning = @($Results | Where-Object Status -eq "WARNING").Count
    $Critical = @($Results | Where-Object Status -eq "CRITICAL").Count

    Write-Host ""

    Write-Host "============================================================" -ForegroundColor DarkGray

    Write-Host ("HEALTHY : {0}" -f $Healthy) -ForegroundColor Green
    Write-Host ("WARNING : {0}" -f $Warning) -ForegroundColor Yellow
    Write-Host ("CRITICAL: {0}" -f $Critical) -ForegroundColor Red
	
    Write-Host ""
    Write-Host "Refresh: 30 Seconds" -ForegroundColor DarkGray
    Write-Host ""
}

Export-ModuleMember -Function Show-DashboardSummary