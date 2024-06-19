@echo off

rem Activate the virtual environment
call venv\Scripts\activate.bat

rem Run the QPAL application
python app.py

rem Pause the script to keep the command prompt window open
pause