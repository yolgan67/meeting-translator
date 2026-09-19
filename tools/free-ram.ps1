# Toplanti oncesi RAM raporu ve (istege bagli) temizlik.
#
#   .\tools\free-ram.ps1           # sadece rapor, hicbir sey kapatmaz
#   .\tools\free-ram.ps1 -Close    # gereksiz uygulamalari onay isteyerek kapatir
#
# Teams, Zoom, Chrome ve VS Code'a ASLA dokunulmaz (icinde kaydedilmemis isin olabilir);
# onlari kendin kapatirsin.

param([switch]$Close)

$SAFE_TO_CLOSE = @(
    @{ Name = "DeepL";          Aciklama = "ceviriyi bu uygulama zaten yapiyor" },
    @{ Name = "WhatsApp";       Aciklama = "telefondan takip edilebilir" },
    @{ Name = "WhatsApp.Root";  Aciklama = "WhatsApp arka plan sureci" },
    @{ Name = "Slack";          Aciklama = "toplanti sirasinda gerekli degilse" },
    @{ Name = "claude";         Aciklama = "DIKKAT: Claude Code bu uygulamadan calisiyorsa oturum kapanir" },
    @{ Name = "M365Copilot";    Aciklama = "Microsoft Copilot" },
    @{ Name = "Spotify";        Aciklama = "sesi de transkripte karisir" }
)

function Show-Memory {
    $os = Get-CimInstance Win32_OperatingSystem
    $total = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    $free  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    Write-Host ("RAM: {0} GB toplam, {1} GB bos (kullanim %{2:N0})" -f `
        $total, $free, ((1 - $free / $total) * 100)) -ForegroundColor Cyan
    return $free
}

$freeBefore = Show-Memory
Write-Host ""
Write-Host "--- En cok RAM kullananlar ---"
Get-Process | Where-Object { $_.WorkingSet64 -gt 50MB } |
    Group-Object ProcessName |
    ForEach-Object {
        [pscustomobject]@{
            Uygulama = $_.Name
            RAM_MB   = [math]::Round((($_.Group | Measure-Object WorkingSet64 -Sum).Sum) / 1MB, 0)
            Surec    = $_.Count
        }
    } | Sort-Object RAM_MB -Descending | Select-Object -First 12 | Format-Table -AutoSize

# Uygulamanin kendi ihtiyaci
Write-Host "Bu uygulamanin ihtiyaci: ~550 MB (base.en + tiny.en + ceviri modeli)"
Write-Host "  Daha az icin: config.yaml -> asr.partial_model: ''  (~50 MB kazanc)"
Write-Host "  Daha az icin: tools\convert_mt_model.py --light --force  (~250 MB kazanc)"
Write-Host ""

$adaylar = @()
foreach ($item in $SAFE_TO_CLOSE) {
    $procs = Get-Process -Name $item.Name -ErrorAction SilentlyContinue
    if ($procs) {
        $mb = [math]::Round((($procs | Measure-Object WorkingSet64 -Sum).Sum) / 1MB, 0)
        $adaylar += [pscustomobject]@{ Name = $item.Name; MB = $mb; Aciklama = $item.Aciklama }
    }
}

if (-not $adaylar) {
    Write-Host "Kapatilabilecek gereksiz uygulama bulunamadi." -ForegroundColor Green
    Write-Host "Kalan buyuk tuketiciler (Chrome / VS Code / Teams) elle kapatilmali."
    return
}

Write-Host "--- Kapatilabilir (guvenli liste) ---"
$adaylar | Format-Table -AutoSize
$toplam = ($adaylar | Measure-Object MB -Sum).Sum
Write-Host ("Kapatilirsa kazanc: ~{0} MB" -f $toplam) -ForegroundColor Yellow

if (-not $Close) {
    Write-Host ""
    Write-Host "Kapatmak icin: .\tools\free-ram.ps1 -Close" -ForegroundColor Cyan
    return
}

Write-Host ""
foreach ($a in $adaylar) {
    if ($a.Name -eq "claude") {
        Write-Host "UYARI: Claude Code'u bu uygulamanin icinden kullaniyorsan kapatmak oturumu bitirir." -ForegroundColor Yellow
    }
    $yanit = Read-Host ("{0} ({1} MB) kapatilsin mi? [e/H]" -f $a.Name, $a.MB)
    if ($yanit -eq "e" -or $yanit -eq "E") {
        # Once nazikce kapat (kaydedilmemis is icin sansi olsun), sonra kontrol et.
        Get-Process -Name $a.Name -ErrorAction SilentlyContinue |
            ForEach-Object { $null = $_.CloseMainWindow() }
        Start-Sleep -Seconds 2
        $kalan = Get-Process -Name $a.Name -ErrorAction SilentlyContinue
        if ($kalan) {
            Write-Host ("  {0} hala acik; arka plan surecleri kapatiliyor." -f $a.Name)
            $kalan | Stop-Process -Force -ErrorAction SilentlyContinue
        }
        Write-Host ("  {0} kapatildi." -f $a.Name) -ForegroundColor Green
    }
}

Write-Host ""
$freeAfter = Show-Memory
Write-Host ("Kazanilan: {0:N1} GB" -f ($freeAfter - $freeBefore)) -ForegroundColor Green
