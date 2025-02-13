param(
    [string]$binary_invocation,
    [string]$src_file,
    [string]$out_file,
    [string]$assembly_flavor
)

# Ensure four parameters are passed
if ($args.Count -ne 4) {
    Write-Host "Need four params"
    exit 1
}

# Run the binary invocation
& $binary_invocation $src_file $assembly_flavor $out_file

# Check if the output file exists
if (Test-Path $out_file) {
    Write-Host "$out_file exists"
} else {
    Write-Host "$out_file does not exist, failing"
    exit 1
}

# Exit with success
exit 0