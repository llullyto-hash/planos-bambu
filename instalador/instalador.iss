; Instalador de Windows (Inno Setup 6). Lo compila .github/workflows/instalador-windows.yml
#define Nombre "Topografia - Polilineas y Metrados"
#define Version GetEnv("VERSION_APP")
#if Version == ""
  #define Version "1.0.0"
#endif

[Setup]
AppId={{8C6E5B0A-3F1D-4C7E-9A52-5B0E1D7A2C11}
AppName={#Nombre}
AppVersion={#Version}
AppPublisher=planos-bambu
DefaultDirName={localappdata}\Programs\TopografiaMetrados
DefaultGroupName={#Nombre}
PrivilegesRequired=lowest
OutputDir=..\dist_instalador
OutputBaseFilename=Instalar_TopografiaMetrados
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\TopografiaMetrados.exe

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\TopografiaMetrados\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#Nombre}"; Filename: "{app}\TopografiaMetrados.exe"
Name: "{group}\Desinstalar"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nombre}"; Filename: "{app}\TopografiaMetrados.exe"; Tasks: escritorio

[Run]
Filename: "{app}\TopografiaMetrados.exe"; Description: "Abrir el programa ahora"; Flags: nowait postinstall skipifsilent
