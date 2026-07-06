# Автоматическое обновление MikroTik IP списка для Windows PowerShell
# Файл: Update-MikroTikIPList.ps1

param(
    [string]$MikroTikHost = "192.168.1.1",
    [string]$MikroTikUser = "atemirov",
    [string]$MikroTikPassword = "Djqnb{jxe_2021",
    [string]$ListName = "rkn",
    [string]$LogFile = "$PSScriptRoot\mikrotik_update.log",
    [switch]$Force,
    [switch]$TestMode
)

# ==================== КОНФИГУРАЦИЯ ====================

$Config = @{
    ScriptDir = $PSScriptRoot
    PythonScript = Join-Path $PSScriptRoot "mikrotik_advanced.py"
    LockFile = Join-Path $env:TEMP "mikrotik_update.lock"
    MaxLogSize = 10MB
    
    # Настройки уведомлений
    EmailEnabled = $false
    EmailTo = "admin@domain.com"
    EmailFrom = "mikrotik@domain.com"
    EmailSubject = "MikroTik IP List Update"
    SmtpServer = "smtp.domain.com"
    
    TelegramEnabled = $false
    TelegramBotToken = "YOUR_BOT_TOKEN"
    TelegramChatId = "YOUR_CHAT_ID"
}

# ==================== ФУНКЦИИ ====================

function Write-LogMessage {
    param([string]$Message, [string]$Level = "INFO")
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    
    # Вывод в консоль
    switch ($Level) {
        "ERROR" { Write-Host $logEntry -ForegroundColor Red }
        "WARNING" { Write-Host $logEntry -ForegroundColor Yellow }
        "SUCCESS" { Write-Host $logEntry -ForegroundColor Green }
        default { Write-Host $logEntry }
    }
    
    # Запись в файл
    try {
        Add-Content -Path $LogFile -Value $logEntry -Encoding UTF8
        
        # Ротация логов при превышении размера
        if ((Get-Item $LogFile -ErrorAction SilentlyContinue).Length -gt $Config.MaxLogSize) {
            $backupLog = $LogFile -replace '\.log$', "_$(Get-Date -Format 'yyyyMMdd').log"
            Move-Item $LogFile $backupLog -Force
        }
    }
    catch {
        Write-Warning "Не удалось записать в лог: $_"
    }
}

function Test-Dependencies {
    Write-LogMessage "Проверка зависимостей..."
    
    # Проверка Python
    try {
        $pythonVersion = & python --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Python не найден"
        }
        Write-LogMessage "Найден: $pythonVersion"
    }
    catch {
        try {
            $pythonVersion = & python3 --version 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Python3 не найден"
            }
            Write-LogMessage "Найден: $pythonVersion"
            $script:PythonCommand = "python3"
        }
        catch {
            Write-LogMessage "ОШИБКА: Python не установлен или не добавлен в PATH" "ERROR"
            return $false
        }
    }
    
    if (-not $script:PythonCommand) {
        $script:PythonCommand = "python"
    }
    
    # Проверка Python скрипта
    if (-not (Test-Path $Config.PythonScript)) {
        Write-LogMessage "ОШИБКА: Python скрипт не найден: $($Config.PythonScript)" "ERROR"
        return $false
    }
    
    # Проверка Python модулей
    try {
        & $script:PythonCommand -c "import requests, paramiko" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-LogMessage "Устанавливаем недостающие Python модули..." "WARNING"
            & $script:PythonCommand -m pip install requests paramiko
            if ($LASTEXITCODE -ne 0) {
                throw "Не удалось установить модули"
            }
        }
    }
    catch {
        Write-LogMessage "ОШИБКА: Проблемы с Python модулями: $_" "ERROR"
        return $false
    }
    
    Write-LogMessage "Все зависимости проверены" "SUCCESS"
    return $true
}

function Test-ProcessLock {
    if (Test-Path $Config.LockFile) {
        $lockContent = Get-Content $Config.LockFile -ErrorAction SilentlyContinue
        Write-LogMessage "ПРЕДУПРЕЖДЕНИЕ: Найден файл блокировки: $lockContent" "WARNING"
        
        if (-not $Force) {
            return $false
        }
        
        Write-LogMessage "Принудительное удаление блокировки..." "WARNING"
        Remove-Item $Config.LockFile -Force
    }
    return $true
}

function Test-MikroTikConnection {
    Write-LogMessage "Проверка доступности MikroTik $MikroTikHost..."
    
    try {
        $ping = Test-Connection -ComputerName $MikroTikHost -Count 1 -Quiet -ErrorAction Stop
        if ($ping) {
            Write-LogMessage "MikroTik доступен" "SUCCESS"
            return $true
        }
    }
    catch {
        Write-LogMessage "ПРЕДУПРЕЖДЕНИЕ: MikroTik недоступен по ping: $_" "WARNING"
    }
    
    return $false
}

