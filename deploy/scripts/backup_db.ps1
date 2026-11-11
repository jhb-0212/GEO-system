# 数据库备份：自定义格式 pg_dump，备份后做一次可读性校验
# 用法：
#   开发：.\deploy\scripts\backup_db.ps1
#   生产：.\deploy\scripts\backup_db.ps1 -AppEnv prod
#         （或显式指定：-Container geo-prod-postgres-1）
# 容器名解析：显式 -Container 优先；否则按 -AppEnv（默认读环境变量 APP_ENV）。
#   prod -> geo-prod-postgres-1；dev/local/test/未设置 -> geo-postgres；其余值直接报错，不猜。

param(
    [string]$Container,
    [string]$AppEnv = $env:APP_ENV,
    [string]$Db = "geo",
    [string]$User = "geo",
    [string]$OutDir = "$PSScriptRoot\..\backups"
)

$ErrorActionPreference = "Stop"

$envKey = ""
if ($AppEnv) { $envKey = $AppEnv.Trim().ToLower() }
$envLabel = "未设置"
if ($envKey) { $envLabel = $envKey }

if (-not $Container) {
    if ($envKey -eq "prod") {
        $Container = "geo-prod-postgres-1"
    } elseif ($envKey -eq "" -or $envKey -eq "dev" -or $envKey -eq "local" -or $envKey -eq "test") {
        $Container = "geo-postgres"
    } else {
        throw "APP_ENV=$AppEnv 无法确定数据库容器；请显式传 -Container（生产为 geo-prod-postgres-1）"
    }
}

# 前置校验：容器必须存在且运行中，避免对着错误的容器做"成功"的备份
$running = ""
$inspectCode = 0
try {
    $running = docker inspect --format "{{.State.Running}}" $Container 2>$null
    $inspectCode = $LASTEXITCODE
} catch {
    $inspectCode = 1
}
if ($inspectCode -ne 0 -or "$running".Trim() -ne "true") {
    $names = docker ps --format "{{.Names}}"
    throw "容器 $Container 不存在或未运行。生产请传 -AppEnv prod（geo-prod-postgres-1）或显式 -Container；当前运行中的容器：$names"
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}
$target = Join-Path (Resolve-Path -LiteralPath $OutDir) "geo-$stamp.dump"

Write-Output "备份数据库 $Db -> $target（容器 $Container，APP_ENV=$envLabel）"
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