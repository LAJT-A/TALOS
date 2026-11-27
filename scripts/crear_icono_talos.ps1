# Pone el logo de TALOS: cambia el acceso directo del escritorio por uno llamado "TALOS" con su logo,
# y crea otro en el menu Inicio (para poder anclarlo a la barra de tareas).
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat = Join-Path $here 'talos.bat'
$ico = Join-Path (Split-Path -Parent $here) 'talos.ico'
$sh = New-Object -ComObject WScript.Shell
$desk = [Environment]::GetFolderPath('Desktop')
Get-ChildItem -Path $desk -Filter *.lnk | ForEach-Object {
    $old = $sh.CreateShortcut($_.FullName)
    if ($old.TargetPath -like '*talos.bat' -and $_.Name -ne 'TALOS.lnk') {
        Remove-Item $_.FullName
        Write-Host "Quitado el acceso viejo: $($_.Name)"
    }
}
foreach ($dir in @($desk, [Environment]::GetFolderPath('Programs'))) {
    $l = $sh.CreateShortcut((Join-Path $dir 'TALOS.lnk'))
    $l.TargetPath = $bat
    $l.WorkingDirectory = $here
    $l.IconLocation = "$ico,0"
    $l.Description = 'TALOS - asistente de LAJT'
    $l.Save()
}
Start-Process ie4uinit.exe -ArgumentList '-show' -ErrorAction SilentlyContinue
Write-Host 'Listo: TALOS quedo en el escritorio y en el menu Inicio con su logo.'
