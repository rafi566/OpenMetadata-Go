$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskResults = Join-Path $taskRoot 'docker\benchmark\results'
$taskRestoreId = [guid]::NewGuid().ToString('N')
$taskLog = Join-Path $taskResults ('private\restore-' + $taskRestoreId + '.log')
$taskCli = (Get-Command docker.exe -ErrorAction Stop).Source
$taskPrefix = @('--host','npipe:////./pipe/dockerDesktopLinuxEngine')

function Invoke-FixtureDocker {
    param([string[]]$CommandArgs)
    $taskOutput = & $taskCli @taskPrefix @CommandArgs 2>&1
    $taskExit = $LASTEXITCODE
    $taskOutput | Add-Content -LiteralPath $taskLog
    if ($taskExit -ne 0) { throw ('Fixture Docker command failed; private log: ' + $taskLog) }
    return $taskOutput
}

$taskLoads = @(& $taskCli @taskPrefix ps --filter 'name=bettermetadata-load-' --format '{{.Names}}')
if ($taskLoads.Count -ne 0) { throw 'A load generator is still running; refusing to reset its fixture.' }
foreach ($taskName in @('bettermetadata-benchmark-api-1','bettermetadata-benchmark-postgres-1','bettermetadata-benchmark-opensearch-1')) {
    $taskProject = Invoke-FixtureDocker -CommandArgs @('inspect',$taskName,'--format','{{index .Config.Labels "com.docker.compose.project"}}')
    if ($taskProject -ne 'bettermetadata-benchmark') { throw ('Unexpected container ownership: ' + $taskName) }
}
$taskDump = Join-Path $taskResults 'private\catalog-v1.dump'
$taskDumpHash = (Get-FileHash -LiteralPath $taskDump -Algorithm SHA256).Hash
if ($taskDumpHash -ne '06B305C857FCEA3F79B04E69435B3AB18D04818103F4C0A61875D352E19CDF5B') {
    throw 'Unexpected PostgreSQL snapshot; refusing to restore it.'
}
$taskSavedSnapshot = (Get-Content -LiteralPath (Join-Path $taskResults 'private\search-snapshot.json') -Raw | ConvertFrom-Json).snapshot
if ($taskSavedSnapshot.snapshot -ne 'catalog-v1' -or $taskSavedSnapshot.state -ne 'SUCCESS' -or !$taskSavedSnapshot.uuid -or $taskSavedSnapshot.indices.Count -lt 1 -or $taskSavedSnapshot.indices.Count -gt 200 -or $taskSavedSnapshot.shards.total -lt 1 -or $taskSavedSnapshot.shards.failed -ne 0 -or $taskSavedSnapshot.shards.successful -ne $taskSavedSnapshot.shards.total) {
    throw 'Saved search snapshot metadata is incomplete or unsuccessful.'
}
$taskAvailableJson = Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-opensearch-1','curl','--silent','--show-error','--fail','http://localhost:9200/_snapshot/benchmark_fixture/catalog-v1')
$taskAvailableSnapshots = @(($taskAvailableJson | ConvertFrom-Json).snapshots)
if ($taskAvailableSnapshots.Count -ne 1) { throw 'The saved search snapshot is unavailable.' }
$taskAvailable = $taskAvailableSnapshots[0]
if ($taskAvailable.uuid -ne $taskSavedSnapshot.uuid -or $taskAvailable.state -ne 'SUCCESS' -or $taskAvailable.shards.failed -ne 0 -or $taskAvailable.shards.successful -ne $taskSavedSnapshot.shards.successful -or ((@($taskAvailable.indices | Sort-Object) -join "`n") -ne (@($taskSavedSnapshot.indices | Sort-Object) -join "`n")) -or ((@($taskAvailable.data_streams | Sort-Object) -join "`n") -ne (@($taskSavedSnapshot.data_streams | Sort-Object) -join "`n"))) {
    throw 'The available search snapshot differs from the saved fixture.'
}
Invoke-FixtureDocker -CommandArgs @('stop','--time','20','bettermetadata-benchmark-api-1') | Out-Null
Invoke-FixtureDocker -CommandArgs @('cp',$taskDump,'bettermetadata-benchmark-postgres-1:/tmp/benchmark-restore.dump') | Out-Null
Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-postgres-1','pg_restore','--list','/tmp/benchmark-restore.dump') | Out-Null
Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-postgres-1','dropdb','-U','benchmark','--maintenance-db=postgres','--force','--if-exists','openmetadata_benchmark') | Out-Null
Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-postgres-1','createdb','-U','benchmark','-O','benchmark','openmetadata_benchmark') | Out-Null
Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-postgres-1','pg_restore','-U','benchmark','-d','openmetadata_benchmark','--exit-on-error','/tmp/benchmark-restore.dump') | Out-Null
$taskStreamsJson = Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-opensearch-1','curl','--silent','--show-error','--fail','http://localhost:9200/_data_stream')
$taskStreams = @((($taskStreamsJson | ConvertFrom-Json).data_streams).name)
if ($taskStreams.Count -gt 100) { throw 'Unexpected local data stream count.' }
foreach ($taskStream in $taskStreams) {
    if ($taskStream) {
        Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-opensearch-1','curl','--silent','--show-error','--fail','-X','DELETE',('http://localhost:9200/_data_stream/' + [Uri]::EscapeDataString($taskStream))) | Out-Null
    }
}
$taskIndicesJson = Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-opensearch-1','curl','--silent','--show-error','--fail','http://localhost:9200/_cat/indices?format=json&h=index&expand_wildcards=all')
$taskIndices = @(($taskIndicesJson | ConvertFrom-Json).index)
if ($taskIndices.Count -lt 1 -or $taskIndices.Count -gt 200) { throw 'Unexpected local index count.' }
for ($taskOffset = 0; $taskOffset -lt $taskIndices.Count; $taskOffset += 20) {
    $taskLast = [Math]::Min($taskOffset + 19, $taskIndices.Count - 1)
    $taskNames = ($taskIndices[$taskOffset..$taskLast] | ForEach-Object { [Uri]::EscapeDataString($_) }) -join ','
    Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-opensearch-1','curl','--silent','--show-error','--fail','-X','DELETE',('http://localhost:9200/' + $taskNames)) | Out-Null
}
$taskSnapshotNames = @($taskSavedSnapshot.indices | Where-Object {-not $_.StartsWith('.ds-')}) + @($taskSavedSnapshot.data_streams)
$taskRestoreBody = @{indices=($taskSnapshotNames -join ',');include_global_state=$false;include_aliases=$true} | ConvertTo-Json -Compress
$taskRestoreJson = $taskRestoreBody | & $taskCli @taskPrefix exec -i bettermetadata-benchmark-opensearch-1 curl --silent --show-error --fail -X POST 'http://localhost:9200/_snapshot/benchmark_fixture/catalog-v1/_restore?wait_for_completion=true' -H 'Content-Type: application/json' --data-binary '@-'
if ($LASTEXITCODE -ne 0) { throw 'Local search snapshot restore failed.' }
$taskRestoreJson | Add-Content -LiteralPath $taskLog
$taskSearchRestore = $taskRestoreJson | ConvertFrom-Json
if ($taskSearchRestore.snapshot.shards.failed -ne 0 -or $taskSearchRestore.snapshot.indices.Count -ne $taskSavedSnapshot.indices.Count -or $taskSearchRestore.snapshot.shards.successful -ne $taskSavedSnapshot.shards.successful) {
    throw 'Search restore did not cover the complete saved snapshot.'
}
Invoke-FixtureDocker -CommandArgs @('exec','bettermetadata-benchmark-opensearch-1','curl','--silent','--show-error','--fail','http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=60s') | Out-Null
Invoke-FixtureDocker -CommandArgs @('start','bettermetadata-benchmark-api-1') | Out-Null
$taskClock = [Diagnostics.Stopwatch]::StartNew()
$taskReady = $false
while ($taskClock.Elapsed.TotalSeconds -lt 60) {
    try {
        $taskVersion = Invoke-RestMethod -Uri 'http://127.0.0.1:18585/api/v1/system/version' -TimeoutSec 2
        if ($taskVersion.revision -eq 'f38e3487c729fe4663269bd367ed9a853fa9d3e6') { $taskReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (!$taskReady) { throw 'The API did not become ready in the observation window.' }
$taskLoginBody = @{email='admin@open-metadata.org';password='YWRtaW4='} | ConvertTo-Json -Compress
$taskLogin = Invoke-RestMethod -Uri 'http://127.0.0.1:18585/api/v1/users/login' -Method Post -ContentType 'application/json' -Body $taskLoginBody -TimeoutSec 15
if (!$taskLogin.accessToken) { throw 'Fresh fixture login failed.' }
[IO.File]::WriteAllText((Join-Path $taskResults 'private\admin-token'),$taskLogin.accessToken,[Text.UTF8Encoding]::new($false))
$taskHeaders = @{Authorization=('Bearer ' + $taskLogin.accessToken)}
$taskCatalog = Invoke-RestMethod -Uri 'http://127.0.0.1:18585/api/v1/tables?limit=1' -Headers $taskHeaders -TimeoutSec 15
if ($taskCatalog.paging.total -ne 10100) { throw 'Restored table count differs.' }
$taskGolden = Get-Content -LiteralPath (Join-Path $taskResults 'environment\sample-detail.json') -Raw | ConvertFrom-Json
$taskTable = Invoke-RestMethod -Uri ('http://127.0.0.1:18585/api/v1/tables/' + $taskGolden.id) -Headers $taskHeaders -TimeoutSec 15
if ($taskTable.version -ne $taskGolden.version -or $taskTable.description -ne $taskGolden.description -or $taskTable.updatedAt -ne $taskGolden.updatedAt) {
    throw 'PostgreSQL fixture contents did not return to the saved state.'
}
$taskQuery = [Uri]::EscapeDataString('fullyQualifiedName:"' + $taskGolden.fullyQualifiedName + '"')
$taskSearch = Invoke-RestMethod -Uri ('http://127.0.0.1:18585/api/v1/search/query?q=' + $taskQuery + '&index=table_search_index&size=5') -Headers $taskHeaders -TimeoutSec 15
$taskHit = @($taskSearch.hits.hits | Where-Object {$_._id -eq $taskGolden.id})
if ($taskHit.Count -ne 1 -or $taskHit[0]._source.description -ne $taskGolden.description -or $taskHit[0]._source.updatedAt -ne $taskGolden.updatedAt) {
    throw 'Search and PostgreSQL fixture snapshots disagree.'
}
$taskEvidence = [pscustomobject]@{
    RestoreId=$taskRestoreId;CompletedUtc=[DateTime]::UtcNow.ToString('o');
    PostgreSQLDumpSha256=$taskDumpHash;Tables=$taskCatalog.paging.total;
    SearchShards=$taskSearchRestore.snapshot.shards.successful;
    TableVersion=$taskTable.version;StoresConsistent=$true;FreshLogin=$true
}
$taskEvidence | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskResults ('private\restore-' + $taskRestoreId + '.json'))
$taskEvidence | ConvertTo-Json
