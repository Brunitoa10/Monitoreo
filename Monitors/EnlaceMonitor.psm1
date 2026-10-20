function Invoke-EnlaceMonitor {

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        $Device
    )

    $PadrePing = Get-PingStatus `
        -IPAddress $Device.IPAddress_Padre

    $HijoPing = Get-PingStatus `
        -IPAddress $Device.IPAddress_Hijo

    $Status =  if ($PadrePing.Online -and $HijoPing.Online) {
		$Global:Status.HEALTHY
    }
    elseif ($PadrePing.Online -or $HijoPing.Online) {
		$Global:Status.WARNING
    }
    else {
		 $Global:Status.CRITICAL
    }

    [PSCustomObject]@{

        DeviceName     = $Device.Name
        DeviceType     = "Enlace"
        Site           = $Device.Site

        IPAddressPadre = $Device.IPAddress_Padre
        IPAddressHijo  = $Device.IPAddress_Hijo

        PadreOnline    = $PadrePing.Online
        HijoOnline     = $HijoPing.Online

        PadreLatency   = $PadrePing.Latency
        HijoLatency    = $HijoPing.Latency

        Status         = $Status
        Timestamp      = Get-Date
    }
}

Export-ModuleMember `
    -Function Invoke-EnlaceMonitor