@echo off
cd /d "%~dp0"
if exist dist\Seekframe.exe del /f /q dist\Seekframe.exe
python -m pip install --upgrade pyinstaller playwright tkinterdnd2 sv-ttk darkdetect tzdata
python -m PyInstaller --onefile --noconsole --collect-all tkinterdnd2 --collect-all playwright --collect-all sv_ttk --hidden-import darkdetect --collect-data tzdata --icon assets\shadow.ico --add-data "assets\shadow.ico;assets" --add-data "assets\shadow_studio.png;assets" --add-data "assets\ai_template.html;assets" --add-data "locales;locales" --add-data "tools\narrate\captions.js;tools\narrate" --add-data "tools\narrate\wrap_tail.js;tools\narrate" --add-data "tools\blender\shadow_blender_job.py;tools\blender" --hidden-import blender_core --paths tools\narrate --hidden-import make_narrated_scene --name Seekframe app.py
echo.
if exist dist\Seekframe.exe (echo Built: dist\Seekframe.exe) else (echo BUILD FAILED)
pause
