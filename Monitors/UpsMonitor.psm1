function Invoke-UpsMonitor {

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        $Device
    )

    $Ping = Get-PingStatus -IPAddress $Device.IPAddress

    $Status = $Global:Status.CRITICAL
    $Latency = "-"

    if ($Ping -and $Ping.Online) {
        $Status = $Global:Status.HEALTHY
        $Latency = $Ping.Latency
    }

    [PSCustomObject]@{
        DeviceName = $Device.Name
        DeviceType = "UPS"
        Site       = $Device.Site
        IPAddress  = $Device.IPAddress
        Latency    = $Latency
        Status     = $Status
        Timestamp  = Get-Date
    }
}

Export-ModuleMember -Function Invoke-UpsMonitor