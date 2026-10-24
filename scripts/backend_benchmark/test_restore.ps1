$ErrorActionPreference = 'Stop'
$taskRestoreScript = Join-Path $PSScriptRoot 'restore.ps1'
foreach ($taskCase in @('missing', 'malformed', 'unavailable')) {
    & {
        $taskCalls = [Collections.Generic.List[string]]::new()
        function Get-Command {
            [CmdletBinding()]
            param([string]$Name)
            if ($Name -ne 'docker.exe') { throw 'Unexpected command lookup' }
            [pscustomobject]@{Source='Invoke-FakeDocker'}
        }
        function Get-FileHash {
            [CmdletBinding()]
            param([string]$LiteralPath, [string]$Algorithm)
            [pscustomobject]@{Hash='06B305C857FCEA3F79B04E69435B3AB18D04818103F4C0A61875D352E19CDF5B'}
        }
        function Get-Content {
            [CmdletBinding()]
            param([string]$LiteralPath, [switch]$Raw)
            if (!$LiteralPath.EndsWith('search-snapshot.json')) { throw 'Unexpected file read' }
            if ($taskCase -eq 'missing') { throw 'Fixture metadata is missing' }
            if ($taskCase -eq 'malformed') { return '{' }
            '{"snapshot":{"snapshot":"catalog-v1","state":"SUCCESS","uuid":"saved-snapshot","indices":["table"],"data_streams":[],"shards":{"total":1,"successful":1,"failed":0}}}'
        }
        function Add-Content {
            [CmdletBinding()]
            param([string]$LiteralPath, [Parameter(ValueFromPipeline)]$Value)
            process {}
        }
        function Invoke-FakeDocker {
            $taskCalls.Add(($args -join ' '))
            $global:LASTEXITCODE = 0
            if ($args -contains 'ps') { return }
            if ($args -contains 'inspect') { return 'bettermetadata-benchmark' }
            if (($args -join ' ') -match '/_snapshot/benchmark_fixture/catalog-v1$') {
                $global:LASTEXITCODE = 22
                return 'Snapshot is unavailable'
            }
            throw 'A mutating Docker command was attempted'
        }
        $taskRejected = $false
        try { & $taskRestoreScript } catch { $taskRejected = $true }
        if (!$taskRejected -or @($taskCalls | Where-Object {$_ -match ' stop |dropdb|createdb|pg_restore|DELETE'}).Count) {
            throw ('Unsafe restore preflight for ' + $taskCase + ': ' + ($taskCalls -join '; '))
        }
        Write-Output ('PASS: ' + $taskCase + ' search snapshot prevents fixture mutations')
    }
}
