param(
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [string]$HostName = "localhost",
    [int]$Port = 9090
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Root)) {
    Write-Host "[ERROR] Public root not found: $Root"
    exit 1
}

$rootPath = (Resolve-Path -LiteralPath $Root).Path
$prefix = "http://$HostName`:$Port/"
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add($prefix)

function Get-ContentType([string]$path) {
    switch ([System.IO.Path]::GetExtension($path).ToLowerInvariant()) {
        ".html" { "text/html; charset=utf-8" }
        ".css" { "text/css; charset=utf-8" }
        ".js" { "application/javascript; charset=utf-8" }
        ".json" { "application/json; charset=utf-8" }
        ".svg" { "image/svg+xml" }
        ".png" { "image/png" }
        ".jpg" { "image/jpeg" }
        ".jpeg" { "image/jpeg" }
        ".webp" { "image/webp" }
        ".ico" { "image/x-icon" }
        ".txt" { "text/plain; charset=utf-8" }
        default { "application/octet-stream" }
    }
}

try {
    $listener.Start()
    Write-Host "Serving $rootPath at $prefix"
    Write-Host "Press Ctrl+C to stop."

    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $requestPath = [System.Uri]::UnescapeDataString($context.Request.Url.AbsolutePath.TrimStart('/'))
        if ([string]::IsNullOrWhiteSpace($requestPath)) {
            $requestPath = "index.html"
        }

        $relativePath = $requestPath -replace '/', '\'
        $candidate = Join-Path $rootPath $relativePath
        $fullPath = [System.IO.Path]::GetFullPath($candidate)

        if (-not $fullPath.StartsWith($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            $context.Response.StatusCode = 403
            $context.Response.Close()
            continue
        }

        if ((Test-Path -LiteralPath $fullPath) -and -not (Get-Item -LiteralPath $fullPath).PSIsContainer) {
            $bytes = [System.IO.File]::ReadAllBytes($fullPath)
            $context.Response.ContentType = Get-ContentType $fullPath
            $context.Response.ContentLength64 = $bytes.LongLength
            $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
            $context.Response.OutputStream.Close()
            continue
        }

        $context.Response.StatusCode = 404
        $fallback404 = Join-Path $rootPath "404.html"
        if (Test-Path -LiteralPath $fallback404) {
            $bytes404 = [System.IO.File]::ReadAllBytes($fallback404)
            $context.Response.ContentType = "text/html; charset=utf-8"
            $context.Response.ContentLength64 = $bytes404.LongLength
            $context.Response.OutputStream.Write($bytes404, 0, $bytes404.Length)
        }
        $context.Response.OutputStream.Close()
    }
}
catch {
    Write-Host "[ERROR] Failed to start static server: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($listener.IsListening) {
        $listener.Stop()
    }
    $listener.Close()
}
