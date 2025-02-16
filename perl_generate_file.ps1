# Set strict error handling similar to Bash's 'set -euo pipefail'
$ErrorActionPreference = "Stop"

# Check if exactly one argument is passed
if ($args.Length -ne 1) {
    Write-Host "Need a param"
    exit 1
}

# Because of bazel sandboxing we need to tell Windows where to find perl.
$env:PATH = $env:PATH + ";C:\Strawberry\c\bin;C:\Strawberry\perl\site\bin;C:\Strawberry\perl\bin;"

$commands = $args[0]
Write-Host "Running $commands"
# Split the string by commas into an array
$commands_arr = $commands -split ','

foreach ($command in $commands_arr) {
    # Execute the command
    Invoke-Expression $command

    # Split the command by spaces (to access the last word)
    $split_command_arr = $command -split ' '
    $out_file = $split_command_arr[-1]

    # Check if the output file exists
    if (Test-Path $out_file) {
        Write-Host "$out_file exists"
    } else {
        Write-Host "$out_file does not exist, failing"
        exit 1
    }
}

exit 0