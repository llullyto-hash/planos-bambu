param([string]$Src)
$ErrorActionPreference = 'Stop'
try {
  $Dest = Join-Path $env:LOCALAPPDATA 'ZenSecciones'
  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  foreach ($f in 'ZenSecciones.html','ZenSecciones.ico','Desinstalar.cmd') { Copy-Item -Force -Path (Join-Path $Src $f) -Destination $Dest }

  # Codigo de equipo (a partir del identificador de Windows de esta PC)
  $guid = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid).MachineGuid
  $sha  = [System.Security.Cryptography.SHA256]::Create()
  $h    = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes('ZENSEC-' + $guid))
  $hex  = ($h | ForEach-Object { $_.ToString('X2') }) -join ''
  $code = $hex.Substring(0,4) + '-' + $hex.Substring(4,4) + '-' + $hex.Substring(8,4)

  # Navegador: Microsoft Edge (viene con Windows); si no, Google Chrome
  function Get-AppPath([string]$exe) {
    foreach ($root in 'HKLM:','HKCU:') {
      $k = "$root\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe"
      if (Test-Path $k) { $v = (Get-ItemProperty -Path $k).'(default)'; if ($v -and (Test-Path $v)) { return $v } }
    }
    return $null
  }
  $br = Get-AppPath 'msedge.exe'
  if (-not $br) {
    foreach ($p in @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")) { if (Test-Path $p) { $br = $p; break } }
  }
  if (-not $br) { $br = Get-AppPath 'chrome.exe' }
  if (-not $br) { Write-Host 'No se encontro Microsoft Edge ni Google Chrome en este equipo.'; exit 1 }

  $url  = 'file:///' + (($Dest -replace '\\','/') -replace ' ','%20') + '/ZenSecciones.html#m=' + $code
  $argv = "--app=`"$url`" --user-data-dir=`"$Dest\perfil`" --no-first-run --no-default-browser-check"

  $ws = New-Object -ComObject WScript.Shell
  $links = @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Zen Secciones.lnk'), (Join-Path ([Environment]::GetFolderPath('Programs')) 'Zen Secciones.lnk'))
  foreach ($lnk in $links) {
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = $br
    $s.Arguments = $argv
    $s.IconLocation = "$Dest\ZenSecciones.ico,0"
    $s.WorkingDirectory = $Dest
    $s.Description = 'Zen Secciones'
    $s.Save()
  }
  Set-Content -Path (Join-Path $Dest 'codigo_equipo.txt') -Value $code
  Write-Host ''
  Write-Host ('  Codigo de equipo:  ' + $code)
  Write-Host ''
  Start-Process -FilePath $br -ArgumentList $argv
  exit 0
} catch {
  Write-Host ('Error: ' + $_.Exception.Message)
  exit 1
}
