function Test-TcpPort {

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$IPAddress,

        [Parameter(Mandatory)]
        [int]$Port,

        [int]$Timeout = 1000
    )

    try {

        $Client = New-Object System.Net.Sockets.TcpClient

        $Connect = $Client.BeginConnect(
            $IPAddress,
            $Port,
            $null,
            $null
        )

        $Connected = $Connect.AsyncWaitHandle.WaitOne(
            $Timeout,
            $false
        )

        if (-not $Connected) {

            $Client.Close()

            return [PSCustomObject]@{
                Online   = $false
                Port     = $Port
                Latency  = 0
                Status   = "CLOSED"
            }
        }

        $Client.EndConnect($Connect)

        $Client.Close()

        return [PSCustomObject]@{
            Online   = $true
            Port     = $Port
            Latency  = 0
            Status   = "OPEN"
        }
    }
    catch {

        return [PSCustomObject]@{
            Online   = $false
            Port     = $Port
            Latency  = 0
            Status   = "CLOSED"
        }
    }
}

Export-ModuleMember `
    -Function Test-TcpPort