function Send-Notification {
    param([string]$Status, [string]$Message)
    
    # Email уведомления
    if ($Config.EmailEnabled) {
        try {
            $emailParams = @{
                To = $Config.EmailTo
                From = $Config.EmailFrom
                Subject = "$($Config.EmailSubject) - $Status"
                Body = $Message
                SmtpServer = $Config.SmtpServer
            }
            Send-MailMessage @emailParams
            Write-LogMessage "Email уведомление отправлено"
        }
        catch {
            Write-LogMessage "Ошибка отправки email: $_" "WARNING"
        }
    }
    
    # Telegram уведомления
    if ($Config.TelegramEnabled) {
        try {
            $telegramUrl = "https://api.telegram.org/bot$($Config.TelegramBotToken)/sendMessage"
            $telegramBody = @{
                chat_id = $Config.TelegramChatId
                text = "🔄 MikroTik: $Message"
            }
            Invoke-RestMethod -Uri $telegramUrl -Method Post -Body $telegramBody
            Write-LogMessage "Telegram уведомление отправлено"
        }
        catch {
            Write-LogMessage "Ошибка отправки Telegram: $_" "WARNING"
        }
    }
}

function Invoke-MikroTikUpdate {
    Write-LogMessage "=== Запуск обновления MikroTik IP списка ==="
    
    # Проверки
    if (-not (Test-Dependencies)) {
        Send-Notification "FAILED" "Ошибка зависимостей"
        return 1
    }
    
    if (-not (Test-ProcessLock)) {
        return 1
    }
    
    Test-MikroTikConnection | Out-Null
    
    # Создание блокировки
    try {
        Set-Content -Path $Config.LockFile -Value "$(Get-Date) - PID: $PID"
    }
    catch {
        Write-LogMessage "ОШИБКА: Не удалось создать файл блокировки" "ERROR"
        return 1
    }
    
    try {
        Set-Location $Config.ScriptDir
        
        if ($TestMode) {
            Write-LogMessage "ТЕСТОВЫЙ РЕЖИМ: команды не выполняются" "WARNING"
            $arguments = @(
                $Config.PythonScript,
                "--list-name", $ListName
            )
        } else {
            Write-LogMessage "Запуск обновления списка '$ListName'..."
            $arguments = @(
                $Config.PythonScript,
                "--ssh-host", $MikroTikHost,
                "--ssh-user", $MikroTikUser,
                "--ssh-password", $MikroTikPassword,
                "--list-name", $ListName,
                "--clear-existing"
            )
        }
        
        $process = Start-Process -FilePath $script:PythonCommand -ArgumentList $arguments -Wait -PassThru -NoNewWindow -RedirectStandardOutput "$env:TEMP\mikrotik_out.log" -RedirectStandardError "$env:TEMP\mikrotik_err.log"
        
        # Читаем вывод
        if (Test-Path "$env:TEMP\mikrotik_out.log") {
            Get-Content "$env:TEMP\mikrotik_out.log" | ForEach-Object { Write-LogMessage "PYTHON: $_" }
            Remove-Item "$env:TEMP\mikrotik_out.log" -Force
        }
        
        if (Test-Path "$env:TEMP\mikrotik_err.log") {
            Get-Content "$env:TEMP\mikrotik_err.log" | ForEach-Object { Write-LogMessage "PYTHON ERROR: $_" "ERROR" }
            Remove-Item "$env:TEMP\mikrotik_err.log" -Force
        }
        
        $exitCode = $process.ExitCode
        
        if ($exitCode -eq 0) {
            Write-LogMessage "✅ Обновление успешно завершено" "SUCCESS"
            Send-Notification "SUCCESS" "IP список '$ListName' обновлен успешно"
        } else {
            Write-LogMessage "❌ ОШИБКА: Обновление завершилось с кодом $exitCode" "ERROR"
            Send-Notification "FAILED" "Ошибка обновления списка '$ListName' (код: $exitCode)"
        }
        
        return $exitCode
    }
    catch {
        Write-LogMessage "❌ ОШИБКА выполнения: $_" "ERROR"
        Send-Notification "FAILED" "Критическая ошибка: $_"
        return 1
    }
    finally {
        # Удаляем блокировку
        if (Test-Path $Config.LockFile) {
            Remove-Item $Config.LockFile -Force
        }
        Write-LogMessage "=== Завершение обновления ==="
    }
}

# ==================== ОСНОВНОЙ КОД ====================

# Настройка политики выполнения для текущей сессии
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force

# Запуск
$exitCode = Invoke-MikroTikUpdate
exit $exitCode