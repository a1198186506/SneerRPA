Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"

Name "SneerRPA 工作室"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\SneerRPA"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "SneerRPA 工作室"
VIAddVersionKey "FileDescription" "SneerRPA Windows x64 安装程序"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
Var TestMode
Var WebViewVersion

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\SneerRPA.exe"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "此安装包需要 64 位 Windows。"
    Abort
  ${EndIf}
  SetShellVarContext current
  ${GetParameters} $0
  ${GetOptions} $0 "/TESTMODE" $TestMode
  ${IfNot} ${Errors}
    StrCpy $TestMode "1"
  ${EndIf}
FunctionEnd

Section "SneerRPA"
  ; Detect either a machine-wide or current-user Evergreen WebView2 runtime.
  ReadRegStr $WebViewVersion HKCU "Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  ${If} $WebViewVersion == ""
  ${OrIf} $WebViewVersion == "0.0.0.0"
    SetRegView 32
    ReadRegStr $WebViewVersion HKLM "Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  ${EndIf}
  ${If} $WebViewVersion == ""
  ${OrIf} $WebViewVersion == "0.0.0.0"
    InitPluginsDir
    SetOutPath "$PLUGINSDIR"
    File /oname=WebView2Setup.exe "${WEBVIEW_INSTALLER}"
    DetailPrint "正在安装 WebView2 运行环境…"
    ExecWait '"$PLUGINSDIR\WebView2Setup.exe" /silent /install' $0
    ${If} $0 != 0
      MessageBox MB_ICONSTOP "WebView2 安装失败（$0），请完成运行环境安装后重试。"
      SetErrorLevel 1
      Abort
    ${EndIf}
  ${EndIf}
  SetOutPath "$INSTDIR"
  File /r /x .tmp /x __pycache__ /x neutralinojs.log "${APP_STAGE}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ${If} $TestMode != "1"
    CreateDirectory "$SMPROGRAMS\SneerRPA"
    CreateShortcut "$SMPROGRAMS\SneerRPA\SneerRPA 工作室.lnk" "$INSTDIR\SneerRPA.exe"
    CreateShortcut "$SMPROGRAMS\SneerRPA\卸载 SneerRPA.lnk" "$INSTDIR\Uninstall.exe"
    CreateShortcut "$DESKTOP\SneerRPA 工作室.lnk" "$INSTDIR\SneerRPA.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA" "DisplayName" "SneerRPA 工作室"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA" "DisplayIcon" "$INSTDIR\SneerRPA.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA" "NoRepair" 1
  ${Else}
    FileOpen $0 "$INSTDIR\.installer-test" w
    FileClose $0
  ${EndIf}
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  IfFileExists "$INSTDIR\.installer-test" skipIntegration
    Delete "$DESKTOP\SneerRPA 工作室.lnk"
    Delete "$SMPROGRAMS\SneerRPA\SneerRPA 工作室.lnk"
    Delete "$SMPROGRAMS\SneerRPA\卸载 SneerRPA.lnk"
    RMDir "$SMPROGRAMS\SneerRPA"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SneerRPA"
  skipIntegration:
  ; Only remove known application-owned paths. Never remove user project data.
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\extensions"
  RMDir /r "$INSTDIR\resources"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\.tmp"
  Delete "$INSTDIR\SneerRPA.exe"
  Delete "$INSTDIR\resources.neu"
  Delete "$INSTDIR\installed.json"
  Delete "$INSTDIR\使用说明.txt"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\neutralinojs.log"
  Delete "$INSTDIR\.installer-test"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
