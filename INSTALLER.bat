@echo off

rem Create ay virtual environment
python -m venv venv

rem Activate the virtual environment
call venv\Scripts\activate.bat

rem Install packages from requirements.txt
pip install -r requirements.txt

echo Installation complete!

rem Ask the user if they want to run QPAL
set /p run_qpal="Do you want to run QPAL? (y/n): "

if /i "%run_qpal%"=="y" (
    echo Running QPAL...
    python app.py
) else (
    echo Returning to the virtual environment...
    cmd /k
)

pause
