function Invoke-PrinterMonitor {

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

        DeviceType = "Printer"

        Site = $Device.Site

        IPAddress = $Device.IPAddress

        Online = $Ping.Online

        Latency = $Ping.Latency

        Status = $Status

        Timestamp = Get-Date
    }
}

Export-ModuleMember `
    -Function Invoke-PrinterMonitor