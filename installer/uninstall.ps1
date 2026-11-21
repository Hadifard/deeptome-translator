# =====================================================================================================================
#  File    : uninstall.ps1
#  Author  : Hadi Sarhangi Fard
#  Date    : 2026-11-19   (DeepTome Translator 3.4)
#  Purpose : Removes DeepTome Translator: program folder, shortcuts and the entry in Windows "Apps"; on request
#            also the downloaded models and settings.  Translations made by the user are never touched.
#  Copyright (c) 2026 Hadi Sarhangi Fard. All rights reserved.
# =====================================================================================================================
Add-Type -AssemblyName PresentationFramework
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $dir "app\book_translator.py"))) {
    [void][Windows.MessageBox]::Show("This folder does not look like a DeepTome installation:`n$dir", "DeepTome Translator")
    exit 1
}
if ([Windows.MessageBox]::Show("Remove DeepTome Translator from this computer?`n`n$dir", "DeepTome Translator", "YesNo", "Question") -ne "Yes") { exit 0 }
$data = Join-Path $env:USERPROFILE ".pdf_book_translator"
$alsoData = $false
if (Test-Path $data) {
    $alsoData = ([Windows.MessageBox]::Show("Also delete the downloaded translation models, fonts and your settings?`n`n$data`n`nNo = keep them (a later installation does not have to download the models again).", "DeepTome Translator", "YesNo", "Question") -eq "Yes")
}
foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath("Desktop")) "DeepTome Translator.lnk"),
                   (Join-Path ([Environment]::GetFolderPath("Programs")) "DeepTome Translator.lnk"))) {
    Remove-Item $lnk -Force -ErrorAction SilentlyContinue
}
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepTomeTranslator" -Recurse -Force -ErrorAction SilentlyContinue
if ($alsoData) { Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue }
# the folder contains this script: delete it from a separate process after this one has ended
$cmd = "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$dir' -Recurse -Force -ErrorAction SilentlyContinue"
Start-Process powershell.exe -ArgumentList "-NoProfile -WindowStyle Hidden -Command `"$cmd`"" -WindowStyle Hidden
[void][Windows.MessageBox]::Show("DeepTome Translator was removed.`n`nOllama (if you installed it) is a separate program: remove it in Windows Settings > Apps.", "DeepTome Translator")
