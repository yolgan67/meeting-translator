# Canlı Toplantı Çevirmeni (EN → TR)

Zoom/Teams toplantılarında **karşı tarafın İngilizcesini anlık olarak Türkçe altyazıya** çevirir
ve toplantı sonunda **zaman damgalı transkript** bırakır. Tamamen bilgisayarda çalışır:
internet, hesap, abonelik veya API anahtarı gerekmez. Ses kaydı tutulmaz, sadece metin.

- Sistem ses çıkışını dinler (WASAPI loopback) → **mikrofonun kaydedilmez**, sadece karşı taraf
- Ekranın altında her zaman üstte duran yarı saydam altyazı penceresi
- Üstte küçük İngilizce orijinal, altta büyük Türkçe çeviri
- **Ara altyazı:** cümlenin bitmesini beklemeden, konuşma sürerken ~1,2 saniyede bir
  o ana kadarki metin soluk renkte gösterilir; cümle bitince kesin metinle değişir
- `logs/<tarih_saat>/transcript.md` ve `transcript.jsonl`

## Kullanım

**En kolay yol:** `Toplanti-Cevirmeni.bat` dosyasına çift tıkla. PowerShell gerektirmez,
**konsol penceresi açılmaz** — açık tutman gereken bir pencere yok, uygulama arka planda
çalışır. (Sağ tık → Gönder → Masaüstü, ile kısayol yapabilirsin.)

- Başlangıç mesajları ve hatalar `logspp.log` dosyasına yazılır (1 MB'ı geçince
  `app.log.1` olarak devredilir).
- İkinci kez çift tıklarsan yeni kopya açılmaz; var olan pencere öne getirilir.
  (Aksi halde ikinci kopya ~570 MB'ı boşa yükler ve çeviri modeli belleğe sığmaz.)
- Kapatmak için altyazı çubuğundaki `×` veya `Ctrl+Shift+Q`.

**PowerShell'den** (klasörde sağ tık → "Terminalde aç"):

```powershell
.\run.ps1                    # overlay ile (normal kullanım)
.\run.ps1 -Console           # arayüz yok, konsola yazar
.\run.ps1 -Model small.en    # daha doğru, daha yavaş
.\run.ps1 -Engine none       # çeviri kapalı, sadece İngilizce transkript
```

Toplantı bitince pencereyi kapat (`×` veya `Ctrl+Shift+Q`). Transkript
`logs/<tarih_saat>/transcript.md` dosyasında; yolu `logs/app.log` içinde de yazılı.

### Ayarlar penceresi

Altyazı çubuğunun sağ üstündeki **dişli simgesine** (veya `Ctrl+Shift+S`) bas:

- **Görünüm modu:** iki dilli / sadece Türkçe / **sadece İngilizce**
- **Yazı boyutu:** Türkçe ve İngilizce satırlar için ayrı ayrı
- **Renkler:** Türkçe yazı, İngilizce yazı, arka plan (renk seçici ile)
- **Pencere genişliği ve yüksekliği** (kaydırıcı) — yükseklik kaydırıcısını
  oynatınca otomatik boyutlama kendiliğinden kapanır, pencere senin verdiğin
  boyda kalır
- **Saydamlık**, tutulan replik sayısı, ara altyazı açık/kapalı

Pencere yüksekliği replik sayısına ve yazı boyutuna göre kendini ayarlar (alt kenar
sabit kalır, yukarı doğru büyür). İstediğin sayı ekrana sığmıyorsa ayar penceresi
"yazı boyutunu küçült" diye uyarır; sabit yükseklik istersen `config.yaml` →
`ui.auto_height: false` ve `ui.height`.

Değişiklikler anında uygulanır; **Kaydet** ile `config.yaml`'a yazılır (dosyadaki
yorumlar korunur). "Varsayılana dön" ilk ayarlara döner.

**Sadece İngilizce modu** İngilizce çalışmak için: çeviri tamamen atlanır ve çeviri
modeli bellekten bırakılır — ölçüm: **~250 MB RAM serbest kalır**, CPU da düşer.
Türkçeye geri dönünce model otomatik yeniden yüklenir (~1 sn).

### Kısayollar (pencere odakta olmasa da çalışır)

| Kısayol | İşlev |
|---|---|
| `Ctrl+Shift+S` | Ayarlar penceresi |
| `Ctrl+Shift+L` | Mod değiştir (iki dilli → sadece TR → sadece EN) |
| `Ctrl+Shift+H` | Altyazıyı gizle / göster |
| `Ctrl+Shift+P` | Duraklat / devam |
| `Ctrl+Shift+Q` | Çık (transkripti yazar) |

