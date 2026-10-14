<#
.SYNOPSIS
  Collects the hardware/software facts UNIVERSE Phase 1 needs to pick a model loadout.

.DESCRIPTION
  Read-only. Changes nothing on the system and installs nothing.
  Does not collect serial numbers, user names, or the computer name.
  Works in Windows PowerShell 5.1 and PowerShell 7+.

  Run from the repo root:
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hardware-report.ps1

  Then paste the contents of universe-hardware-report.txt into the chat.
#>

$ErrorActionPreference = 'Stop'
$script:Lines = New-Object System.Collections.Generic.List[string]

function Out-Line([string]$Text = '') { $script:Lines.Add($Text); Write-Host $Text }
function Out-Section([string]$Title) { Out-Line ''; Out-Line "## $Title" }
function Format-GB($Bytes) {
    if ($null -eq $Bytes -or $Bytes -eq 0) { return 'unknown' }
    return ('{0:N1} GB' -f ([double]$Bytes / 1GB))
}

# Runs one section; a failure is reported and the report continues.
function Invoke-Section([string]$Title, [scriptblock]$Body) {
    Out-Section $Title
    try { & $Body }
    catch { Out-Line "- unavailable: $(($_.Exception.Message -split "`r?`n")[0])" }
}

function Get-ToolVersion([string]$Name, [string[]]$VersionArgs = @('--version')) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { return 'not installed' }
    try {
        $out = & $cmd.Source @VersionArgs 2>&1 | Select-Object -First 1
        return ("$out").Trim()
    } catch { return "installed ($($cmd.Source)), version check failed" }
}

Out-Line '# UNIVERSE hardware report'
Out-Line ("Generated: {0:yyyy-MM-dd HH:mm} (PowerShell {1})" -f (Get-Date), $PSVersionTable.PSVersion)

Invoke-Section 'Operating system' {
    $os = Get-CimInstance Win32_OperatingSystem
    Out-Line "- Edition: $($os.Caption)"
    Out-Line "- Version / build: $($os.Version) / $($os.BuildNumber)"
    Out-Line "- Architecture: $($os.OSArchitecture)"
    $cs = Get-CimInstance Win32_ComputerSystem
    $form = switch ([int]$cs.PCSystemType) { 1 { 'desktop' } 2 { 'laptop / mobile' } 3 { 'workstation' } default { "type $($cs.PCSystemType)" } }
    Out-Line "- Form factor: $form ($($cs.Manufacturer) $($cs.Model))"
    $battery = @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
    if ($battery.Count -gt 0) {
        $onAc = ($battery | Where-Object { $_.BatteryStatus -eq 2 }).Count -gt 0
        Out-Line "- Battery: present (on AC power: $onAc)"
    } else { Out-Line '- Battery: none' }
    Out-Line "- Hypervisor present: $($cs.HypervisorPresent)"
}

Invoke-Section 'CPU' {
    foreach ($cpu in @(Get-CimInstance Win32_Processor)) {
        Out-Line "- $($cpu.Name.Trim())"
        Out-Line "  - Cores / threads: $($cpu.NumberOfCores) / $($cpu.NumberOfLogicalProcessors)"
        Out-Line "  - Max clock: $($cpu.MaxClockSpeed) MHz"
        Out-Line "  - Virtualization enabled in firmware: $($cpu.VirtualizationFirmwareEnabled)"
    }
}

Invoke-Section 'Memory' {
    $cs = Get-CimInstance Win32_ComputerSystem
    Out-Line "- Total RAM: $(Format-GB $cs.TotalPhysicalMemory)"
    $mods = @(Get-CimInstance Win32_PhysicalMemory)
    foreach ($m in $mods) {
        $speed = $m.ConfiguredClockSpeed
        if (-not $speed) { $speed = $m.Speed }
        Out-Line "  - Module: $(Format-GB $m.Capacity) @ $speed MT/s"
    }
}

