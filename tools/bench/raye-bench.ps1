# SPDX-License-Identifier: GPL-3.0-or-later
# The same measures as raye-bench, on Windows, so the two can be compared
# with `raye-bench --compare windows.json raye.json`. Same JSON shape.
#
#   powershell -ExecutionPolicy Bypass -File raye-bench.ps1 -Out windows.json
#
# Run it as admin (the boot log needs it), 5 minutes after logging in, on
# mains power, with nothing else open. Boot times are the last three boots
# from Windows' own boot performance log (event 100), so restart three
# times first. Each app is opened and closed three times; the median counts.

param(
    [int]$Runs = 3,
    [string]$Out = ""
)

$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class RayeBenchWin {
    public delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr hwnd, uint cmd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);
    [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr hwnd, int attr, out int value, int size);
    // Visible, unowned, not cloaked: what shows on the taskbar.
    public static List<long> TopWindows() {
        var list = new List<long>();
        EnumWindows(delegate (IntPtr h, IntPtr p) {
            int cloaked = 0;
            DwmGetWindowAttribute(h, 14, out cloaked, 4);
            if (IsWindowVisible(h) && GetWindow(h, 4) == IntPtr.Zero && cloaked == 0) list.Add(h.ToInt64());
            return true;
        }, IntPtr.Zero);
        return list;
    }
    public static uint Pid(long h) { uint pid; GetWindowThreadProcessId(new IntPtr(h), out pid); return pid; }
    public static void Close(long h) { PostMessage(new IntPtr(h), 0x0010, IntPtr.Zero, IntPtr.Zero); }
}
"@

function Get-Agg($values) {
    $good = @($values | Where-Object { $null -ne $_ } | Sort-Object)
    if ($good.Count -eq 0) {
        return [ordered]@{ median = $null; min = $null; max = $null; values = @($values) }
    }
    $mid = [math]::Floor($good.Count / 2)
    if ($good.Count % 2) { $median = $good[$mid] } else { $median = ($good[$mid - 1] + $good[$mid]) / 2 }
    return [ordered]@{ median = [math]::Round([double]$median, 4); min = $good[0]; max = $good[-1]; values = @($values) }
}

# ------------------------------------------------------------ fingerprint
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$fp = [ordered]@{
    os = "$($os.Caption) $($os.Version)"
    cpu = $cpu.Name.Trim()
    threads = [int]$env:NUMBER_OF_PROCESSORS
    ram_mib = [math]::Floor($os.TotalVisibleMemorySize / 1024)
    disk = $null
    gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object { "$($_.Name) $($_.DriverVersion)" })
    kernel = $os.Version
    fast_startup = $null
    on_mains = $null
    virtual = $null
}
try {
    $num = (Get-Partition -DriveLetter C).DiskNumber
    $pd = Get-PhysicalDisk | Where-Object { $_.DeviceId -eq "$num" } | Select-Object -First 1
    $kind = if ($pd.MediaType -eq "HDD") { "hdd" } else { "ssd" }
    $fp.disk = "$($pd.FriendlyName.Trim()) ($($pd.BusType.ToString().ToLower()), $kind)"
} catch { }
try {
    $hb = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" -Name HiberbootEnabled
    $fp.fast_startup = [bool]$hb.HiberbootEnabled
} catch { }
$battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1
if ($battery) { $fp.on_mains = ($battery.BatteryStatus -eq 2) }
$model = (Get-CimInstance Win32_ComputerSystem).Model
if ($model -match "Virtual|VMware|KVM|QEMU") { $fp.virtual = $model }

$results = [ordered]@{}
$details = [ordered]@{}
$errors = [ordered]@{}

# ------------------------------------------------------------ boot
try {
    $events = Get-WinEvent -FilterHashtable @{ LogName = 'Microsoft-Windows-Diagnostics-Performance/Operational'; Id = 100 } -MaxEvents $Runs
    $total = @(); $main = @()
    foreach ($e in $events) {
        $data = ([xml]$e.ToXml()).Event.EventData.Data
        $total += [math]::Round([double](($data | Where-Object Name -eq 'BootTime').'#text') / 1000, 2)
        $main += [math]::Round([double](($data | Where-Object Name -eq 'MainPathBootTime').'#text') / 1000, 2)
    }
    $results.boot = [ordered]@{ total_s = Get-Agg $total; main_path_s = Get-Agg $main }
} catch {
    $errors.boot = "no boot performance log (run as admin): $($_.Exception.Message)"
}

# ------------------------------------------------------------ memory, disk
$results.memory = [ordered]@{
    used_mib = Get-Agg @([math]::Floor(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1024))
    total_mib = Get-Agg @([math]::Floor($os.TotalVisibleMemorySize / 1024))
}
$c = Get-PSDrive C
$results.disk = [ordered]@{
    used_gib = Get-Agg @([math]::Round($c.Used / 1GB, 2))
    size_gib = Get-Agg @([math]::Round(($c.Used + $c.Free) / 1GB, 1))
}

# ------------------------------------------------------------ launch
# The counterparts of the apps raye-bench opens on Raye. A new window
# owned by one of the listed processes ends the timing; it is then closed
# with WM_CLOSE, never by killing the process (Explorer is the shell).
$apps = [ordered]@{
    files    = @{ file = "explorer.exe"; args = "C:\"; procs = @("explorer") }
    browser  = @{ file = "msedge.exe"; args = "about:blank"; procs = @("msedge") }
    settings = @{ file = "ms-settings:"; args = $null; procs = @("SystemSettings", "ApplicationFrameHost") }
    terminal = @{ file = "wt.exe"; args = $null; procs = @("WindowsTerminal", "OpenConsole") }
    store    = @{ file = "ms-windows-store:"; args = $null; procs = @("WinStore.App", "ApplicationFrameHost") }
}

function Measure-Launch($app) {
    $before = [RayeBenchWin]::TopWindows()
    $sw = [Diagnostics.Stopwatch]::StartNew()
    if ($app.args) { Start-Process -FilePath $app.file -ArgumentList $app.args } else { Start-Process -FilePath $app.file }
    while ($sw.Elapsed.TotalSeconds -lt 60) {
        foreach ($h in [RayeBenchWin]::TopWindows()) {
            if ($before -contains $h) { continue }
            $p = Get-Process -Id ([RayeBenchWin]::Pid($h)) -ErrorAction SilentlyContinue
            if ($p -and ($app.procs -contains $p.ProcessName)) {
                $t = [math]::Round($sw.Elapsed.TotalSeconds, 3)
                [RayeBenchWin]::Close($h)
                Start-Sleep -Seconds 3
                return $t
            }
        }
        Start-Sleep -Milliseconds 20
    }
    return $null
}

$launch = [ordered]@{}
$launchDetail = [ordered]@{}
foreach ($name in $apps.Keys) {
    $times = @()
    for ($i = 0; $i -lt $Runs; $i++) {
        try { $times += Measure-Launch $apps[$name] } catch { $times += $null; $launchDetail[$name] = $_.Exception.Message }
    }
    $launch["$($name)_s"] = Get-Agg $times
}
$results.launch = $launch
$details.launch = @($launchDetail)

$report = [ordered]@{
    format = 2
    tool = "raye-bench.ps1"
    os = "windows"
    taken = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    runs = $Runs
    fingerprint = $fp
    results = $results
    details = $details
    errors = $errors
}
$json = $report | ConvertTo-Json -Depth 6
if ($Out) {
    # UTF-8 without a byte order mark, which Set-Content would add
    $path = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out)
    [IO.File]::WriteAllText($path, $json)
} else {
    $json
}
