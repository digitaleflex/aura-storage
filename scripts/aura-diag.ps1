#requires -Version 5.1
<#
.SYNOPSIS
  Mesure réseau Aura périodique, sans navigateur.

.DESCRIPTION
  Rejoue le diagnostic de la page /diagnostic (RTT + gigue, descente, montée
  navigateur/serveur) et l'écrit dans un CSV local. Conçu pour une tâche
  planifiée Windows : il tourne onglet fermé, navigateur fermé.

  Aucun paquet à installer : PowerShell 5.1 (présent sur Windows 10/11) suffit.
  Le jeton d'identité de service est chiffré avec DPAPI (portée utilisateur),
  donc illisible par un autre compte de la machine.

.PARAMETER BaseUrl
  Origine de l'application, sans barre finale.

.PARAMETER SaveToken
  Demande le jeton et l'enregistre chiffré, puis quitte.

.PARAMETER Install
  Enregistre la tâche planifiée « AuraDiag » (toutes les IntervalMinutes).

.PARAMETER Remove
  Supprime la tâche planifiée.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\aura-diag.ps1 -SaveToken

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\aura-diag.ps1 -Install -IntervalMinutes 15

.NOTES
  Le PC doit être allumé pour mesurer ; au réveil, la tâche rattrape une
  exécution manquée (-StartWhenAvailable). Un passage consomme ~3 Mo.
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "https://app.aura-storage.eurinhash.com",
    [string]$TokenFile = (Join-Path $env:LOCALAPPDATA "Aura\diag-token.clixml"),
    [string]$OutFile = (Join-Path $env:LOCALAPPDATA "Aura\diag.csv"),
    [string]$ErrorLog = (Join-Path $env:LOCALAPPDATA "Aura\diag-errors.log"),
    [int]$PingCount = 10,
    [int]$DownloadBytes = 2000000,
    [int]$UploadBytes = 1000000,
    [int]$IntervalMinutes = 15,
    [switch]$SaveToken,
    [switch]$Install,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$TaskName = "AuraDiag"

function New-AuraDirectory([string]$Path) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}

function Protect-File([string]$Path) {
    # Lecture/écriture réservées au compte courant : un jeton ne doit pas
    # être lisible par un autre utilisateur de la machine.
    try {
        $me = "$env:USERDOMAIN\$env:USERNAME"
        & icacls.exe $Path /inheritance:r /grant:r "${me}:(R,W)" | Out-Null
    } catch {
        Write-Warning "ACL non appliquée sur $Path : vérifiez les droits manuellement."
    }
}

