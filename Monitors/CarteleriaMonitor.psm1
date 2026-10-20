function Invoke-CarteleriaMonitor {

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        $Device
    )

    $Ping = Get-PingStatus `
        -IPAddress $Device.IPAddress

    $Status = if ($Ping.Online) {
        $Global:Status.HEALTHY
    }
    else {
		$Global:Status.CRITICAL
    }

    [PSCustomObject]@{

        DeviceName = $Device.Name

        DeviceType = "Carteleria"

        Site = $Device.Site

        IPAddress = $Device.IPAddress

        Online = $Ping.Online

        Latency = $Ping.Latency

        Status = $Status

        Timestamp = Get-Date
    }
}

Export-ModuleMember `
    -Function Invoke-CarteleriaMonitor