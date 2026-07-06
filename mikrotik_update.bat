@echo off
:: Автоматическое обновление MikroTik IP списка для Windows
:: Файл: mikrotik_update.bat

setlocal EnableDelayedExpansion

:: ==================== КОНФИГУРАЦИЯ ====================
set MIKROTIK_HOST=192.168.1.1
set MIKROTIK_USER=atemirov
set MIKROTIK_PASSWORD=Djqnb{jxe_2021
set LIST_NAME=rkn

:: Пути к файлам
set SCRIPT_DIR=G:\mikrotik\update_ip_lists\
set PYTHON_SCRIPT=%SCRIPT_DIR%mikrotik_advanced_loader.py
set LOG_FILE=%SCRIPT_DIR%mikrotik_update.log
set LOCK_FILE=%SCRIPT_DIR%mikrotik_update.lock

:: Python путь (автоопределение)
set PYTHON_PATH=python
for /f "delims=" %%i in ('where python 2^>nul') do set PYTHON_PATH=%%i
if "!PYTHON_PATH!"=="" (
    for /f "delims=" %%i in ('where python3 2^>nul') do set PYTHON_PATH=%%i
)

:: ==================== ФУНКЦИИ ====================

:log_message
echo [%date% %time%] %~1 >> "%LOG_FILE%"
echo [%date% %time%] %~1
goto :eof

:check_dependencies
call :log_message "Проверка зависимостей..."
:: Проверяем Python
"!PYTHON_PATH!" --version >nul 2>&1
if errorlevel 1 (
    call :log_message "ОШИБКА: Python не найден. Установите Python и добавьте в PATH"
    exit /b 1
)

:: Проверяем существование Python скрипта
if not exist "!PYTHON_SCRIPT!" (
    call :log_message "ОШИБКА: Python скрипт не найден: !PYTHON_SCRIPT!"
    exit /b 1
)

:: Проверяем Python модули
"!PYTHON_PATH!" -c "import requests, paramiko" >nul 2>&1
if errorlevel 1 (
    call :log_message "Установка модулей requests и paramiko..."
    "!PYTHON_PATH!" -m pip install requests paramiko
    if errorlevel 1 (
        call :log_message "ОШИБКА: Не удалось установить модули"
        exit /b 1
    )
)
call :log_message "Зависимости проверены успешно"
goto :eof

:check_lock
if exist "!LOCK_FILE!" (
    call :log_message "ОШИБКА: Процесс уже запущен (найден lock-файл: !LOCK_FILE!)"
    exit /b 1
)
goto :eof

:ping_mikrotik
ping -n 1 -w 5000 %MIKROTIK_HOST% >nul 2>&1
if errorlevel 1 (
    call :log_message "ПРЕДУПРЕЖДЕНИЕ: MikroTik %MIKROTIK_HOST% недоступен по ping"
    exit /b 1
)
call :log_message "MikroTik %MIKROTIK_HOST% доступен"
goto :eof

:send_notification
:: Функция для отправки уведомлений
:: %1 - статус (SUCCESS/FAILED)
:: %2 - сообщение
call :log_message "Уведомление: %~1 - %~2"
:: Пример Telegram уведомления (раскомментируйте и настройте)
:: set BOT_TOKEN=YOUR_BOT_TOKEN
:: set CHAT_ID=YOUR_CHAT_ID
:: curl -s -X POST "https://api.telegram.org/bot%BOT_TOKEN%/sendMessage" -d "chat_id=%CHAT_ID%" -d "text=MikroTik: %~2"
goto :eof

:: ==================== ОСНОВНАЯ ЛОГИКА ====================

:main
call :log_message "=== Запуск обновления MikroTik IP списка ==="

:: Проверки
call :check_dependencies
if errorlevel 1 (
    call :send_notification "FAILED" "Ошибка зависимостей"
    exit /b 1
)

call :check_lock
if errorlevel 1 (
    call :send_notification "FAILED" "Процесс уже запущен"
    exit /b 1
)

call :ping_mikrotik
if errorlevel 1 (
    call :send_notification "FAILED" "MikroTik недоступен"
    exit /b 1
)

:: Создаем блокировку
echo %date% %time% > "!LOCK_FILE!"

:: Запускаем обновление
call :log_message "Запуск Python скрипта: !PYTHON_SCRIPT!"
cd /d "!SCRIPT_DIR!"
"!PYTHON_PATH!" "!PYTHON_SCRIPT!" --ssh-host %MIKROTIK_HOST% --ssh-user %MIKROTIK_USER% --ssh-password "%MIKROTIK_PASSWORD%" --list-name %LIST_NAME% --clear-existing > "%SCRIPT_DIR%python_output.log" 2>&1
set RESULT=%ERRORLEVEL%

:: Удаляем блокировку
if exist "!LOCK_FILE!" del "!LOCK_FILE!"

:: Проверяем результат
if %RESULT%==0 (
    call :log_message "✅ Обновление успешно завершено"
    call :send_notification "SUCCESS" "IP список обновлен успешно"
) else (
    call :log_message "❌ ОШИБКА: Обновление завершилось с кодом %RESULT%"
    call :log_message "Вывод Python: see %SCRIPT_DIR%python_output.log"
    call :send_notification "FAILED" "Ошибка обновления (код: %RESULT%)"
)

call :log_message "=== Завершение обновления ==="
call :log_message ""

exit /b %RESULT%

:: ==================== ЗАПУСК ====================

if "%1"=="--edit-config" (
    echo Отредактируйте переменные в начале этого файла:
    echo MIKROTIK_HOST, MIKROTIK_USER, MIKROTIK_PASSWORD
    pause
    exit /b 0
)

call :main %*