Pencere kaybolursa `Altyazi-Geri-Getir.bat` (aşağıya bak).

### Altyazı ekrandan kayboldu mu?

Sırayla dene:

1. **`Ctrl+Shift+H`** — gizle/göster anahtarı, klavyeden. Pencere gizliyken de
   çalışır; test edildi (gerçek tarama kodlu tuş enjeksiyonuyla): gizleme ve geri
   getirme, `Ctrl+Shift+L` (mod) ve `Ctrl+Shift+S` (ayarlar) hepsi tetikleniyor.
   Durum çubuğunda "kısayollar sadece pencere odaktayken" yazıyorsa global kayıt
   olmamış demektir; o zaman 2. yolu kullan.
2. **`Altyazi-Geri-Getir.bat`** dosyasına çift tıkla. İki durumu da halleder:
   - Uygulama **açıksa**: pencereyi gösterir ve ekranın altına ortalar (~1 sn).
   - Uygulama **kapalıysa**: uygulamayı baştan başlatır.
3. Ayarlar penceresindeki **"Pencereyi ortala"** düğmesi — pencereyi sürükleyip
   kenara ittiysen.

Pencere artık ekran dışına tamamen taşınamaz: en az 240 px'i görünür kalacak
şekilde geri çekilir (başlık çubuğu olmadığı için tutamayacağın bir pencere
kurtarılamazdı).

**Ekran paylaşırken:** altyazı penceresi her zaman üstte olduğu için tüm ekranı paylaşıyorsan
karşı taraf da görür. `Ctrl+Shift+H` ile gizle. Tek pencere paylaşımında sorun yok.

## Nasıl çalışır

```
WASAPI loopback (48 kHz stereo → 16 kHz mono)
   │   boşta kalan süre yapay sessizlikle doldurulur (aşağıdaki nota bak)
   ▼
VAD segmenter   enerji tabanlı + histerezis, sessizlikte cümleyi kapatır
   ▼
faster-whisper — ara altyazı: tiny.en (hızlı) · kesin altyazı: base.en (doğru)
   │                             her ikisi de int8, 3 thread, + güven skoru filtresi
   ▼
opus-mt-tc-big-en-tr (CTranslate2 int8)   → Türkçe metin
   ▼
overlay (dişli simgesi: mod, yazı boyutu, renk)
   +  logs/<oturum>/transcript.jsonl (anında)  +  transcript.md (çıkışta)
```

PyTorch/transformers **kurulmaz**; her iki model de CTranslate2 üzerinde çalışır.

## Ölçülen performans (bu bilgisayarda: i7-1165G7, 16 GB)

| Ölçüm | Değer |
|---|---|
| **Ara altyazı gecikmesi** (son söylenen kelime → ekran) | **~1,0 sn** (ölçüm: kuyruk+ASR ort. 755 ms, + çeviri ~150 ms, + çizim ~100 ms) |
| Kesin (nihai) metin | cümle bittikten 0,7 – 1,2 sn sonra |
| Ara altyazı olmadan | 5 – 10 sn (cümlenin bitmesi beklenirdi) |
| ASR çağrı maliyeti (tampon uzunluğundan bağımsız) | tiny.en 0,5 – 0,7 sn · base.en 0,9 – 1,25 sn |
| Çeviri | cümle başına 60 – 250 ms |
| RAM | ~470 – 500 MB (tepe 555 MB) |
| CPU (ara altyazı açık, kesintisiz konuşma) | ort 1,07 çekirdek, tepe 1,9 çekirdek → sistemin %13'ü / tepe %24'ü |
| CPU (ara altyazı kapalı) | ort 0,4 çekirdek → sistemin %5'i |
| CPU (sessizken) | tek çekirdeğin %2-3'ü |
| Ayarlar penceresi | açıkken +1,2 MB, kapalıyken 0 |
| "Sadece İngilizce" moduna geçiş | −250 MB RAM (çeviri modeli bırakılır) |
| Süreç önceliği | BelowNormal → Teams/Zoom sesi önde kalır |
| Disk | modeller ~550 MB + bağımlılıklar ~450 MB |

`base.en` bu CPU'da gerçek zamanın 14 katı hızlı çalışıyor; doğruluk yetmezse
`-Model small.en` hâlâ rahat gerçek zamanlıdır (yaklaşık 3 kat yavaş).

## Çeviri kalitesi

