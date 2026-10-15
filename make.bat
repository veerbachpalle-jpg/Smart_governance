@echo off
if exist "C:\MinGW\bin\mingw32-make.exe" (
    C:\MinGW\bin\mingw32-make.exe %*
) else (
    if "%1"=="eval" (
        python -m app.modules.evaluation.cli --provider mock
    ) else if "%1"=="test" (
        pytest -v
    ) else if "%1"=="migrate" (
        alembic upgrade head
    ) else if "%1"=="seed" (
        python -m app.db.seed
    ) else (
        echo Unknown target %1
    )
)
