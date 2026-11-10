param(
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [string]$Compiler = 'C:\msys64\mingw64\bin\gcc.exe',
    [string]$Sdk = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8'
)
$ErrorActionPreference = 'Stop'
$taskCompiler = (Resolve-Path -LiteralPath $Compiler).Path
$taskInclude = Join-Path $Sdk 'include'
$taskImportLib = Join-Path $Sdk 'lib\x64\OpenCL.lib'
if (-not (Test-Path -LiteralPath $taskImportLib)) { throw 'OpenCL x64 import library missing' }
$taskOutput = [System.IO.Path]::GetFullPath($OutputPath)
New-Item -ItemType Directory -Force -Path (Split-Path $taskOutput) | Out-Null
$taskOldPath = $env:PATH
try {
    $env:PATH = (Split-Path $taskCompiler) + ';' + $taskOldPath
    & $taskCompiler -O3 -shared -static-libgcc '-Wl,--no-insert-timestamp' "-I$taskInclude" `
        -o $taskOutput (Join-Path $PSScriptRoot 'bch_hashscan_opencl.c') $taskImportLib
    if ($LASTEXITCODE -ne 0) { throw "GCC failed: $LASTEXITCODE" }
} finally { $env:PATH = $taskOldPath }
Get-FileHash -LiteralPath $taskOutput -Algorithm SHA256
