# Наблюдатель за обычным чатом Claude для питомца.
#
# Пока в окне Claude видна кнопка «Stop response» (ответ генерируется), обновляет
# файл-метку; когда кнопки нет — удаляет его. Питомец считает метку действующей,
# только пока она свежая (несколько секунд), так что зависший наблюдатель дугу не «залипнет».
# Работает, только когда чат открыт в окне Claude: в других вкладках кнопки нет.
#
# Запускается питомцем скрыто и завершается сам, когда питомец закрыт.

param(
    [Parameter(Mandatory = $true)][string]$Marker,
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [int]$IntervalMs = 700
)

# Точные названия кнопки остановки ответа в обычном чате, по языкам интерфейса Claude.
# Проверены вживую: английский — 'Stop response', русский — 'Остановить ответ'.
# Кнопку вкладки Code ('Stop' / 'Остановить') не берём: её отслеживают хуки Claude Code.
# Не-ASCII названия задаются Unicode-кодами: PowerShell 5.1 читает .ps1 без BOM
# в кодировке ANSI, и кириллица прямо в строке превратилась бы в «кракозябры».
$StopNames = @(
    'Stop response',
    [regex]::Unescape('\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c\u0020\u043e\u0442\u0432\u0435\u0442')  # Остановить ответ
)

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$scope = [System.Windows.Automation.TreeScope]
$buttonCond = New-Object System.Windows.Automation.PropertyCondition(
    $A::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
$nameConds = foreach ($n in $StopNames) { New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $n) }
$nameCond = if ($nameConds.Count -gt 1) { New-Object System.Windows.Automation.OrCondition($nameConds) } else { $nameConds }
$stopCond = New-Object System.Windows.Automation.AndCondition($buttonCond, $nameCond)

$claudePids = @()
$nextPidScan = [DateTime]::MinValue

function Remove-Marker { if (Test-Path -LiteralPath $Marker) { Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue } }

while ($true) {
    if (-not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) { Remove-Marker; break }
    $busy = $false
    try {
        if ((Get-Date) -ge $nextPidScan) {
            # Только десктоп-приложение Claude; у Claude Code CLI тот же claude.exe, но без окон.
            $claudePids = @(Get-Process claude -ErrorAction SilentlyContinue |
                Where-Object { $_.Path -like '*\WindowsApps\Claude_*' -or $_.Path -like '*\AnthropicClaude\*' } |
                ForEach-Object { $_.Id })
            $nextPidScan = (Get-Date).AddSeconds(10)
        }
        if ($claudePids.Count) {
            foreach ($w in $A::RootElement.FindAll($scope::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
                if ($claudePids -notcontains $w.Current.ProcessId) { continue }
                if ($w.FindFirst($scope::Descendants, $stopCond)) { $busy = $true; break }
            }
        }
    } catch { $busy = $false }

    if ($busy) {
        $dir = Split-Path -Parent $Marker
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        if (Test-Path -LiteralPath $Marker) { (Get-Item -LiteralPath $Marker).LastWriteTime = Get-Date }
        else { New-Item -ItemType File -Path $Marker -Force | Out-Null }
    } else {
        Remove-Marker
    }
    Start-Sleep -Milliseconds $IntervalMs
}
