# Start Neo4j if not already running, then launch the codegraph MCP server
$ErrorActionPreference = "SilentlyContinue"

# Check if Neo4j is responding
$neo4jUp = $false
try {
    $response = Invoke-RestMethod -Uri "http://localhost:7474" -TimeoutSec 2 -UseBasicParsing 2>$null
    $neo4jUp = $true
} catch {}

if (-not $neo4jUp) {
    Write-Error "Starting Neo4j via docker compose..."
    docker compose up -d neo4j 2>&1 | Write-Host

    # Wait for Neo4j to be healthy (up to 30s)
    $attempts = 0
    while ($attempts -lt 15) {
        Start-Sleep -Seconds 2
        try {
            Invoke-RestMethod -Uri "http://localhost:7474" -TimeoutSec 2 -UseBasicParsing 2>$null
            Write-Error "Neo4j is ready."
            break
        } catch {}
        $attempts++
    }
    if ($attempts -ge 15) {
        Write-Error "WARNING: Neo4j may not be ready yet, proceeding anyway..."
    }
}

# Launch the actual MCP server
& "C:\Users\Jedediah\.local\bin\uvx.exe" --with neo4j codegraphcontext mcp start
