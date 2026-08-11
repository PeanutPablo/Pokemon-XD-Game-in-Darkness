@echo off
setlocal
set "PROJECT=C:\Users\psych\Documents\My Games\pokemon xg accessibility\PokemonXGAccessibility"
set "DOLPHIN=C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64\Dolphin.exe"
set "GAME=C:\Users\psych\OneDrive\Desktop\apps\Dolphin-x64\Pokemon XD - Gale of Darkness (USA).rvz"
set "PYTHON=C:\Users\psych\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
set "PYTHONPATH=%PROJECT%\Companion;%PROJECT%\Companion\.venv\Lib\site-packages"

start "" /min "%PYTHON%" "%PROJECT%\Companion\run_accessible_pokemon_xd.py"
start "" "%DOLPHIN%" -b -e "%GAME%"
endlocal
