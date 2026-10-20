function Get-NemesisDevices {

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ConfigRoot
    )

    $Devices = @()

    if (-not (Test-Path $ConfigRoot)) {
        throw "Config path not found: $ConfigRoot"
    }

    Get-ChildItem `
        -Path $ConfigRoot `
        -Recurse `
        -Filter *.json |
    ForEach-Object {

        try {

            $Json = Get-Content `
                -Path $_.FullName `
                -Raw |
            ConvertFrom-Json

            $Devices += $Json
        }
        catch {

            Write-Warning `
                "Error reading file: $($_.FullName)"
        }
    }

    return $Devices
}

Export-ModuleMember `
    -Function Get-NemesisDevices