Invoke-Section 'GPU' {
    # Win32_VideoController.AdapterRAM is a uint32 and caps at 4 GB, so read the
    # driver's 64-bit memory size from the display-adapter class key as well.
    $classKey = 'HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    $vramByName = @{}
    if (Test-Path $classKey) {
        Get-ChildItem $classKey -ErrorAction SilentlyContinue |
            Where-Object { $_.PSChildName -match '^\d{4}$' } |
            ForEach-Object {
                $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
                if ($p -and $p.DriverDesc) {
                    $size = $p.'HardwareInformation.qwMemorySize'
                    if (-not $size -and ($p.'HardwareInformation.MemorySize' -is [int] -or $p.'HardwareInformation.MemorySize' -is [long])) {
                        $size = $p.'HardwareInformation.MemorySize'
                    }
                    if ($size) { $vramByName[$p.DriverDesc] = [double]$size }
                }
            }
    }
    foreach ($gpu in @(Get-CimInstance Win32_VideoController)) {
        $vram = $vramByName[$gpu.Name]
        if (-not $vram) { $vram = $gpu.AdapterRAM }
        Out-Line "- $($gpu.Name)"
        Out-Line "  - VRAM: $(Format-GB $vram)"
        Out-Line "  - Driver: $($gpu.DriverVersion)"
        if ($gpu.CurrentHorizontalResolution) {
            Out-Line "  - Current mode: $($gpu.CurrentHorizontalResolution)x$($gpu.CurrentVerticalResolution) @ $($gpu.CurrentRefreshRate) Hz"
        }
    }
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($smi) {
        $q = & $smi.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>&1
        foreach ($row in @($q)) { Out-Line "- nvidia-smi: $row" }
        $cuda = (& $smi.Source 2>&1 | Select-String -Pattern 'CUDA Version:\s*([\d.]+)' | Select-Object -First 1)
        if ($cuda) { Out-Line "- CUDA (driver) version: $($cuda.Matches[0].Groups[1].Value)" }
    } else { Out-Line '- nvidia-smi: not found (no NVIDIA GPU or driver tools not on PATH)' }
}

Invoke-Section 'Displays' {
    Add-Type -AssemblyName System.Windows.Forms
    $screens = [System.Windows.Forms.Screen]::AllScreens
    Out-Line "- Count: $($screens.Count)"
    foreach ($s in $screens) {
        Out-Line "  - $($s.Bounds.Width)x$($s.Bounds.Height) primary=$($s.Primary)"
    }
}

Invoke-Section 'Storage' {
    foreach ($d in @(Get-PhysicalDisk)) {
        Out-Line "- Disk: $($d.FriendlyName) | $($d.MediaType) | $($d.BusType) | $(Format-GB $d.Size)"
    }
    foreach ($v in @(Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' } | Sort-Object DriveLetter)) {
        Out-Line "- Volume $($v.DriveLetter): $($v.FileSystem) | free $(Format-GB $v.SizeRemaining) of $(Format-GB $v.Size)"
    }
    foreach ($v in @(Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Removable' } | Sort-Object DriveLetter)) {
        Out-Line "- Removable $($v.DriveLetter): $($v.FileSystem) | free $(Format-GB $v.SizeRemaining) of $(Format-GB $v.Size)"
    }
}

Invoke-Section 'Audio and camera devices' {
    foreach ($a in @(Get-CimInstance Win32_SoundDevice)) { Out-Line "- Audio: $($a.Name)" }
    $cams = @(Get-PnpDevice -Class Camera, Image -PresentOnly -ErrorAction SilentlyContinue)
    if ($cams.Count -gt 0) { foreach ($c in $cams) { Out-Line "- Camera: $($c.FriendlyName)" } }
    else { Out-Line '- Camera: none detected' }
}

Invoke-Section 'Installed tools' {
    Out-Line "- git: $(Get-ToolVersion git)"
    Out-Line "- python: $(Get-ToolVersion python)"
    Out-Line "- uv: $(Get-ToolVersion uv)"
    Out-Line "- node: $(Get-ToolVersion node)"
    Out-Line "- pnpm: $(Get-ToolVersion pnpm)"
    Out-Line "- ollama: $(Get-ToolVersion ollama)"
    Out-Line "- docker: $(Get-ToolVersion docker)"
    Out-Line "- podman: $(Get-ToolVersion podman)"
    Out-Line "- restic: $(Get-ToolVersion restic @('version'))"
    $wsl = Get-Command wsl -ErrorAction SilentlyContinue
    if ($wsl) {
        $env:WSL_UTF8 = '1'   # wsl.exe prints UTF-16 otherwise
        $distros = & $wsl.Source --list --verbose 2>&1 | Where-Object { "$_".Trim() }
        Out-Line '- WSL distributions:'
        foreach ($row in @($distros)) { Out-Line "  $("$row".Trim())" }
    } else { Out-Line '- WSL: not installed' }
}

$outFile = Join-Path (Get-Location) 'universe-hardware-report.txt'
$script:Lines | Set-Content -Path $outFile -Encoding UTF8
Write-Host ''
Write-Host "Saved to $outFile"
