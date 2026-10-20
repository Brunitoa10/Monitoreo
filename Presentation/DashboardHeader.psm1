function Show-DashboardHeader {

    param(
        [array]$Results
    )

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "                       MONITOR" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""

    Write-Host ("Timestamp : {0}" -f (Get-Date))
    Write-Host ("Devices   : {0}" -f $Results.Count)

    Write-Host ""
}

Export-ModuleMember -Function Show-DashboardHeader