function Import-NemesisModule {

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        throw "Module not found: $Path"
    }

    Import-Module `
        -Name $Path `
        -Force `
        -Global `
        -ErrorAction Stop
}

function Initialize-Nemesis {

    $Modules = @(
        "$PSScriptRoot\Logger.psm1",
        "$PSScriptRoot\Constants.psm1",

        "$PSScriptRoot\..\Repositories\JsonDeviceRepository.psm1",

        "$PSScriptRoot\..\Providers\PingProvider.psm1",
        "$PSScriptRoot\..\Providers\TcpProvider.psm1",

        "$PSScriptRoot\..\Monitors\SwitchMonitor.psm1",
        "$PSScriptRoot\..\Monitors\PrinterMonitor.psm1",
		"$PSScriptRoot\..\Monitors\EnlaceMonitor.psm1",
		"$PSScriptRoot\..\Monitors\CarteleriaMonitor.psm1",
		"$PSScriptRoot\..\Monitors\UpsMonitor.psm1",
		
        "$PSScriptRoot\..\Services\MonitoringService.psm1",


        "$PSScriptRoot\..\Presentation\ConsoleDashboard.psm1"
    )

    foreach ($Module in $Modules) {

        try {

            Import-NemesisModule `
                -Path $Module

            Write-Host "[OK] Loaded: $Module" `
                -ForegroundColor Green
        }
        catch {

            Write-Error `
                "Failed importing module: $Module`n$($_.Exception.Message)"

            throw
        }
    }

    Write-Host ""
    Write-Host "Nemesis initialized successfully." `
        -ForegroundColor Green
}

Export-ModuleMember `
    -Function Initialize-Nemesis