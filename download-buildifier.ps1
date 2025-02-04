# Set strict error handling
$ErrorActionPreference = "Stop"

# Download the binary using Invoke-WebRequest
Invoke-WebRequest -Uri "https://github.com/bazelbuild/buildtools/releases/download/v7.3.1/buildifier-windows-amd64.exe" -OutFile "C:\temp\buildifier.exe"

# Set executable permission (on Windows, this is more about file attributes)
# Note: Windows doesn't have chmod, so this step is skipped on Windows
# If you want to mark the file as executable, you could use the `Unblock-File` cmdlet
Unblock-File -Path "C:\temp\buildifier.exe"