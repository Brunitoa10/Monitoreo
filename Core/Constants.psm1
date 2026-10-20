$Global:Status = @{
    Healthy = "HEALTHY" 
    Warning = "WARNING"
    Critical = "CRITICAL"
	Available  = "AVAILABLE"
    Unknown = "UNKNOWN"
}

Export-ModuleMember `
    -Variable Status