function Start-NemesisMonitoring {

    $StopWatch = [System.Diagnostics.Stopwatch]::StartNew()

    $Devices = Get-NemesisDevices `
        -ConfigRoot ".\Config\Sites"

    if (-not $Devices) {

        Write-NemesisLog `
            -Level "WARNING" `
            -Message "No devices found."

        return @()
    }

    $Results = [System.Collections.Generic.List[object]]::new()

    foreach ($Device in $Devices) {

        try {

            switch ($Device.Type) {

                "Switch" {

                    $Results.Add(
                        (Invoke-SwitchMonitor -Device $Device)
                    )
                }

                "Printer" {

                    $Results.Add(
                        (Invoke-PrinterMonitor -Device $Device)
                    )
                }

                "Enlace" {

                    $Results.Add(
                        (Invoke-EnlaceMonitor -Device $Device)
                    )
                }
				
				 "Carteleria" {

                    $Results.Add(
                        (Invoke-CarteleriaMonitor -Device $Device)
                    )
                }
				
				"UPS" {

                    $Results.Add(
                        (Invoke-UpsMonitor -Device $Device)
                    )
                }

                default {

                    Write-NemesisLog `
                        -Level "WARNING" `
                        -Message "Device type not implemented: $($Device.Type)"
                }
            }
        }
        catch {

            Write-NemesisLog `
                -Level "ERROR" `
                -Message $_.Exception.Message
        }
    }

    $StopWatch.Stop()

    return $Results
}

Export-ModuleMember `
    -Function Start-NemesisMonitoring