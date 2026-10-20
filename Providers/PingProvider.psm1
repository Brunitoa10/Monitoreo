function Get-PingStatus {

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$IPAddress
    )

    try {

        $Ping = New-Object System.Net.NetworkInformation.Ping

        $Reply = $Ping.Send($IPAddress, 500)

        if ($Reply.Status -eq "Success") {

            return [PSCustomObject]@{
                Online  = $true
                Latency = $Reply.RoundtripTime
            }
        }

        [PSCustomObject]@{
            Online  = $false
            Latency = 0
        }
    }
    catch {

        [PSCustomObject]@{
            Online  = $false
            Latency = 0
        }
    }
}

Export-ModuleMember `
    -Function Get-PingStatus