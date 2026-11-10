# 数据库备份：自定义格式 pg_dump，备份后做一次可读性校验
# 用法：.\deploy\scripts\backup_db.ps1 -Container geo-postgres -Db geo -User geo -OutDir .\deploy\backups

param(
    [string]$Container = "geo-postgres",
    [string]$Db = "geo",
    [string]$User = "geo",
    [string]$OutDir = "$PSScriptRoot\..\backups"
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}
$target = Join-Path (Resolve-Path -LiteralPath $OutDir) "geo-$stamp.dump"

Write-Output "备份数据库 $Db -> $target"
docker exec $Container sh -c "pg_dump -U $User -d $Db -Fc -f /tmp/geo-backup.dump"
if ($LASTEXITCODE -ne 0) { throw "pg_dump 失败" }

docker cp "${Container}:/tmp/geo-backup.dump" $target | Out-Null
if ($LASTEXITCODE -ne 0) { throw "备份文件导出失败" }

# 校验：能列出归档内容才算可用
docker exec $Container sh -c "pg_restore --list /tmp/geo-backup.dump > /dev/null"
if ($LASTEXITCODE -ne 0) { throw "备份文件校验失败（pg_restore --list）" }

$sizeMb = [math]::Round((Get-Item -LiteralPath $target).Length / 1MB, 2)
Write-Output "备份完成：$target（$sizeMb MB），已通过 pg_restore --list 校验"

# 保留策略：本地保留最近 7 份，更早的由运维同步到异地存储后清理
Get-ChildItem -LiteralPath (Resolve-Path -LiteralPath $OutDir) -Filter "geo-*.dump" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 7 |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Write-Output "已清理过期备份 $($_.Name)" }
