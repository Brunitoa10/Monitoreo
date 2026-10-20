function Show-DashboardPrinters {

    param(
        [array]$Results
    )

    $Printers = @(
        $Results |
        Where-Object {
            $_.DeviceType -eq "Printer"
        } |
        Sort-Object IPAddress
    )

    if ($Printers.Count -eq 0) {
        return
    }

    Write-Host ""
    Write-Host "==================== PRINTERS ====================" -ForegroundColor Cyan
    Write-Host ""

    $Header = "{0,-35} {1,-12} {2,-15} {3,-10} {4,8}" -f `
        "DeviceName",
        "Site",
        "IPAddress",
        "Status",
        "Latency"

    Write-Host $Header -ForegroundColor White
    Write-Host ("-" * 90) -ForegroundColor DarkGray

    foreach ($Result in $Printers) {

        $Line = "{0,-35} {1,-12} {2,-15} {3,-10} {4,8}" -f `
            $Result.DeviceName,
            $Result.Site,
            $Result.IPAddress,
            $Result.Status,
            $Result.Latency

        switch ($Result.Status) {
            "HEALTHY"  { Write-Host $Line -ForegroundColor Green }
            "WARNING"  { Write-Host $Line -ForegroundColor Yellow }
            "CRITICAL" { Write-Host $Line -ForegroundColor Red }
            default    { Write-Host $Line -ForegroundColor White }
        }
    }

    Write-Host ""
}

Export-ModuleMember -Function Show-DashboardPrinters