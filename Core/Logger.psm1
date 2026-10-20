function Write-NemesisLog {

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [ValidateSet(
            "INFO",
            "WARNING",
            "ERROR",
            "SUCCESS"
        )]
        [string]$Level,

        [Parameter(Mandatory)]
        [string]$Message
    )

    $LogDirectory = ".\Logs\Monitoring"

    if (-not (Test-Path $LogDirectory)) {

        New-Item `
            -Path $LogDirectory `
            -ItemType Directory `
            -Force | Out-Null
    }

    $LogFile = Join-Path `
        $LogDirectory `
        ("monitor-{0}.log" -f (Get-Date -Format "yyyyMMdd"))

    $Line = "{0} [{1}] {2}" -f `
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss"),
        $Level.ToUpper(),
        $Message

    switch ($Level.ToUpper()) {

        "SUCCESS" {
            Write-Host $Line -ForegroundColor Green
        }

        "INFO" {
            Write-Host $Line -ForegroundColor Cyan
        }

        "WARNING" {
            Write-Host $Line -ForegroundColor Yellow
        }

        "ERROR" {
            Write-Host $Line -ForegroundColor Red
        }

        default {
            Write-Host $Line -ForegroundColor White
        }
    }

    Add-Content `
        -Path $LogFile `
        -Value $Line
}

Export-ModuleMember `
    -Function Write-NemesisLog