function Show-DashboardEnlaces {

    param(
        [array]$Results
    )

    $Enlaces = @(
        $Results |
        Where-Object {
            $_.DeviceType -eq "Enlace"
        } |
        Sort-Object {
            [version]$_.IPAddressPadre
        }
    )

    if ($Enlaces.Count -eq 0) {
        return
    }

    Write-Host ""
    Write-Host "===================== ENLACES =====================" -ForegroundColor Cyan
    Write-Host ""

    $Header = "{0,-25} {1,-10} {2,-15} {3,-15} {4,-8} {5,-8} {6,-10}" -f `
        "Nombre",
        "Site",
        "IP Padre",
        "IP Hijo",
        "Padre",
        "Hijo",
        "Status"

    Write-Host $Header -ForegroundColor White
    Write-Host ("-" * 110) -ForegroundColor DarkGray

    foreach ($Result in $Enlaces) {

        $Line = "{0,-25} {1,-10} {2,-15} {3,-15} {4,-8} {5,-8} {6,-10}" -f `
            $Result.DeviceName,
            $Result.Site,
            $Result.IPAddressPadre,
            $Result.IPAddressHijo,
            $(if ($Result.PadreOnline) { "UP" } else { "DOWN" }),
            $(if ($Result.HijoOnline) { "UP" } else { "DOWN" }),
            $Result.Status

        switch ($Result.Status) {

            $Status.Healthy {
                Write-Host $Line -ForegroundColor Green
            }

            $Status.Warning {
                Write-Host $Line -ForegroundColor Yellow
            }

            $Status.Critical {
                Write-Host $Line -ForegroundColor Red
            }

            default {
                Write-Host $Line -ForegroundColor White
            }
        }
    }

    Write-Host ""
}

Export-ModuleMember -Function Show-DashboardEnlaces