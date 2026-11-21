# =====================================================================================================================
#  File    : install.ps1
#  Author  : Hadi Sarhangi Fard
#  Date    : 2026-11-19   (DeepTome Translator 3.4)
#  Purpose : The Windows setup program (WPF window).  Installs a private Python 3.12, the Python packages, the
#            translation engines the user ticks (built-in MADLAD-400, Ollama + Gemma), the shortcuts and the entry
#            in Windows "Apps".  Downloads are resumable; no administrator rights are needed.
#  Copyright (c) 2026 Hadi Sarhangi Fard. All rights reserved.
# =====================================================================================================================
param(
    [string]$InstallDir = "",
    [switch]$DryRun,            # show the window and play the steps without downloading / installing anything
    [switch]$NoShortcuts,       # test: no desktop / start menu shortcut, no entry in "Apps"
    [string]$Auto = "",         # test: start at once with these engines ("none", "builtin", "ollama", "all") and close
    [string]$Shot = ""          # test: save pictures of the window as <Shot>-1.png, -2.png, -3.png
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms

$AppName   = "DeepTome Translator"
$Here      = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\DeepTome" }

# ---- what is downloaded (sizes measured on 2026-11-16; the window shows them before anything starts)
$PythonUrl   = "https://github.com/astral-sh/python-build-standalone/releases/download/20250409/cpython-3.12.10+20250409-x86_64-pc-windows-msvc-install_only.tar.gz"
$OllamaUrl   = "https://ollama.com/download/OllamaSetup.exe"
$OllamaModel = "gemma3:4b"
$MB = 1024 * 1024
$Size = @{
    Python  = 41960587        # private Python 3.12 with Tk
    Pip     = 288719173       # 54 packages (PyMuPDF, CTranslate2, transformers, torch ...)
    Madlad  = 11782645567     # google/madlad400-3b-mt (original files; converted once to 2.8 GB)
    Ollama  = 1857663944      # OllamaSetup.exe
    Gemma   = 3350272259      # gemma3:4b
    Voices  = 330000000       # offline voices: Piper engine + one voice for each of the 5 languages
}
function Fmt([double]$b) { if ($b -ge 1e9) { "{0:N2} GB" -f ($b / 1e9) } else { "{0:N0} MB" -f ($b / 1e6) } }

[xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="DeepTome Translator - Setup" Width="820" Height="640" ResizeMode="CanMinimize"
        WindowStartupLocation="CenterScreen" Background="#F1F5F9" FontFamily="Segoe UI" FontSize="13">
  <Window.Resources>
    <Style TargetType="Button">
      <Setter Property="Padding" Value="22,8"/><Setter Property="Margin" Value="6,0,0,0"/>
      <Setter Property="Foreground" Value="#0F172A"/><Setter Property="Background" Value="#E2E8F0"/>
      <Setter Property="BorderThickness" Value="0"/><Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button">
        <Border Background="{TemplateBinding Background}" CornerRadius="6" Padding="{TemplateBinding Padding}">
          <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/></Border>
        <ControlTemplate.Triggers><Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.45"/></Trigger>
        <Trigger Property="IsMouseOver" Value="True"><Setter Property="Opacity" Value="0.85"/></Trigger></ControlTemplate.Triggers>
      </ControlTemplate></Setter.Value></Setter>
    </Style>
    <Style x:Key="Card" TargetType="Border">
      <Setter Property="Background" Value="White"/><Setter Property="CornerRadius" Value="10"/>
      <Setter Property="BorderBrush" Value="#E2E8F0"/><Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="16,12"/><Setter Property="Margin" Value="0,0,0,10"/>
    </Style>
  </Window.Resources>
  <DockPanel>
    <Border DockPanel.Dock="Top" Height="104" Background="#063360">
      <DockPanel Margin="14,0,22,0">
        <Image x:Name="Logo" Height="96" DockPanel.Dock="Left" VerticalAlignment="Center" RenderOptions.BitmapScalingMode="HighQuality"/>
        <StackPanel VerticalAlignment="Center" Margin="18,0,0,0">
          <TextBlock Text="Setup" Foreground="White" FontSize="24" FontWeight="SemiBold"/>
          <TextBlock x:Name="Sub" Text="Translate books and documents - same layout - offline AI" Foreground="#C7D2FE" FontSize="13"/>
        </StackPanel>
      </DockPanel>
    </Border>
    <Border DockPanel.Dock="Bottom" Background="White" BorderBrush="#E2E8F0" BorderThickness="0,1,0,0" Padding="22,12">
      <DockPanel>
        <StackPanel DockPanel.Dock="Left" VerticalAlignment="Center">
          <TextBlock x:Name="Foot" Foreground="#64748B" Text=""/>
          <TextBlock Foreground="#94A3B8" FontSize="11" Text="(c) 2026 Hadi Sarhangi Fard. All rights reserved.  By installing you accept LICENSE.txt."/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
          <Button x:Name="BtnCancel" Content="Cancel"/>
          <Button x:Name="BtnGo" Content="Install" Background="#1BF576" Foreground="#052E16"/>
        </StackPanel>
      </DockPanel>
    </Border>
    <Grid Margin="22,16,22,6">
      <!-- page 1: what to install -->
      <StackPanel x:Name="Page1">
        <Border Style="{StaticResource Card}">
          <StackPanel>
            <TextBlock Text="1 - Choose the translation engines" FontSize="16" FontWeight="SemiBold" Foreground="#4F46E5"/>
            <StackPanel Orientation="Horizontal" Margin="0,8,0,4">
              <RadioButton x:Name="RbAdv" Content="Advanced - all engines (recommended)" IsChecked="True" FontWeight="SemiBold" Margin="0,0,22,0"/>
              <RadioButton x:Name="RbStd" Content="Standard - built-in engine only" Margin="0,0,22,0"/>
              <RadioButton x:Name="RbMin" Content="Small - app only, engines later"/>
            </StackPanel>
            <CheckBox x:Name="CbBuiltin" IsChecked="True" Margin="0,8,0,0">
              <TextBlock TextWrapping="Wrap" Width="700"><Run FontWeight="SemiBold" Text="Built-in engine (MADLAD-400 3B)"/><Run x:Name="TxBuiltin" Text=""/></TextBlock></CheckBox>
            <CheckBox x:Name="CbOllama" IsChecked="True" Margin="0,8,0,0">
              <TextBlock TextWrapping="Wrap" Width="700"><Run FontWeight="SemiBold" Text="Ollama with the Gemma model"/><Run x:Name="TxOllama" Text=""/></TextBlock></CheckBox>
            <CheckBox x:Name="CbApi" IsChecked="True" Margin="0,8,0,0">
              <TextBlock TextWrapping="Wrap" Width="700"><Run FontWeight="SemiBold" Text="Online API (OpenAI-compatible)"/><Run Text=" - nothing to download. You type the address and your own key in the app."/></TextBlock></CheckBox>
          </StackPanel>
        </Border>
        <Border Style="{StaticResource Card}" Background="#FFFBEB" BorderBrush="#FCD34D">
          <StackPanel>
            <TextBlock Text="The first installation needs a lot of time" FontWeight="SemiBold" Foreground="#92400E"/>
            <TextBlock x:Name="TxTotal" TextWrapping="Wrap" Margin="0,4,0,0" Foreground="#78350F"/>
          </StackPanel>
        </Border>
        <Border Style="{StaticResource Card}">
          <DockPanel>
            <TextBlock Text="Install in:" VerticalAlignment="Center" FontWeight="SemiBold"/>
            <Button x:Name="BtnDir" Content="Change..." DockPanel.Dock="Right" Padding="14,5"/>
            <TextBlock x:Name="TxDir" VerticalAlignment="Center" Margin="10,0" TextTrimming="CharacterEllipsis" Foreground="#334155"/>
          </DockPanel>
        </Border>
      </StackPanel>
      <!-- page 2: progress -->
      <DockPanel x:Name="Page2" Visibility="Collapsed">
        <Border Style="{StaticResource Card}" DockPanel.Dock="Top">
          <StackPanel>
            <TextBlock x:Name="TxStep" Text="Starting ..." FontSize="16" FontWeight="SemiBold" Foreground="#4F46E5"/>
            <TextBlock x:Name="TxDetail" Text="" Margin="0,4,0,8" Foreground="#334155"/>
            <ProgressBar x:Name="Bar" Height="14" Minimum="0" Maximum="100" Foreground="#1BF576" Background="#E2E8F0" BorderThickness="0"/>
            <TextBlock x:Name="TxAll" Text="" Margin="0,8,0,0" Foreground="#64748B"/>
          </StackPanel>
        </Border>
        <Border Style="{StaticResource Card}" Background="#0F172A" BorderBrush="#334155" Padding="10">
          <TextBox x:Name="LogBox" Background="Transparent" Foreground="#E2E8F0" BorderThickness="0" IsReadOnly="True"
                   FontFamily="Consolas" FontSize="12" VerticalScrollBarVisibility="Auto" TextWrapping="Wrap"/>
        </Border>
      </DockPanel>
      <!-- page 3: done -->
      <StackPanel x:Name="Page3" Visibility="Collapsed" VerticalAlignment="Center">
        <TextBlock x:Name="TxDone" Text="DeepTome Translator is installed" FontSize="24" FontWeight="SemiBold" Foreground="#16A34A" HorizontalAlignment="Center"/>
        <TextBlock x:Name="TxDone2" TextWrapping="Wrap" TextAlignment="Center" Margin="40,14,40,18" Foreground="#334155"/>
        <CheckBox x:Name="CbRun" Content="Start DeepTome Translator now" IsChecked="True" HorizontalAlignment="Center"/>
      </StackPanel>
    </Grid>
  </DockPanel>
</Window>
"@
$win = [Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $xaml))
$ui = @{}
foreach ($n in "Logo","Sub","Foot","BtnCancel","BtnGo","Page1","Page2","Page3","RbAdv","RbStd","RbMin","CbBuiltin","CbOllama","CbApi",
               "TxBuiltin","TxOllama","TxTotal","TxDir","BtnDir","TxStep","TxDetail","Bar","TxAll","LogBox","TxDone","TxDone2","CbRun") {
    $ui[$n] = $win.FindName($n)
}
$logo = Join-Path $Here "app\assets\logo_setup.png"      # cut from the high-resolution logo, same blue as the header
if (-not (Test-Path $logo)) { $logo = Join-Path $Here "app\assets\logo.png" }
if (Test-Path $logo) { $ui.Logo.Source = New-Object Windows.Media.Imaging.BitmapImage ([Uri]$logo) }
$ico = Join-Path $Here "app\assets\deeptome.ico"
if (Test-Path $ico) { try { $win.Icon = [Windows.Media.Imaging.BitmapFrame]::Create([Uri]$ico) } catch {} }

$ui.TxBuiltin.Text = " - works offline, nothing to set up. Download: " + (Fmt $Size.Madlad) + " once; it is then converted and needs 2.8 GB on the disk."
$ui.TxOllama.Text  = " - a language model on this computer (better Persian, follows your instructions). Download: Ollama " + (Fmt $Size.Ollama) + " + model " + $OllamaModel + " " + (Fmt $Size.Gemma) + "."
$ui.TxDir.Text = $InstallDir

function Update-Total {
    $t = $Size.Python + $Size.Pip + $Size.Voices
    if ($ui.CbBuiltin.IsChecked) { $t += $Size.Madlad }
    if ($ui.CbOllama.IsChecked)  { $t += $Size.Ollama + $Size.Gemma }
    $disk = 1.6e9
    if ($ui.CbBuiltin.IsChecked) { $disk += 2.8e9 }
    if ($ui.CbOllama.IsChecked)  { $disk += 5.0e9 + $Size.Gemma }
    $peak = $disk
    if ($ui.CbBuiltin.IsChecked) { $peak += $Size.Madlad }
    $h = { param($mbit) $s = $t * 8 / ($mbit * 1e6); if ($s -ge 5400) { "{0:N1} hours" -f ($s / 3600) } else { "{0:N0} minutes" -f [math]::Ceiling($s / 60) } }
    $conv = ""
    if ($ui.CbBuiltin.IsChecked) { $conv = " After the download the built-in model is converted once, which takes 15 to 40 more minutes." }
    $ui.TxTotal.Text = "Download now: " + (Fmt $t) + "  (Python " + (Fmt $Size.Python) + ", program packages " + (Fmt $Size.Pip) + " and the engines you ticked)." +
        "  That is about " + (& $h 100) + " with a 100 Mbit/s line, " + (& $h 20) + " with 20 Mbit/s, " + (& $h 5) + " with 5 Mbit/s." + $conv +
        "  Free disk space needed: " + (Fmt $peak) + " during the installation, " + (Fmt $disk) + " afterwards." +
        "  You can keep using the computer; a download that is interrupted continues where it stopped when you run Setup again."
    try {
        $drive = (Get-Item ([IO.Path]::GetPathRoot($InstallDir))).PSDrive
        $free = $drive.Free
        $script:SpaceShort = ($free -lt $peak)
        if ($free -lt $peak) { $ui.Foot.Text = "Not enough free space on " + $drive.Name + ": (" + (Fmt $free) + " free)"; $ui.Foot.Foreground = "#DC2626" }
        else { $ui.Foot.Text = "Free on drive " + $drive.Name + ": " + (Fmt $free); $ui.Foot.Foreground = "#64748B" }
    } catch { $ui.Foot.Text = "" }
}
$busy = $false
$SpaceShort = $false
$ui.RbAdv.Add_Checked({ if (-not $script:busy) { $script:busy = $true; $ui.CbBuiltin.IsChecked = $true;  $ui.CbOllama.IsChecked = $true;  $ui.CbApi.IsChecked = $true; $script:busy = $false; Update-Total } })
$ui.RbStd.Add_Checked({ if (-not $script:busy) { $script:busy = $true; $ui.CbBuiltin.IsChecked = $true;  $ui.CbOllama.IsChecked = $false; $ui.CbApi.IsChecked = $true; $script:busy = $false; Update-Total } })
$ui.RbMin.Add_Checked({ if (-not $script:busy) { $script:busy = $true; $ui.CbBuiltin.IsChecked = $false; $ui.CbOllama.IsChecked = $false; $ui.CbApi.IsChecked = $true; $script:busy = $false; Update-Total } })
foreach ($cb in $ui.CbBuiltin, $ui.CbOllama) { $cb.Add_Click({ Update-Total }) }
$ui.BtnDir.Add_Click({
    $d = New-Object System.Windows.Forms.FolderBrowserDialog
    $d.Description = "Folder for DeepTome Translator"
    if ($d.ShowDialog() -eq "OK") { $script:InstallDir = Join-Path $d.SelectedPath "DeepTome"; $ui.TxDir.Text = $script:InstallDir; Update-Total }
})
Update-Total

# ------------------------------------------------------------------ the work (runs beside the window)
$sync = [hashtable]::Synchronized(@{ Step = ""; Detail = ""; Pct = 0; All = ""; Log = New-Object System.Collections.ArrayList; Done = $false; Error = ""; Cancel = $false })
$worker = {
    param($sync, $cfg)
    $ErrorActionPreference = "Stop"
    function Log($m) { [void]$sync.Log.Add($m) }
    function Step($n, $of, $title) { $sync.Step = "Step $n of $of - $title"; $sync.Detail = ""; $sync.Pct = 0; $sync.All = "Step $n of $of"; Log "== $title" }
    function Fmt([double]$b) { if ($b -ge 1e9) { "{0:N2} GB" -f ($b / 1e9) } else { "{0:N0} MB" -f ($b / 1e6) } }
    function Get-File($url, $dest, $what) {
        # download with progress; a partial file is continued
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $part = "$dest.part"
        $have = 0
        if (Test-Path $part) { $have = (Get-Item $part).Length }
        $req = [Net.HttpWebRequest]::Create($url)
        $req.UserAgent = "DeepTomeSetup"
        $req.Timeout = 60000; $req.ReadWriteTimeout = 120000
        if ($have -gt 0) { $req.AddRange([long]$have) }
        try { $resp = $req.GetResponse() }
        catch {
            if ($have -gt 0) { Remove-Item $part -Force; return (Get-File $url $dest $what) }
            throw
        }
        if ($have -gt 0 -and [int]$resp.StatusCode -ne 206) { $have = 0 }
        $total = $have + $resp.ContentLength
        $in = $resp.GetResponseStream()
        $mode = [IO.FileMode]::Create
        if ($have -gt 0) { $mode = [IO.FileMode]::Append }
        $out = New-Object IO.FileStream ($part, $mode)
        $buf = New-Object byte[] 262144
        $got = $have; $t0 = Get-Date; $g0 = $got; $speed = 0
        try {
            while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
                if ($sync.Cancel) { throw "cancelled" }
                $out.Write($buf, 0, $n); $got += $n
                $dt = ((Get-Date) - $t0).TotalSeconds
                if ($dt -ge 1) { $speed = ($got - $g0) / $dt; $t0 = Get-Date; $g0 = $got }
                $sync.Pct = [int](100 * $got / [math]::Max(1, $total))
                $left = ""
                if ($speed -gt 0) { $s = ($total - $got) / $speed; $left = "  -  {0:N1} MB/s, about {1:N0} min left" -f ($speed / 1MB), [math]::Ceiling($s / 60) }
                $sync.Detail = "$what  " + (Fmt $got) + " of " + (Fmt $total) + $left
            }
        } finally { $out.Close(); $in.Close(); $resp.Close() }
        Move-Item $part $dest -Force
    }
    function Run($exe, $argList, $what, $env2) {
        # run a program, show its output lines in the log
        $psi = New-Object Diagnostics.ProcessStartInfo
        $psi.FileName = $exe; $psi.Arguments = $argList; $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
        $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
        $psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"; $psi.EnvironmentVariables["PYTHONUTF8"] = "1"
        $psi.EnvironmentVariables["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        if ($env2) { foreach ($k in $env2.Keys) { $psi.EnvironmentVariables[$k] = $env2[$k] } }
        $p = New-Object Diagnostics.Process
        $p.StartInfo = $psi
        $h = { if ($EventArgs.Data) { $line = $EventArgs.Data; $s = $Event.MessageData; if ($line.Length -gt 200) { $line = $line.Substring(0, 200) }; $s.Detail = $line; [void]$s.Log.Add("   " + $line) } }
        $e1 = Register-ObjectEvent $p OutputDataReceived -Action $h -MessageData $sync
        $e2 = Register-ObjectEvent $p ErrorDataReceived -Action $h -MessageData $sync
        [void]$p.Start(); $p.BeginOutputReadLine(); $p.BeginErrorReadLine()
        while (-not $p.WaitForExit(400)) { if ($sync.Cancel) { try { $p.Kill() } catch {}; throw "cancelled" } }
        $p.WaitForExit()
        Unregister-Event $e1.Name; Unregister-Event $e2.Name
        if ($p.ExitCode -ne 0) { throw "$what failed (exit code $($p.ExitCode)). See the lines above." }
    }
    try {
        $dir = $cfg.Dir; $app = Join-Path $dir "app"; $py = Join-Path $dir "python\python.exe"; $pyw = Join-Path $dir "python\pythonw.exe"
        $n = 5; if ($cfg.Builtin) { $n++ }; if ($cfg.Ollama) { $n++ }
        $k = 0
        if ($cfg.DryRun) {
            foreach ($t in "Copying the program", "Installing Python", "Installing the program packages", "Built-in engine", "Ollama", "Shortcuts") {
                $k++; Step $k 6 $t
                for ($i = 0; $i -le 100; $i += 10) { $sync.Pct = $i; $sync.Detail = "(test run - nothing is installed)  $i %"; Start-Sleep -Milliseconds 120 }
            }
            $sync.Done = $true; return
        }
        # 1 ---- the program files
        $k++; Step $k $n "Copying the program"
        New-Item -ItemType Directory -Force -Path $app | Out-Null
        Copy-Item (Join-Path $cfg.Here "app\*") $app -Recurse -Force
        Copy-Item (Join-Path $cfg.Here "uninstall.ps1") $dir -Force
        foreach ($doc in "README.txt", "LICENSE.txt", "THIRD_PARTY_NOTICES.txt", "CHANGELOG.txt") {
            $f = Join-Path $cfg.Here $doc
            if (Test-Path $f) { Copy-Item $f $dir -Force }
        }
        $sync.Pct = 100
        # 2 ---- a private Python (with Tk); it does not touch any Python that is already on the computer
        $k++; Step $k $n "Installing Python (private copy, $(Fmt $cfg.Size.Python))"
        if (-not (Test-Path $py)) {
            $tgz = Join-Path $dir "python.tar.gz"
            Get-File $cfg.PythonUrl $tgz "Python"
            $sync.Detail = "Unpacking Python ..."
            Run (Join-Path $env:SystemRoot "System32\tar.exe") "-xf `"$tgz`" -C `"$dir`"" "Unpacking Python" $null
            Remove-Item $tgz -Force
        } else { Log "   Python is already there." }
        if (-not (Test-Path $py)) { throw "Python could not be unpacked into $dir" }
        # 3 ---- packages
        $k++; Step $k $n "Installing the program packages ($(Fmt $cfg.Size.Pip), 54 packages)"
        $sync.Pct = 5
        Run $py "-m pip install --no-warn-script-location --disable-pip-version-check -r `"$app\requirements.txt`"" "Installing the packages" $null
        $sync.Pct = 100
        Run $py "-c `"import fitz, ctranslate2, transformers, sentencepiece, tkinter; print('packages ok, PyMuPDF', fitz.VersionBind)`"" "Checking the packages" $null
        # 3b ---- voices for the pronunciation of Quick translate: one offline voice for each of the five languages
        #         (never fatal: without the internet they can be installed later in Settings -> Components)
        $k++; Step $k $n "Offline voices for English, Persian, German, French and Spanish ($(Fmt $cfg.Size.Voices))"
        $code = "import sys, subprocess; sys.path.insert(0, r'$app'); r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-warn-script-location', '--disable-pip-version-check', 'piper-tts']); import book_translator as bt; n = bt.install_default_voices(lambda m: print(m, flush=True)) if r.returncode == 0 else 0; print('voices ready:', n, flush=True)"
        try { Run $py "-c `"$code`"" "Installing the voices" $null } catch { Log "   The voices could not be installed now - install them later in Settings (Components)." }
        $sync.Pct = 100
        # 4 ---- built-in engine: download + convert (the long step)
        if ($cfg.Builtin) {
            $k++; Step $k $n "Built-in engine: downloading and converting MADLAD-400 ($(Fmt $cfg.Size.Madlad)) - the long step"
            $sync.Detail = "This step takes the longest. The window may show the same line for a long time."
            $code = "import sys; sys.path.insert(0, r'$app'); import book_translator as bt; p, fam = bt.prepare_model(bt.DEFAULT_MODEL, lambda m: print(m, flush=True), True); print('model ready:', p, flush=True)"
            Run $py "-c `"$code`"" "Preparing the built-in model" @{ HF_HUB_DISABLE_PROGRESS_BARS = "1" }
            $sync.Pct = 100
        }
        # 5 ---- Ollama + model
        if ($cfg.Ollama) {
            $k++; Step $k $n "Ollama and the model $($cfg.OllamaModel)"
            $ol = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
            if (-not (Test-Path $ol)) {
                $cmd = Get-Command ollama -ErrorAction SilentlyContinue
                if ($cmd) { $ol = $cmd.Source }
            }
            if (-not (Test-Path $ol)) {
                $setup = Join-Path $dir "OllamaSetup.exe"
                Get-File $cfg.OllamaUrl $setup "Ollama"
                $sync.Detail = "Installing Ollama ..."; $sync.Pct = 100
                $p = Start-Process $setup -ArgumentList "/VERYSILENT /NORESTART /SUPPRESSMSGBOXES" -PassThru
                while (-not $p.WaitForExit(500)) { if ($sync.Cancel) { throw "cancelled" } }
                Remove-Item $setup -Force -ErrorAction SilentlyContinue
                $ol = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
                if (-not (Test-Path $ol)) { throw "Ollama was not installed. Install it from https://ollama.com and run Setup again." }
            } else { Log "   Ollama is already installed." }
            # the Ollama service must answer before a model can be pulled
            $ok = $false
            for ($i = 0; $i -lt 40 -and -not $ok; $i++) {
                try { [void](Invoke-WebRequest "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3); $ok = $true }
                catch { if ($i -eq 2) { Start-Process $ol -ArgumentList "serve" -WindowStyle Hidden }; Start-Sleep -Seconds 2 }
            }
            $sync.Pct = 0; $sync.Detail = "Downloading the model $($cfg.OllamaModel) ($(Fmt $cfg.Size.Gemma)) ..."
            Run $ol "pull $($cfg.OllamaModel)" "Downloading the Ollama model" $null
            $sync.Pct = 100
        }
        # 6 ---- shortcuts, entry in "Apps", settings for the first start
        $k++; Step $k $n "Shortcuts"
        if (-not $cfg.NoShortcuts) {
            $sh = New-Object -ComObject WScript.Shell
            $targets = @((Join-Path ([Environment]::GetFolderPath("Desktop")) "DeepTome Translator.lnk"),
                         (Join-Path ([Environment]::GetFolderPath("Programs")) "DeepTome Translator.lnk"))
            # Windows keeps shortcut icons in a cache keyed by the file name: a new name makes it show the new icon
            Get-ChildItem (Join-Path $app "assets") -Filter "shortcut_*.ico" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
            $icoName = "shortcut_" + (Get-Date -Format "yyyyMMddHHmmss") + ".ico"
            Copy-Item (Join-Path $app "assets\deeptome.ico") (Join-Path $app "assets\$icoName") -Force
            foreach ($lnk in $targets) {
                $s = $sh.CreateShortcut($lnk)
                $s.TargetPath = $pyw; $s.Arguments = "`"$app\book_translator.py`""; $s.WorkingDirectory = $app
                $s.IconLocation = (Join-Path $app "assets\$icoName"); $s.Description = "DeepTome Translator"
                $s.Save()
            }
            $rk = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepTomeTranslator"
            New-Item $rk -Force | Out-Null
            Set-ItemProperty $rk DisplayName "DeepTome Translator"
            Set-ItemProperty $rk DisplayVersion $cfg.Version
            Set-ItemProperty $rk Publisher "Hadi Sarhangi Fard"
            Set-ItemProperty $rk InstallLocation $dir
            Set-ItemProperty $rk DisplayIcon (Join-Path $app "assets\deeptome.ico")
            Set-ItemProperty $rk UninstallString "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$dir\uninstall.ps1`""
            Set-ItemProperty $rk NoModify 1 -Type DWord
            Set-ItemProperty $rk NoRepair 1 -Type DWord
            try { Start-Process (Join-Path $env:SystemRoot "System32\ie4uinit.exe") -ArgumentList "-show" -WindowStyle Hidden } catch {}
        }
        $sync.Pct = 100
        Log "== Finished."
        $sync.Done = $true
    } catch {
        $sync.Error = "$($_.Exception.Message)"
        Log ("ERROR: " + $sync.Error)
    }
}

$state = @{ Phase = "choose"; PS = $null; Shown = 0; Shot2 = $false }
function Save-Shot($n) {
    if (-not $Shot) { return }
    try {
        $el = $win.Content
        $win.UpdateLayout()
        $bmp = New-Object Windows.Media.Imaging.RenderTargetBitmap ([int]$el.ActualWidth, [int]$el.ActualHeight, 96, 96, [Windows.Media.PixelFormats]::Pbgra32)
        $bmp.Render($el)
        $enc = New-Object Windows.Media.Imaging.PngBitmapEncoder
        $enc.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp))
        $fs = [IO.File]::Create("$Shot-$n.png"); $enc.Save($fs); $fs.Close()
    } catch {}
}
function Start-Install {
    $ui.Page1.Visibility = "Collapsed"; $ui.Page2.Visibility = "Visible"
    $ui.BtnGo.IsEnabled = $false; $ui.BtnGo.Content = "Installing ..."
    $ui.Foot.Text = ""
    $ver = "3.2"
    try { $m = Select-String -Path (Join-Path $Here "app\book_translator.py") -Pattern '^APP_VERSION = "(.+)"' | Select-Object -First 1; if ($m) { $ver = $m.Matches[0].Groups[1].Value } } catch {}
    $cfg = @{ Dir = $script:InstallDir; Here = $Here; Builtin = [bool]$ui.CbBuiltin.IsChecked; Ollama = [bool]$ui.CbOllama.IsChecked
              DryRun = [bool]$DryRun; NoShortcuts = [bool]$NoShortcuts; PythonUrl = $PythonUrl; OllamaUrl = $OllamaUrl
              OllamaModel = $OllamaModel; Size = $Size; Version = $ver }
    $ps = [PowerShell]::Create()
    [void]$ps.AddScript($worker).AddArgument($sync).AddArgument($cfg)
    $state.PS = $ps; $state.Handle = $ps.BeginInvoke(); $state.Phase = "work"
}
$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(250)
$timer.Add_Tick({
    if ($state.Phase -ne "work") { return }
    $ui.TxStep.Text = $sync.Step; $ui.TxDetail.Text = $sync.Detail; $ui.Bar.Value = $sync.Pct; $ui.TxAll.Text = $sync.All
    $cnt = $sync.Log.Count
    if ($cnt -gt $state.Shown) {
        $new = $sync.Log.GetRange($state.Shown, $cnt - $state.Shown) -join "`r`n"
        $ui.LogBox.AppendText($new + "`r`n"); $ui.LogBox.ScrollToEnd(); $state.Shown = $cnt
    }
    if (-not $state.Shot2 -and $sync.Pct -ge 40 -and $sync.Log.Count -ge 3) { $state.Shot2 = $true; Save-Shot 2 }
    if ($sync.Done) {
        $state.Phase = "done"
        $ui.Page2.Visibility = "Collapsed"; $ui.Page3.Visibility = "Visible"
        $ui.TxDone2.Text = "A shortcut 'DeepTome Translator' is on your desktop and in the Start menu. Double-click it to start the app.`n`nInstalled in: " + $script:InstallDir
        if ($DryRun) { $ui.TxDone.Text = "Test run finished - nothing was installed"; $ui.CbRun.IsChecked = $false }
        $ui.BtnGo.Content = "Finish"; $ui.BtnGo.IsEnabled = $true; $ui.BtnCancel.Visibility = "Collapsed"
        Save-Shot 3
        if ($Auto) { $win.Close() }
    } elseif ($sync.Error) {
        $state.Phase = "error"
        $ui.TxStep.Text = "The installation stopped"; $ui.TxStep.Foreground = "#DC2626"
        $ui.TxDetail.Text = $sync.Error + "   -   Run Setup again: what is already downloaded is kept."
        $ui.BtnGo.Content = "Close"; $ui.BtnGo.IsEnabled = $true; $ui.BtnCancel.Visibility = "Collapsed"
        try { $sync.Log -join "`r`n" | Out-File (Join-Path $env:TEMP "DeepTome_setup.log") -Encoding utf8 } catch {}
        if ($Auto) { $win.Close() }
    }
})
$ui.BtnGo.Add_Click({
    if ($state.Phase -eq "choose") {
        if ($script:SpaceShort -and -not $DryRun) {
            if ([Windows.MessageBox]::Show("There is probably not enough free disk space for what you ticked.`n`n" + $ui.Foot.Text + "`n`nFree some space, choose fewer engines, or install anyway.`n`nInstall anyway?", "Setup", "YesNo", "Warning") -ne "Yes") { return }
        }
        Start-Install
    }
    elseif ($state.Phase -eq "done") {
        if ($ui.CbRun.IsChecked -and -not $DryRun) {
            Start-Process (Join-Path $script:InstallDir "python\pythonw.exe") -ArgumentList ("`"" + (Join-Path $script:InstallDir "app\book_translator.py") + "`"") -WorkingDirectory (Join-Path $script:InstallDir "app")
        }
        $win.Close()
    } else { $win.Close() }
})
$ui.BtnCancel.Add_Click({
    if ($state.Phase -eq "work") {
        if ([Windows.MessageBox]::Show("Stop the installation?`n`nWhat is already downloaded is kept; run Setup again to continue.", "Setup", "YesNo", "Question") -eq "Yes") { $sync.Cancel = $true }
    } else { $win.Close() }
})
$win.Add_Closing({ param($s, $e) if ($state.Phase -eq "work" -and -not $sync.Error -and -not $sync.Done) { $sync.Cancel = $true } })
$timer.Start()
if ($Auto) {
    $ui.CbBuiltin.IsChecked = ($Auto -in "builtin", "all"); $ui.CbOllama.IsChecked = ($Auto -in "ollama", "all")
    $win.Add_ContentRendered({ Save-Shot 1; Start-Install })
}
[void]$win.ShowDialog()
$timer.Stop()
if ($sync.Error) { exit 1 }