Ölçtüğüm iki ana kayıp kaynağı ve yapılanlar:

**1) Beam search kapalıydı** (`beam_size: 1`). Gerçek hatalara yol açıyordu; beam 4
düzeltti ve **gecikme artmadı** (cümle başına 128 ms → 125 ms, çünkü çıktılar da
kısalıyor). beam 8'in belirgin üstünlüğü görülmedi.

**2) Toplantı deyimleri birebir çevriliyordu.** opus-mt iş jargonunda anlamsız
Türkçe üretiyor; çeviriden önce sade İngilizce'ye çevirme katmanı eklendi
(`src/phrases.py`, `translate.simplify_idioms`). Ekranda ve transkriptte gösterilen
İngilizce metin değişmez, sadeleştirme yalnızca çeviri motoruna giden kopyada olur.

| İngilizce | Önce | Sonra |
|---|---|---|
| align on the **scope** | ...**dürbün** üzerinde hizaya girmeliyiz | ...**kapsam** konusunda anlaşmamız gerekiyor |
| **touch base** after deploy | üsse dokunalım | kısaca konuşalım |
| that's **low-hanging fruit** | düşük asılı meyve | en kolay iş bu |
| **double-click** on that | çift tıklayabilir misiniz | daha ayrıntılı açıklayabilir misiniz |
| do you have **bandwidth** | bant genişliğiniz var mı | zamanınız var mı |
| **circle back** tomorrow | tekrar çember çizeceğim | yarın bu konuya dönelim |
| **park that** item | o eşyayı park edelim | bu öğeyi erteleyelim |

Liste ~70 kalıp içeriyor (`in the weeds`, `edge case`, `happy path`, `roll back`,
`nail down`, `off the top of my head`, `deployment` …). Kendi terimlerini
`config.yaml` → `translate.phrase_map` ile ekleyebilirsin, örn.
`{"our deck": "our slides"}`. Türkçe çıktıda tekrar eden bir kelimeyi
değiştirmek için `translate.post_map`, örn. `{"Salı": "Tuesday"}`.

Not: fiil biçimleri bilerek listede değil — "deployed"/"deploy" eşlemesi
`"We deployed the fix to prod"` gibi cümlelerde `prod` eşlemesiyle üst üste binip
bozuk çıktı veriyordu (ölçüldü).

### Daha da iyisi isteniyorsa

| Yol | Kazanç | Bedeli (ölçülen) |
|---|---|---|
| `asr.initial_prompt`'a jargon yaz (ürün adları, kısaltmalar) | Whisper terimleri doğru yazar | yok |
| `translate.engine: deepl` + DeepL Free anahtarı | YouTube/Google seviyesine en yakın çeviri | internet gerekir, metin dışarı gider, anahtar için kart doğrulaması |
| `asr.model: small.en` | transkript doğruluğu artar | **çağrı başına 3,8–4,2 sn** (base.en 0,7–1,4 sn) → gecikme 4 katına çıkar, önerilmez |
| `asr.beam_size: 3-5` | — | ölçtüm: kazanç yok, gürültülü sesde **daha kötü** ("my fellow" → "am I fellow") |
| NLLB-200 distilled 600M (yerel, daha büyük model) | — | ölçtüm: **daha kötü**. "circle back" → "yarın daireye dönelim", "bandwidth" → "bant genişliğine sahip misin", "trade-offs" → "anlaşmazlıklarını". Üstüne cümle başına 854 ms (opus-mt 186 ms) ve +711 MB RAM |

YouTube'daki çeviri Google Translate'tir: hem devasa bir çeviri modeli hem de çok
daha büyük bir konuşma tanıma modeli kullanır ve gerçek zamanlı olmak zorunda
değildir. Tamamen yerel ve ~1 sn gecikmeli bir sistemde ona birebir yetişmek
mümkün değil; en yakın nokta DeepL bağlamaktır.

## Ayarlar (`config.yaml`)

En çok işe yarayacak olanlar:

