# Registra no Agendador de Tarefas do Windows a coleta diária do Radar Cordeiro às 08:00.
# Execute uma vez, num PowerShell aberto na pasta do projeto:
#     powershell -ExecutionPolicy Bypass -File scripts\agendar_tarefa_windows.ps1
# Atenção: o Agendador usa o relógio do Windows. Confira se o fuso da máquina é
# "(UTC-03:00) Fortaleza" ou "Brasília" (ambos UTC-3, sem horário de verão).

$ErrorActionPreference = "Stop"
$projeto = Split-Path -Parent $PSScriptRoot
$python  = Join-Path $projeto ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Ambiente virtual não encontrado em $python. Rode a instalação do README primeiro." }

$acao    = New-ScheduledTaskAction -Execute $python -Argument "-m radar.collector --agendado" -WorkingDirectory $projeto
$gatilho = New-ScheduledTaskTrigger -Daily -At "08:00"
# StartWhenAvailable: se o PC estiver desligado às 08:00, roda assim que ligar.
$config  = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "Radar Cordeiro - coleta diaria" -Action $acao -Trigger $gatilho -Settings $config `
    -Description "Coleta de notícias do Radar Cordeiro (Exa + DuckDuckGo)" -Force | Out-Null

Write-Host "Tarefa 'Radar Cordeiro - coleta diaria' registrada para 08:00. Fuso atual do Windows: $((Get-TimeZone).DisplayName)"
