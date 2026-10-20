class HealthResult {

    [string]$DeviceName

    [string]$IPAddress

    [string]$DeviceType

    [string]$Site

    [bool]$Online

    [double]$Latency

    [string]$Status

    [datetime]$Timestamp

    HealthResult() {

        $this.Timestamp = Get-Date
    }
}