| Ayar | Anlamı | Ne zaman değiştir |
|---|---|---|
| `asr.model` | `tiny.en` / `base.en` / `small.en` | Kelimeler yanlış anlaşılıyorsa `small.en` |
| `segmenter.silence_ms` | Cümleyi bitiren sessizlik (700) | Cümleler bölünüyorsa artır, gecikme fazlaysa azalt |
| `segmenter.merge_below_s` | Bundan kısa parçalar bir sonrakiyle birleşir (2,0) | Tek kelimelik altyazılar çıkıyorsa artır |
| `asr.partial_model` | Ara altyazı modeli (`tiny.en`) | Ara satırlar çok hatalıysa `base.en` yap (gecikme ~2 katına çıkar) |
| `segmenter.partial_every_ms` | Ara altyazı sıklığı (600) | CPU kasıyorsa 1000-1500 yap veya `0` ile kapat |
| `segmenter.partial_window_s` | Ara altyazıda çözülen son N saniye (4,0) | Daha çok bağlam istiyorsan artır |
| `ui.show_partial` | Ara altyazı açık/kapalı | Soluk satır dikkatini dağıtıyorsa `false` |
| `asr.min_avg_logprob` | Uydurma cümle filtresi (−0,85) | Sessizlikte saçma altyazı çıkıyorsa −0,7'ye çek |
| `asr.partial_min_avg_logprob` | Ara altyazı filtresi (−0,6) | Ara satırlarda saçmalık varsa −0,4'e çek |
| `segmenter.vad_abs_floor` | Mutlak ses eşiği (0,0015) | Çok kısık sesli konuşmacılarda düşür |
| `ui.font_size_tr` / `ui.opacity` / `ui.color_tr` | Yazı boyutu / saydamlık / renk | Dişli simgesinden canlı değiştirilebilir |
| `ui.max_lines` / `ui.auto_height` | Ekranda kaç replik / pencerenin kendini boyutlaması | Sabit yükseklik istersen `auto_height: false` |
| `translate.engine` | `local` / `deepl` / `none` | DeepL anahtarın varsa `deepl` (daha iyi çeviri, internet gerekir) |
| `translate.beam_size` | Çeviri arama genişliği (4) | 1 daha hızlı ama belirgin daha hatalı |
| `translate.simplify_idioms` / `phrase_map` | Deyim sadeleştirme | Kendi jargonunu eklemek için |
| `asr.initial_prompt` | Whisper'a terim ipucu | Ürün/teknoloji adları yanlış yazılıyorsa |

## Sorun giderme

**"ses gelmiyor" (kırmızı nokta):** Windows ses çıkış cihazını değiştirdiysen uygulama
1 saniye içinde yeni cihaza bağlanır. Kulaklık takıp çıkarmak sorun değil. Hâlâ gelmiyorsa
`.venv\Scripts\python tools\selftest.py --audio` ile hangi cihazın dinlendiğini gör.

**Sessizlikte saçma altyazı:** Loopback bilgisayarda çalan *her* sesi duyar (YouTube, bildirim).
Ölçümde 60 saniye sessizlikte sıfır yanlış altyazı çıktı, ama başka bir uygulama arka planda
ses çalıyorsa transkripte girer. `Ctrl+Shift+P` ile duraklat veya `asr.min_avg_logprob`'u yükselt.

**Altyazı çok geç geliyor:** Ara altyazı kapalıysa (`ui.show_partial: false` veya
`partial_every_ms: 0`) altyazı ancak konuşmacı sustuğunda gelir; ortalama cümle 5 saniye
sürdüğü için bu 5-8 saniye gibi hissedilir. Ara altyazıyı aç, ya da `segmenter.max_segment_s`
ve `silence_ms` değerlerini düşür.

**Gecikme birikiyor (sarı nokta):** Kuyruk dolarsa en eski cümle düşürülür, altyazı gerçek
zamana yakın kalır. Sürekli sarıysa `asr.model: tiny.en` yap veya `cpu_threads`'i düşür.

