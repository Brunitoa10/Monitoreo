function Show-NemesisDashboard {

    param(
        [array]$Results
    )

    Clear-Host

    if (-not $Results) {
        Write-Host ""
        Write-Host "No data available." -ForegroundColor Magenta
        Write-Host ""
        return
    }

    Show-DashboardHeader -Results $Results

    Show-DashboardSwitches -Results $Results

    Show-DashboardEnlaces -Results $Results

    Show-DashboardPrinters -Results $Results

    Show-DashboardCarteleria -Results $Results
	
	Show-DashboardUps -Results $Results

    Show-DashboardSummary -Results $Results
}

Export-ModuleMember -Function Show-NemesisDashboard