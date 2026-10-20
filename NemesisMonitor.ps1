Set-StrictMode -Version Latest

$RootPath = Split-Path `
    -Parent `
    $MyInvocation.MyCommand.Path

Import-Module `
    "$RootPath\Core\Bootstrap.psm1" `
    -Force

Initialize-Nemesis

Import-Module `
    "$RootPath\Services\MonitoringService.psm1" `
    -Force

Get-ChildItem "$PSScriptRoot\Presentation\*.psm1" |
ForEach-Object {
    Import-Module $_.FullName -Force
}

while ($true) {

    try {

        $Results = Start-NemesisMonitoring

        Show-NemesisDashboard `
            -Results $Results
    }
    catch {

        Write-Host ""
        Write-Host "Monitoring Error:" `
            -ForegroundColor Red

        Write-Host $_.Exception.Message `
            -ForegroundColor Yellow
    }

    Start-Sleep -Seconds 10
}