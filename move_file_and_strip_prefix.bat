@echo off
setlocal EnableDelayedExpansion

REM Check if exactly 3 arguments are provided
if "%~3"=="" (
    echo Usage: %~nx0 dest_dir file prefix >&2
    exit /b 1
)
if not "%~4"=="" (
    echo Usage: %~nx0 dest_dir file prefix >&2
    exit /b 1
)

set "dest_dir=%~1"
set "file=%~2"
set "prefix=%~3"

REM Remove prefix from file path (equivalent to ${file##$prefix})
set "clean_filepath=!file:%prefix%=!"

REM Get directory name (equivalent to dirname) - extract relative directory path only
for %%F in ("!clean_filepath!") do (
    set "clean_dirname=%%~pF"
    REM Remove drive letter and leading slash if present
    set "clean_dirname=!clean_dirname:~1!"
    REM Remove trailing backslash if present
    if "!clean_dirname:~-1!"=="\" set "clean_dirname=!clean_dirname:~0,-1!"
)

REM Create directory structure (equivalent to mkdir -p)
if not exist "%dest_dir%\!clean_dirname!" (
    mkdir "%dest_dir%\!clean_dirname!" 2>nul
)

REM Copy file (equivalent to cp -RL, xcopy follows symlinks by default)
xcopy "!file!" "%dest_dir%\!clean_dirname!\" /Y /Q >nul