function Read-AuraToken {
    if (-not (Test-Path $TokenFile)) {
        throw "Jeton absent ($TokenFile). Lancez d'abord : -SaveToken"
    }
    $secure = Import-Clixml -Path $TokenFile
    if ($secure -isnot [System.Security.SecureString]) {
        throw "$TokenFile ne contient pas un SecureString attendu."
    }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Get-Median([double[]]$Values) {
    if ($Values.Count -eq 0) { return 0 }
    $sorted = $Values | Sort-Object
    $mid = [int][Math]::Floor($sorted.Count / 2)
    if ($sorted.Count % 2 -eq 1) { return [double]$sorted[$mid] }
    return ([double]$sorted[$mid - 1] + [double]$sorted[$mid]) / 2
}

function Invoke-AuraMeasurement {
    param([string]$Token)

    Add-Type -AssemblyName System.Net.Http

    $handler = New-Object System.Net.Http.HttpClientHandler
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(120)
    $client.DefaultRequestHeaders.Authorization =
        New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $Token)

    try {
        # --- RTT + gigue -----------------------------------------------------
        $samples = New-Object System.Collections.Generic.List[double]
        for ($i = 0; $i -lt [Math]::Max(1, $PingCount); $i++) {
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $response = $client.GetAsync("$BaseUrl/api/v1/diag/ping").GetAwaiter().GetResult()
            $response.EnsureSuccessStatusCode() | Out-Null
            $null = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            $sw.Stop()
            $samples.Add($sw.Elapsed.TotalMilliseconds) | Out-Null
        }
        $rttMin = ($samples | Measure-Object -Minimum).Minimum
        $rttMax = ($samples | Measure-Object -Maximum).Maximum
        $rttAvg = ($samples | Measure-Object -Average).Average
        $jitter = 0.0
        if ($samples.Count -gt 1) {
            $spread = 0.0
            for ($i = 1; $i -lt $samples.Count; $i++) {
                $spread += [Math]::Abs($samples[$i] - $samples[$i - 1])
            }
            $jitter = $spread / ($samples.Count - 1)
        }

        # --- Descente (lecture en flux) --------------------------------------
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $response = $client.GetAsync(
            "$BaseUrl/api/v1/diag/download?bytes=$DownloadBytes",
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        $response.EnsureSuccessStatusCode() | Out-Null
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $buffer = New-Object byte[] 65536
        $received = 0
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $received += $read
        }
        $stream.Dispose()
        $sw.Stop()
        $downBps = 0.0
        if ($sw.Elapsed.TotalSeconds -gt 0) {
            $downBps = $received / $sw.Elapsed.TotalSeconds
        }

        # --- Montée (navigateur + serveur) -----------------------------------
        $payload = New-Object byte[] ([Math]::Max(1, $UploadBytes))
        $content = New-Object System.Net.Http.ByteArrayContent($payload)
        $content.Headers.ContentType =
            New-Object System.Net.Http.Headers.MediaTypeHeaderValue("application/octet-stream")
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $response = $client.PostAsync("$BaseUrl/api/v1/diag/upload", $content).GetAwaiter().GetResult()
        $response.EnsureSuccessStatusCode() | Out-Null
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        $sw.Stop()
        $upBps = 0.0
        if ($sw.Elapsed.TotalSeconds -gt 0) {
            $upBps = $payload.Length / $sw.Elapsed.TotalSeconds
        }

        return [pscustomobject]@{
            Timestamp        = (Get-Date).ToString("o")
            RttMinMs         = [Math]::Round($rttMin, 1)
            RttAvgMs         = [Math]::Round($rttAvg, 1)
            RttMaxMs         = [Math]::Round($rttMax, 1)
            JitterMs         = [Math]::Round($jitter, 1)
            DownBps          = [Math]::Round($downBps, 0)
            UpBps            = [Math]::Round($upBps, 0)
            UpServerBps      = [int]$body.bytes_per_second
            DownMbps         = [Math]::Round(($downBps * 8) / 1000000, 2)
            UpMbps           = [Math]::Round(($upBps * 8) / 1000000, 2)
            UpServerMbps     = [Math]::Round(([double]$body.bytes_per_second * 8) / 1000000, 2)
        }
    } finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

# --- Modes d'administration ------------------------------------------------
if ($SaveToken) {
    New-AuraDirectory $TokenFile
    $secure = Read-Host -AsSecureString "Jeton d'identité de service (aura_...)"
    $secure | Export-Clixml -Path $TokenFile
    Protect-File $TokenFile
    Write-Host "Jeton enregistré dans $TokenFile (chiffré DPAPI, compte courant uniquement)."
    return
}

if ($Remove) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tâche « $TaskName » supprimée."
    } catch {
        & schtasks.exe /delete /tn $TaskName /f | Out-Null
        Write-Host "Tâche « $TaskName » supprimée (schtasks)."
    }
    return
}

if ($Install) {
    # Le jeton reste dans le fichier protégé : il n'apparaît ni dans la ligne de
    # commande de la tâche, ni dans l'historique du planificateur.
    $arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Settings $settings -Description "Mesure réseau Aura toutes les $IntervalMinutes minutes" `
            -Force | Out-Null
        Write-Host "Tâche « $TaskName » planifiée toutes les $IntervalMinutes minutes."
    } catch {
        # Sans élévation, l'enregistrement peut être refusé : schtasks fait le
        # même travail au niveau utilisateur.
        & schtasks.exe /create /tn $TaskName /sc minute /mo $IntervalMinutes `
            /tr "powershell.exe $arguments" /f | Out-Null
        Write-Host "Tâche « $TaskName » planifiée via schtasks (toutes les $IntervalMinutes min)."
    }
    Write-Host "Première mesure dans ~1 minute. CSV : $OutFile"
    return
}

# --- Mesure ---------------------------------------------------------------
try {
    $token = Read-AuraToken
    $row = Invoke-AuraMeasurement -Token $token
    New-AuraDirectory $OutFile
    if (Test-Path $OutFile) {
        $row | Export-Csv -Path $OutFile -Append -NoTypeInformation -Encoding UTF8
    } else {
        $row | Export-Csv -Path $OutFile -NoTypeInformation -Encoding UTF8
    }
    $row | Format-List
} catch {
    New-AuraDirectory $ErrorLog
    $line = "{0}`t{1}" -f (Get-Date).ToString("o"), $_.Exception.Message
    Add-Content -Path $ErrorLog -Value $line -Encoding UTF8
    Write-Error $_
    exit 1
}
