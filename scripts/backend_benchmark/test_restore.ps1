$ErrorActionPreference = 'Stop'
$taskRestoreScript = Join-Path $PSScriptRoot 'restore.ps1'
foreach ($taskCase in @('missing', 'malformed', 'unavailable', 'foreign-gateway', 'failed-load-inventory', 'failed-gateway-inventory')) {
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
            if ($args -contains 'ps') {
                if (($taskCase -eq 'failed-gateway-inventory' -and $args -contains '--all') -or ($taskCase -eq 'failed-load-inventory' -and $args -notcontains '--all')) { $global:LASTEXITCODE = 125; return }
                if ($taskCase -eq 'foreign-gateway' -and $args -contains '--all') { return 'bettermetadata-benchmark-gateway-1' }
                return
            }
            if ($args -contains 'inspect') {
                if ($taskCase -eq 'foreign-gateway' -and $args -contains 'bettermetadata-benchmark-gateway-1') { return 'another-project' }
                return 'bettermetadata-benchmark'
            }
            if (($args -join ' ') -match '/_snapshot/benchmark_fixture/catalog-v1$') {
                $global:LASTEXITCODE = 22
                return 'Snapshot is unavailable'
            }
            throw 'A mutating Docker command was attempted'
        }
        $taskRejected = $false
        $taskRejection = ''
        try { & $taskRestoreScript } catch { $taskRejected = $true; $taskRejection = $_.Exception.Message }
        if ($taskCase -eq 'foreign-gateway' -and $taskRejection -notlike 'Unexpected container ownership:*') { throw 'Foreign gateway was not rejected by the ownership guard.' }
        if ($taskCase -like 'failed-*-inventory' -and ($taskCalls[-1] -notmatch ' ps ' -or $taskRejection -notlike 'Fixture Docker command failed;*')) { throw ('Restore continued after inventory failed: ' + $taskCase) }
        if (!$taskRejected -or @($taskCalls | Where-Object {$_ -match ' stop |dropdb|createdb|pg_restore|DELETE'}).Count) {
            throw ('Unsafe restore preflight for ' + $taskCase + ': ' + ($taskCalls -join '; '))
        }
        Write-Output ('PASS: ' + $taskCase + ' preflight prevents fixture mutations')
    }
}
