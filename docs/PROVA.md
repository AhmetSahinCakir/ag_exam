# Prova ve Test Listesi

Gerçek sınavdan önce **her sınıfta bir kez** bu listeyi uygulayın. En az 3 öğrenci
bilgisayarı (mümkünse biri Windows 10, biri Windows 11) ve sınıfın kendi modemi gerekir.

Bölümler:

1. [Neler otomatik sınandı, neler sınanmadı](#1-neler-otomatik-sınandı-neler-sınanmadı)
2. [Öğrenci bilgisayarı olmadan hızlı deneme](#2-öğrenci-bilgisayarı-olmadan-hızlı-deneme)
3. [Kabul kriterleri](#3-kabul-kriterleri)
4. [Doğrulanması gereken riskler](#4-doğrulanması-gereken-riskler)

---

## 1. Neler otomatik sınandı, neler sınanmadı

**Geliştirme sırasında gerçekten çalıştırılarak sınananlar** (Linux üzerinde, gerçek
MediaMTX v1.21.4, ffmpeg ve Chromium ile):

- Sunucu: giriş, liste kuralları, durum makinesi, teslim adlandırma, `_v2` sürümleri,
  `index.csv`, aynı SHA-256 ve boş teslim uyarıları, MAC/ikinci oturum uyarıları, kopma
  tespiti, yeniden başlatmada durumun geri yüklenmesi, arşivleme, panelin yalnızca
  `localhost`'tan erişilebilmesi → `server/tests` (42 test).
- `mediamtx.yml`: yayın yetkisi (yanlış şifre ve `s/` dışı yollar reddediliyor), fMP4 kayıt,
  denetim API'si, yalnızca yerel WebRTC.
- Panel: gerçek tarayıcıda 35 eşzamanlı WebRTC görüntüsü, uyarı akışı, büyütme, dosya/liste
  yükleme, başlat/bitir, CSV, yeni sınav; sayfanın **hiçbir dış adrese istek yapmadığı**.
- Ajanın platformdan bağımsız çekirdeği (`agent/Core`): UDP keşif, API istemcisi (giriş,
  heartbeat, olay, dosya indirme, teslim), izin listesi eşleştirme (Türkçe Windows'taki
  I/İ sorunu dahil), 5 saniye toleransı ve kapatma kuralları, ffmpeg komut satırı →
  `agent/tests/CoreSmoke`.

**Windows gerektirdiği için yalnızca derlenip gerçek ortamda çalıştırılamayanlar** — bu
provada asıl bakılacak yerler:

- Ajanın arayüzü ve akışı (keşif ekranı → onay → giriş → bekleme → geri sayım → yan panel).
- `gdigrab` ile ekran yakalama (çoklu monitör, yüksek DPI ölçekleme).
- Pencere/süreç denetimi: izinsiz programın kapatılması, öndeki pencere tespiti, Microsoft
  Store uygulamaları, yükseltilmiş (yönetici) süreçler.
- Job Object ile ffmpeg'in ajanla birlikte kapanması.
- Packet Tracer'ın bulunup sınav dosyasıyla açılması.
- `start-teacher.bat` ve güvenlik duvarı kuralları.

## 2. Öğrenci bilgisayarı olmadan hızlı deneme

Öğretmen bilgisayarında, `start-teacher.bat` çalışırken ikinci bir komut penceresinde:

```bat
.venv\Scripts\python server\tests\sim_agent.py --count 5 --stream --kill-event
```

Bu **simülatör** gerçek ajanın ağ davranışını taklit eder (keşif → giriş → heartbeat →
test görüntüsü yayını → sınav dosyasını indirme → otomatik teslim). `--stream` için
`ffmpeg.exe`'nin PATH'te olması gerekir (`scripts\fetch-ffmpeg.ps1` ile indirip
`agent\` klasörünü PATH'e ekleyebilirsiniz). Panelde 5 kutu ve canlı test görüntüsü
görmelisiniz. `--count 35` ile panelin ve bilgisayarınızın 35 yayını kaldırıp kaldırmadığını
ölçebilirsiniz (bkz. Risk 3). `--submit` sınav başlayınca teslim de yapar.

Sunucu testleri:

```bat
.venv\Scripts\python -m pip install -r server\requirements-dev.txt
.venv\Scripts\python -m pytest server\tests
```

Ajan çekirdek testleri (.NET 8 SDK gerekir; sondaki `discover` çalışan sunucuya karşı da dener):

```bat
dotnet run --project agent\tests\CoreSmoke -- discover
```

## 3. Kabul kriterleri

Her maddeyi deneyip işaretleyin.

- [ ] **1. Yönetici olmadan açılmıyor.** Bir komut penceresinde
      `set __COMPAT_LAYER=RunAsInvoker` yazıp aynı pencereden `SinavAjan.exe`'yi çalıştırın
      (bu, yönetici istemini atlatır). “Bu program yönetici olarak çalıştırılmalıdır. Sağ
      tık → Yönetici olarak çalıştır.” mesajı çıkmalı, program kapanmalı, **panelde kimse
      görünmemeli**. (Normal çift tıklamada Windows zaten yönetici izni ister; “Hayır”
      derseniz program hiç başlamaz.)
- [ ] **2. Otomatik keşif.** Ajan IP girmeden sunucuyu buluyor ve `config.yaml`'daki sınıf /
      öğretmen adını büyük harflerle gösteriyor.
- [ ] **3. İki modem, iki sunucu.** İki sınıfın modemi ve öğretmen bilgisayarı açıkken
      (`sinif_adi` farklı) her ajan **yalnızca kendi modemindeki** sunucuyu görüyor. Bir
      öğrenci bilgisayarını diğer modeme bağlayıp ajanı yeniden açınca diğer sınıfın adı
      çıkmalı.
- [ ] **4. Güvenlik duvarı açıkken çalışıyor.** Öğretmen bilgisayarında Windows Güvenlik
      Duvarı açık; `start-teacher.bat` “Güvenlik duvarı kuralları hazır” yazdıktan sonra
      keşif, giriş ve görüntü çalışıyor. Denetim: yönetici komut penceresinde
      `netsh advfirewall firewall show rule name=all | findstr /c:"Sinav Izleme"` üç kuralı
      listelemeli.
- [ ] **5. 10 saniyede canlı görüntü.** 3 ayrı bilgisayardan giriş yapılınca 10 saniye
      içinde panelde üçünün de canlı görüntüsü geliyor.
- [ ] **6. IP / bilgisayar adı / MAC.** Her kutuda üçü de görünüyor. Aynı bilgisayarda
      ajanı kapatıp **başka bir numarayla** giriş yapınca kırmızı uyarı çıkıyor: “Bu
      bilgisayardan daha önce … giriş yapmıştı”.
- [ ] **7. Chrome kapanıyor.** Sınav başladıktan sonra Chrome açılınca 1–2 saniyede
      kapanıyor, öğrencide “… sınav sırasında kullanılamaz.” bildirimi, panelde
      “chrome.exe kapatıldı” uyarısı çıkıyor.
- [ ] **8. Router CLI uyarı vermiyor.** Packet Tracer'da bir router'a tıklayıp CLI
      sekmesini / ayrı CLI penceresini açınca uyarı **çıkmıyor**.
- [ ] **9. Başlat menüsü toleransı.** Başlat menüsünü 2 saniye açıp kapatınca uyarı
      çıkmıyor. Not Defteri açılınca kapanıyor ve uyarı çıkıyor (Windows 10 **ve** 11'de
      deneyin). Dosya Gezgini'ni 6–7 saniye önde tutunca “Packet Tracer dışında bir pencere
      önde: explorer.exe” uyarısı çıkıyor.
- [ ] **10. Wi-Fi kesintisi.** Öğrencide Wi-Fi'yı kapatın: yaklaşık 10 saniyede kutu
      kırmızıya dönüyor. Wi-Fi'yı açın: kutu yeşile dönüyor, görüntü geri geliyor ve
      `recordings\s\<numara>\` altında yeni bir kayıt dosyası başlıyor.
- [ ] **11. Ajanı Görev Yöneticisi'nden sonlandırma.** Kutu kırmızıya dönüyor; öğrencide
      Görev Yöneticisi → Ayrıntılar'da **`ffmpeg.exe` de kalmamış** olmalı.
- [ ] **12. Dosya adı.** Teslim `submissions\<numara>_<AdSoyad>.pka` olarak kaydediliyor;
      “Şükrü Çağrı Işık” gibi bir adla deneyin → `…_SukruCagriIsik.pka`.
- [ ] **13. Otomatik toplama.** Bir öğrenci teslim etmeden “Sınavı bitir”e basın: dosyası
      otomatik geliyor, olay kaydında “Otomatik teslim alındı” yazıyor, ajanı “Sınav sona
      erdi” deyip kapanıyor.
- [ ] **14. Kayıtlar oynuyor.** `recordings\s\<numara>\` altındaki `.mp4` dosyaları VLC'de
      oynuyor.
      *(Not: tanımda `recordings\<numara>\` yazıyordu; MediaMTX kayıt yolunda yayın yolunun
      tamamını — `s/<numara>` — zorunlu tuttuğu için klasör `recordings\s\<numara>\` oldu.)*
- [ ] **15. İnternetsiz çalışma.** Modemin internet kablosu çıkarılmışken tüm akış
      çalışıyor. Panelde F12 → Ağ (Network) sekmesinde yalnızca `localhost:8000` ve
      `127.0.0.1:8889` adreslerine istek olmalı.
- [ ] **16. İz kalmıyor.** Ajan kapandıktan sonra öğrenci bilgisayarında: Görev
      Yöneticisi'nde `SinavAjan.exe` / `ffmpeg.exe` yok; *Başlangıç uygulamaları*,
      *Hizmetler* ve *Görev Zamanlayıcı*'da ajana ait kayıt yok. “Sınav dosyalarımı
      temizle”den sonra `%LOCALAPPDATA%\SinavAjan` klasörü yok.

Ek denemeler (önerilir):

- [ ] Aynı numarayla ikinci bir bilgisayardan giriş **reddediliyor**, panelde uyarı çıkıyor.
- [ ] Sınav sırasında ajanı kapatıp yeniden açınca (aynı numara) kaydedilmiş `sinav.pka`
      **korunuyor**, yeniden indirilmiyor.
- [ ] Hiç kaydetmeden “Teslim et” → “Önce Packet Tracer'da Ctrl+S ile kaydedin.”
- [ ] İki öğrenci aynı dosyayı teslim edince kırmızı “birebir aynı dosya” uyarısı; hiç
      değiştirmeden teslimde “sınav dosyasıyla birebir aynı” uyarısı.
- [ ] İkinci monitör takınca “Monitör sayısı: 2” uyarısı.
- [ ] Sınav sırasında `start-teacher.bat` penceresini kapatıp yeniden açın: sınav
      **SÜRÜYOR** olarak geri geliyor, öğrenciler birkaç saniyede yeniden yeşil oluyor.
- [ ] Sınav başında **sürekli tekrarlayan** “… kapatıldı” uyarısı var mı? Varsa o program
      kendini yeniden başlatıyordur; `config.yaml` → `kapatma_disi` listesine ekleyin.

## 4. Doğrulanması gereken riskler

### Risk 1 — Packet Tracer CLI pencereleri ve yardımcı süreçler

Packet Tracer açıkken Görev Yöneticisi → Ayrıntılar'da “Komut satırı” sütununu açın.
`PacketTracer.exe` ve varsa yardımcı süreçlerin (`QtWebEngineProcess.exe` vb.) yolunun
`C:\Program Files\Cisco Packet Tracer …\` altında olduğunu doğrulayın; izin listesi klasör
kuralıyla bunların hepsini kapsar. Router/switch CLI penceresi, PC masaüstü (Command Prompt,
Web Browser) pencerelerini açıp panelde uyarı çıkmadığına bakın (kriter 8).
Packet Tracer başka bir klasöre kuruluysa (`D:\…`) o klasörü `izin_listesi`ne ekleyin; aksi
hâlde **Packet Tracer'ın kendisi kapatılır**.

### Risk 2 — Packet Tracer girişi

Packet Tracer açılışta Cisco hesabıyla giriş ister ve bunun için tarayıcı açabilir. Giriş
**bekleme aşamasında** yapılmalıdır (OGRENCI.md'de yazıyor). Provada şunu özellikle deneyin:
öğrenci bekleme aşamasında giriş yapıp “Keep me logged in”i açtıktan sonra sınav
başladığında ajanın açtığı **yeni** Packet Tracer penceresi yeniden giriş istiyor mu?
İstiyorsa öğrencilere bekleme aşamasında Packet Tracer'ı **kapatmamalarını**, sınav
başlayınca ajanın açtığı pencereyi kapatıp kendi açık pencerelerinde *File → Open* ile
`%LOCALAPPDATA%\SinavAjan\<numara>\sinav.pka` dosyasını açmalarını söyleyin.

### Risk 3 — Panel performansı (35 WebRTC görüntüsü)

Geliştirme ortamında 35 yayın tek tarayıcıda oynatıldı (toplam ~175 kare/sn çözüldü),
ancak bu ölçüm sizin bilgisayarınızı temsil etmez. Öğretmen bilgisayarında
`sim_agent.py --count 35 --stream` ile (ya da gerçek sınıfla) deneyin; Görev Yöneticisi'nde
tarayıcının işlemci kullanımına ve görüntülerin akıcılığına bakın. Zorlanıyorsa:
**Görünmeyen kutuları duraklat** kutusunu işaretleyin, **Kutu boyutu**'nu küçültün,
gerekirse `yayin.genislik: 960` yapın.

### Risk 4 — Ağ kapasitesi

35 öğrenci × 500 kbps ≈ **17,5 Mbps** sürekli Wi-Fi yüklemesi. Gerçek sınıfla en az 10 dakika
deneyin: kutular kırmızıya dönüp duruyor mu, görüntüler donuyor mu, `data\mediamtx.log`
içinde sık kopma var mı? Sorun varsa `config.yaml` → `yayin` altından düşürün
(ör. `fps: 3`, `genislik: 960`, `bitrate_kbps: 300` → toplam ~10 Mbps). Öğretmen
bilgisayarını modeme kabloyla bağlamak Wi-Fi yükünü yarıya indirir.

### Risk 5 — Ekran ölçeklemesi (DPI)

Ölçeklemesi %125 / %150 olan bir dizüstünde panelde büyütülmüş görüntüye bakın: ekranın
**tamamı** (görev çubuğu ve sağ alt köşe dahil) görünmeli, kırpık olmamalı. İki monitörlü
bir bilgisayarda iki ekran yan yana tek görüntü olarak gelmeli. Kırpılma görürseniz
bildirin; bu durumda yakalama yöntemi değiştirilmelidir.

### Risk 6 — UDP yayını ve AP izolasyonu

Modemde “AP izolasyonu / istemci izolasyonu” açıksa **sistem hiç çalışmaz** (bkz.
KURULUM.md). Deneme: iki öğrenci bilgisayarı birbirine `ping` atabiliyor mu? Atamıyorsa
izolasyon açıktır. Keşif çalışmıyor ama elle IP ile bağlanılabiliyorsa modem yalnızca
yayın (broadcast) paketlerini engelliyordur; öğrenciler elle IP girerek devam edebilir.

### Risk 7 — Antivirüs

Öğrenci bilgisayarlarındaki antivirüsler (özellikle üçüncü taraf olanlar) imzasız
`SinavAjan.exe`'yi veya `ffmpeg.exe`'yi engelleyebilir ya da silebilir. Provada farklı
antivirüsleri olan bilgisayarlarla deneyin. Çözüm antivirüsü kapatmak **değil**, ajan
klasörünü istisna olarak eklemektir (adımlar OGRENCI.md'de).

### Bilinen davranışlar

- **UAC siyah kare:** Yönetici onayı (UAC) penceresi açıkken Windows güvenli masaüstüne
  geçer; o anlarda görüntü siyah gelebilir. Normaldir.
- **Kopma süresi:** Kutu, son sinyalden 10 saniye sonra kırmızıya döner (sinyaller 2
  saniyede bir gelir; Wi-Fi kesildikten sonra 8–11 saniye sürer).
- **Kilit ekranı / uyku:** Bilgisayar kilitlenirse görüntü kilit ekranını gösterir ve “önde:
  LockApp.exe” uyarısı çıkar; uyursa kutu kırmızıya döner.
