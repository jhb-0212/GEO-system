# 备份恢复演练：把备份还原到临时库，逐表比对行数后删除临时库，不碰生产库
# 用法：.\deploy\scripts\restore_drill.ps1 -BackupFile .\deploy\backups\geo-20261110-180000.dump

param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [string]$Container = "geo-postgres",
    [string]$SourceDb = "geo",
    [string]$DrillDb = "geo_restore_drill",
    [string]$User = "geo",
    [switch]$KeepDrillDb
)

$ErrorActionPreference = "Stop"
$backup = (Resolve-Path -LiteralPath $BackupFile).Path

Write-Output "1) 上传备份到容器"
docker cp $backup "${Container}:/tmp/drill.dump" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "备份文件上传失败" }

Write-Output "2) 重建临时库 $DrillDb"
docker exec $Container sh -c "psql -U $User -d postgres -c 'DROP DATABASE IF EXISTS $DrillDb;' -c 'CREATE DATABASE $DrillDb;'" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "创建临时库失败" }

Write-Output "3) 还原到临时库"
docker exec $Container sh -c "pg_restore -U $User -d $DrillDb --no-owner --no-privileges /tmp/drill.dump"
if ($LASTEXITCODE -ne 0) { throw "pg_restore 失败" }

Write-Output "4) 行数与结构比对（源库 vs 临时库）"
$compareSql = @"
select 'tables' as metric,
       (select count(*) from information_schema.tables where table_schema='public') as v
union all select 'roles', (select count(*) from roles)
union all select 'projects', (select count(*) from projects)
union all select 'channels', (select count(*) from channels)
union all select 'questions', (select count(*) from questions)
union all select 'metric_definitions', (select count(*) from metric_definitions)
order by metric;
"@
$tmp = Join-Path $env:TEMP "drill-compare.sql"
Set-Content -LiteralPath $tmp -Value $compareSql -Encoding utf8
docker cp $tmp "${Container}:/tmp/compare.sql" | Out-Null

Write-Output "--- 源库 $SourceDb ---"
docker exec $Container psql -U $User -d $SourceDb -f /tmp/compare.sql
Write-Output "--- 还原库 $DrillDb ---"
docker exec $Container psql -U $User -d $DrillDb -f /tmp/compare.sql

if (-not $KeepDrillDb) {
    Write-Output "5) 清理临时库"
    docker exec $Container sh -c "psql -U $User -d postgres -c 'DROP DATABASE IF EXISTS $DrillDb;'" | Out-Null
    Write-Output "演练临时库已删除，源库未受影响"
} else {
    Write-Output "已保留临时库 $DrillDb 供检查"
}
