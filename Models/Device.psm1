class Device {

    [string]$Name

    [string]$IPAddress

    [string]$Type

    [string]$Site

    Device(
        [string]$Name,
        [string]$IPAddress,
        [string]$Type,
        [string]$Site
    ) {
        $this.Name = $Name
        $this.IPAddress = $IPAddress
        $this.Type = $Type
        $this.Site = $Site
    }
}