**"Ceviri modeli bellege sigmadi" uyarısı:** Uygulamanın iki kopyası birden açıksa ikincisi
çeviri modelini yükleyemez (fp16 model ~490 MB RAM ister) ve sadece İngilizce transkript
gösterir. Diğer pencereyi kapat, ya da hafif modele geç:
`.\.venv\Scripts\python tools\convert_mt_model.py --light --force` (Argos, int8, ~100 MB;
RAM'i yarılar, çeviri kalitesi bir tık düşer).

**Kısayollar çalışmıyor:** `keyboard` kütüphanesi global kısayol kuramadıysa durum çubuğunda
"kısayollar sadece pencere odaktayken" yazar; pencereye tıklayınca kısayollar çalışır.

## RAM darsa

Uygulama ~550 MB ister. Makinede boş yer azsa:

```powershell
.\tools\free-ram.ps1          # rapor: ne ne kadar yiyor, ne kapatilabilir
.\tools\free-ram.ps1 -Close   # guvenli listeyi onay isteyerek kapatir
```

Betik Chrome / VS Code / Teams / Zoom'a dokunmaz (kaydedilmemiş iş olabilir), onları
kendin kapatırsın. Uygulamanın kendi ayağını küçültmek için:

| Değişiklik | Kazanç | Bedeli |
|---|---|---|
| `tools\convert_mt_model.py --light --force` | ~250 MB | çeviri bir tık basitleşir |
| `config.yaml` → `asr.partial_model: ""` | ~50 MB | ara altyazı gecikmesi ~2 katına çıkar |
| `config.yaml` → `translate.engine: none` | ~490 MB | çeviri yok, sadece İngilizce transkript |

## Testler

```powershell
# Deterministik regresyon: bir WAV'ı zincirden geçirir, kelime kapsamasını ölçer
.\.venv\Scripts\python tools\offline_test.py --wav ornek.wav --ref "beklenen ingilizce metin"

# Bileşen testleri
.\.venv\Scripts\python tools\selftest.py --audio      # loopback cihazı ve seviye
.\.venv\Scripts\python tools\selftest.py --asr        # model yükleme + sessizlik filtresi
.\.venv\Scripts\python tools\selftest.py --translate  # çeviri kalitesi ve hızı
.\.venv\Scripts\python tools\selftest.py --file x.wav # uçtan uca gecikme
```

`offline_test.py` sesi 1.0 / 0.3 / 0.1 kat seviyelerde dener; kayıtlı sonuç her seviyede
**%100 kelime kapsaması** (x0.01 gibi aşırı kısık seviyede %95).

Ara altyazının etkisi kesintisiz konuşmada ölçüldü: ilk metin 2,3 sn'de ekranda,
kesin metin 10,1 sn'de (ara altyazı olmasa tek görünen o olurdu).

## Geliştirme sırasında bulunan ve düzeltilen beş sorun

Bunlar kodda yoruma da yazıldı, çünkü ayarlarla oynarken geri gelebilirler:

1. **Marian `</s>` eksikliği** — Çeviri modeline cümle sonu jetonu verilmeyince decoder durmuyor
   ve aynı ifadeyi onlarca kez tekrarlıyordu. `src/translate.py` artık `</s>` ekliyor.
2. **WASAPI loopback boşta veri üretmiyor** — Çıkış cihazı sessizken hiç blok gelmediği için
   zaman çizgisi kayıyor, "sessizlik = cümle bitti" kuralı tetiklenmiyor ve sesin %45'i
   kayboluyordu. `src/audio_capture.py` eksik süreyi yapay sessizlikle dolduruyor.
3. **Cümle sonunu beklemek** — İlk gerçek toplantıda 6-7 saniyelik gecikme hissedildi.
   Log analizi gösterdi ki işlem gecikmesi sadece 0,79 sn, ama cümleler ortalama 5,3 sn
   (tepe 7,8 sn) sürüyordu ve altyazı ancak cümle bitince basılıyordu. Çözüm: ara altyazı
   (`segmenter.partial_every_ms`). Ölçüm: algılanan gecikme 9,6 sn → 2,3 sn.
4. **Whisper'ın çağrı başına sabit maliyeti** — Ara altyazı eklendikten sonra gecikme
   hâlâ 2-3 saniyeydi. Ölçüm, sebebin tampon uzunluğu değil **modelin çağrı başına sabit
   maliyeti** olduğunu gösterdi: Whisper her çağrıda sesi 30 saniyeye doldurup işliyor,
   bu yüzden 1 saniyelik ses de 4 saniyelik ses de aynı sürüyor (base.en ~1,1 sn).
   Çözüm: ara altyazı için `tiny.en`, kesin altyazı ve log için `base.en`.
   Ölçüm: 755 ms ortalama → toplam ~1 sn.
5. **Whisper'ın kendi `vad_filter`'ı** — Kendi VAD'imizin üstüne binince kısık sesli gerçek
   konuşmayı tamamen siliyordu. Kapatıldı; uydurma cümleleri `avg_logprob` / `no_speech_prob`
   filtresi tutuyor (ölçüm: gerçek konuşma −0,07…−0,48, uydurma −1,03…−1,61).

## Sınırlar

- Sadece **İngilizce → Türkçe**. Karşı taraf başka dil konuşursa `asr.language` ve çeviri
  modeli değişmeli.
- Kimin konuştuğu ayırt edilmez (speaker diarization yok).
- Loopback tüm sistem sesini alır; belirli bir uygulamayı izole etmez.
- Modellerin ilk indirilmesi internet gerektirir (~550 MB), sonrası tamamen çevrimdışı.
