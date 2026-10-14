@echo off
rem Builds OpenFinance.exe with the C# compiler that ships with Windows. No SDK to install.
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /warnaserror /optimize+ ^
  /target:winexe /r:System.Windows.Forms.dll ^
  /out:"%~dp0OpenFinance.exe" "%~dp0Launcher.cs"
