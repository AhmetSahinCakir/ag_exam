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

- Sunucu: giriş, liste kuralları, durum makinesi, sınav klasörü (`Kayıtlar` + `Teslimler`),
  teslim adlandırma, `_v2` sürümleri, `index.csv`, yüklemenin özetle ve klasörden geri
  okunarak doğrulanması, teslim klasörü denetimi (dosya kaybolursa / elle konursa), aynı
  SHA-256, boş teslim, şüpheli boyut ve eski dosya uyarıları, MAC/ikinci oturum uyarıları,
  kopma tespiti, başka masaüstü uyarısı, sınıf/öğretmen adının panelden değiştirilmesi,
  yeniden başlatmada durumun geri yüklenmesi, panelin yalnızca `localhost`'tan
  erişilebilmesi; başlangıç planlama, isteğe bağlı süre, ek süre ve kayıt seçeneği; geç teslim, öğrenci başına uyarı dosyaları, sınavın herkes için kapatılması ve sistemin kapatılması → `server/tests` (62 test).
- `mediamtx.yml`: yayın yetkisi (yanlış şifre ve numara dışı yollar reddediliyor), kaydın
  sınav klasörü seçilince çalışırken açılması ve `Kayıtlar\<numara>\` altına yazılması
  (Türkçe harfli ve boşluklu klasör adıyla), teslim edenin yayınının durdurulması, denetim
  API'si, yalnızca yerel WebRTC.
- Panel: gerçek tarayıcıda canlı WebRTC görüntüleri, sınıf/öğretmen adını düzenleme, sınav
  klasörü, tek satırlık öğrenci listesi ve düz uyarı listesi, ekran boyutu denetimi, büyütme,
  dosya/liste yükleme, başlat/bitir, yeni sınav; sayfanın **hiçbir dış adrese istek yapmadığı**.
- Ajanın platformdan bağımsız çekirdeği (`agent/Core`): UDP keşif, API istemcisi (giriş,
  heartbeat, olay, dosya indirme, teslim), teslim öncesi dosya denetimi kuralları, izin
  listesi eşleştirme (Türkçe Windows'taki I/İ sorunu dahil), 5 saniye toleransı ve kapatma
  kuralları, ffmpeg komut satırı → `agent/tests/CoreSmoke`.

**Gerçek Windows üzerinde otomatik sınananlar** (GitHub Actions, Windows Server 2025;
`agent/tests/E2E/windows-e2e.ps1` her derlemede `SinavAjan.exe`'yi çalıştırıp arayüzünü bir
öğrenci gibi kullanır):

- Panelden değiştirilen sınıf/öğretmen adının ajanda görünmesi; “Klasör seç”in Windows'un
  klasör penceresini açması; sınav klasöründe `Kayıtlar` ve `Teslimler`in oluşması.
- Yönetici olarak açılma, keşif, sınıf/öğretmen onayı, giriş; IP, bilgisayar adı ve MAC kaydı.
- `ffmpeg gdigrab` ile ekranın yakalanıp MediaMTX'e yayınlanması ve sınav klasörüne
  kaydedilmesi; ffmpeg'in görünür bir pencere açmaması.
- Bekleme aşamasında hiçbir programın kapatılmaması ve ekranın kaydedilmemesi; planlanan
  başlangıç saatinin ajanda görünmesi; sınav başlayınca geri sayım, sınav paneli
  (küçültülebilir; süre verildiyse “Kalan süre” yazar), “Sınav dosyasını indir” ile dosyanın
  öğrencinin seçtiği yere kaydedilmesi.
- Not Defteri ve Chrome'un kapatılması, öğrenciye bildirim, panelde uyarı.
- Öndeki pencere toleransı: 2,5 sn'lik geçişte uyarı yok, 5 sn'den sonra uyarı var;
  `C:\Windows` altındaki programın kapatılmaması.
- Başka bir sanal masaüstüne geçince uyarı (test makinesi sanal masaüstü açabiliyorsa).
- Teslimde dosya seçme penceresi; değiştirilmemiş sınav dosyası, sınavdan önce kaydedilmiş
  dosya ve `.pka` olmayan dosya için uyarılar; doğru dosyada onay ve teslim (öğrenciye SHA
  gösterilmez), `Teslimler` klasöründe Türkçe karakterleri çevrilmiş dosya adı, yayının
  durması, ajanın kapanması, ffmpeg'in kapanması, servis/başlangıç kaydı/zamanlanmış görev
  kalmaması.
- Teslim klasörü denetimi: dosya klasörden alınınca “Dosya klasörde yok”, geri konunca
  “Teslim etti”; klasöre elle konan dosyanın teslim sayılması ve o öğrencinin ajanının
  kendiliğinden “Teslim alındı” deyip kapanması.
- Ajan zorla sonlandırılınca ffmpeg'in de kapanması (Job Object) ve kutunun kırmızıya dönmesi.
- Ek süre verilince öğrencideki kalan sürenin artması; sınav bitince programın kapanmaması,
  izinsiz programların kapatılmaya devam etmesi, geç teslimin alınıp işaretlenmesi; öğrenci
  başına uyarı dosyaları (`Uyarılar`); “Ekranları kaydet” seçilmeden başlatılan sınavda kayıt
  yapılmaması.
- Panelin kendi penceresinde (Edge, sekmesiz) açılması; pencere kapanınca öğretmen
  bilgisayarında çıkan soru; “Sistemi kapat” ile açık öğrenci programının kapanması
  (otomatik teslim yapılmaması) ve sunucunun kendiliğinden kapanması.
- `start-teacher.bat` güvenlik duvarı kurallarının eklenmesi; sunucu testleri (Windows, Python 3.11).

**Otomatik sınanamayanlar** — bu provada asıl bakılacak yerler:

- **Packet Tracer'ın kendisi:** indirilen dosyanın açılması, CLI pencereleri, giriş.
  (Test ortamında Packet Tracer kurulu değildir.)
- Gerçek Wi-Fi ve modem: keşif yayını, AP izolasyonu, 35 öğrencilik yük.
- Windows 10 ve Windows 11 dizüstüleri: yüksek DPI ölçekleme, çoklu monitör, Microsoft
  Store uygulamaları, üretici yardımcı programları, antivirüsler.
- `start-teacher.bat`'ın ilk kurulum adımları (Python ortamı, MediaMTX indirme).
- Öğretmen bilgisayarındaki tarayıcının 35 görüntüyü kaldırması.

## 2. Öğrenci bilgisayarı olmadan hızlı deneme

Öğretmen bilgisayarında, `start-teacher.bat` çalışırken ikinci bir komut penceresinde:

```bat
.venv\Scripts\python server\tests\sim_agent.py --count 5 --stream --kill-event
```

Bu **simülatör** gerçek ajanın ağ davranışını taklit eder (keşif → giriş → heartbeat →
test görüntüsü yayını → sınav dosyasını indirme → teslim). `--stream` için
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
- [ ] **2. Otomatik keşif.** Ajan IP girmeden sunucuyu buluyor ve panelde yazdığınız sınıf /
      öğretmen adını büyük harflerle gösteriyor. (Panelde **Düzenle** ile adı değiştirip
      ajanı yeniden açınca yeni ad görünmeli.)
- [ ] **3. İki modem, iki sunucu.** İki sınıfın modemi ve öğretmen bilgisayarı açıkken
      (sınıf adları farklı) her ajan **yalnızca kendi modemindeki** sunucuyu görüyor. Bir
      öğrenci bilgisayarını diğer modeme bağlayıp ajanı yeniden açınca diğer sınıfın adı
      çıkmalı.
- [ ] **4. Güvenlik duvarı açıkken çalışıyor.** Öğretmen bilgisayarında Windows Güvenlik
      Duvarı açık; `start-teacher.bat` “Güvenlik duvarı kuralları hazır” yazdıktan sonra
      keşif, giriş ve görüntü çalışıyor. Denetim: yönetici komut penceresinde
      `netsh advfirewall firewall show rule name=all | findstr /c:"Sinav Izleme"` üç kuralı
      listelemeli.
- [ ] **5. 10 saniyede canlı görüntü.** 3 ayrı bilgisayardan giriş yapılınca 10 saniye
      içinde panelde üçünün de canlı görüntüsü geliyor.
- [ ] **6. IP / bilgisayar adı / MAC.** Sağdaki listede öğrencinin satırını okundan açınca
      üçü de görünüyor (kutuya tıklayınca açılan büyük görünümde “Bilgisayar ve teslim
      bilgileri” altında da yazar). Aynı bilgisayarda
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
      sınav klasöründe `Kayıtlar\<numara>\` altında yeni bir kayıt dosyası başlıyor.
- [ ] **11. Ajanı Görev Yöneticisi'nden sonlandırma.** Kutu kırmızıya dönüyor; öğrencide
      Görev Yöneticisi → Ayrıntılar'da **`ffmpeg.exe` de kalmamış** olmalı.
- [ ] **12. Dosya adı.** Teslim, sınav klasöründe `Teslimler\<numara>_<AdSoyad>.pka` olarak kaydediliyor;
      “Şükrü Çağrı Işık” gibi bir adla deneyin → `…_SukruCagriIsik.pka`.
- [ ] **13. Sınav bitince geç teslim; otomatik teslim yok.** İki öğrenci dosyayı indirip
      kaydetsin, teslim etmesin. “Sınavı bitir”e basın: ikisinin de programı **açık
      kalıyor**, panellerinde “Sınav bitti” yazıyor. Biri “Teslim et” ile teslim etsin:
      panelde “Geç teslim etti” ve “Geç teslim” uyarısı çıkıyor. Sonra “Yeni sınav”a (ya da
      “Sistemi kapat”a) basın: panel teslim etmeyen öğrenci olduğunu söyleyip onay istiyor;
      onaylayınca o öğrencinin programı “Sınav kapatıldı — dosyanızı teslim etmediniz” deyip
      kapanıyor ve `Teslimler` klasörüne **dosya gelmiyor**.
- [ ] **14. Kayıtlar oynuyor.** Sınav klasöründe `Kayıtlar\<numara>\` altındaki `.mp4`
      dosyaları VLC'de oynuyor.
- [ ] **15. İnternetsiz çalışma.** Modemin internet kablosu çıkarılmışken tüm akış
      çalışıyor. Panelde F12 → Ağ (Network) sekmesinde yalnızca `localhost:8000` ve
      `127.0.0.1:8889` adreslerine istek olmalı.
- [ ] **16. İz kalmıyor.** Ajan kapandıktan sonra öğrenci bilgisayarında: Görev
      Yöneticisi'nde `SinavAjan.exe` / `ffmpeg.exe` yok; *Başlangıç uygulamaları*,
      *Hizmetler* ve *Görev Zamanlayıcı*'da ajana ait kayıt yok. (Öğrencinin indirdiği
      sınav dosyası ve `%LOCALAPPDATA%\SinavAjan` içindeki küçük günlük dosyası yerinde kalır.)

Ek denemeler (önerilir):

- [ ] Aynı numarayla ikinci bir bilgisayardan giriş **reddediliyor**, panelde uyarı çıkıyor.
- [ ] Sınav sırasında ajanı kapatıp yeniden açınca (aynı numara) öğrenci daha önce
      indirdiği dosyayla **devam ediyor**; yeniden indirmesi gerekmiyor, “Teslim et” hazır.
- [ ] “Sınav dosyasını indir” kayıt yerini soruyor; dosya seçilen yere kaydediliyor ve
      kendiliğinden açılmıyor. Öğrenci panelinde süre **görünmüyor**.
- [ ] **Klasör seçme.** Panelde **Sınav klasörü → Klasör seç** Windows'un klasör penceresini
      açıyor (pencere tarayıcının önünde mi?); seçilen klasörde `Kayıtlar` ve `Teslimler`
      oluşuyor. Klasör ve sınav dosyası seçilmeden “Sınavı başlat” basılamıyor.
- [ ] **Sınavı başlat penceresi.** Süre yazıp başlatınca panelde geri sayım, öğrencide
      “Kalan süre” görünüyor; süre dolunca sınav kendiliğinden bitiyor ve dosyalar
      toplanıyor. Süresiz başlatınca öğrencide süre görünmüyor. “Şu saatte” ile planlanan
      sınav o saatte başlıyor; öğrenci bekleme ekranında saati görüyor.
- [ ] **Ekran kaydı seçeneği.** “Ekranları kaydet” işaretliyken `Kayıtlar\<numara>\` altında
      dosya oluşuyor; işaretli değilken klasör boş kalıyor ama panelde ekranlar canlı
      görünüyor. Öğrenci tarafında iki durumda da hiçbir fark yok.
- [ ] **Teslim edenler alta gidiyor.** Teslim eden öğrencinin ekran kutusu en alta iniyor.
- [ ] **Sınavı bitir penceresi.** “Sınavı bitir”e basınca açılan pencerede “Ek süre ver”
      çalışıyor: öğrencide kalan süre artıyor (süresiz sınavda “Kalan süre” belirmeye
      başlıyor).
- [ ] **Uyarı dosyaları.** Sınav klasöründeki `Uyarılar` klasöründe uyarı alan her öğrenci
      için `<numara>_<AdSoyad>.csv` oluşuyor; Excel'de Türkçe harfler doğru açılıyor.
- [ ] **Panel penceresi ve kapatma.** `start-teacher.bat` paneli kendi penceresinde (sekmesiz,
      adres çubuksuz) açıyor. Pencereyi çarpıdan kapatın: bir iki saniye içinde **öğretmen
      bilgisayarında** “Pencereyi kapattınız” sorusu çıkıyor (başka pencerelerin önünde mi?).
      “Yalnızca pencere kapansın” deyin: öğrenciler bağlı kalıyor; `start-teacher.bat`'ı
      yeniden çalıştırınca yalnızca panel açılıyor. Pencereyi yeniden kapatıp “Sistemi kapat”
      deyin: öğrenci programları, sunucu, MediaMTX ve başlatma penceresi kapanıyor.
- [ ] **Teslimde dosya seçme.** “Teslim et” dosya seçme penceresini açıyor; pencere
      indirilen dosyanın klasöründe açılıyor. **Packet Tracer'da gerçekten kaydedilmiş**
      dosya seçilince ad ve son kayıt saatiyle onay soruluyor; “Evet, teslim et” → “Teslim
      alındı”, panelde “Teslim etti”, görüntüsü duruyor.
- [ ] Hiç kaydetmeden indirilen dosyayı seçince “Dosyada değişiklik yok” uyarısı. (Packet Tracer dosyayı *hiçbir değişiklik yapmadan* Ctrl+S ile kaydedince
      içeriği değişiyor mu? Değişmiyorsa bu uyarı o durumda da çıkar — öğrencilere söyleyin.)
- [ ] Eski bir `.pka` dosyası seçince “Yanlış dosya olabilir” uyarısı.
- [ ] **Teslim klasörü.** Teslim edilmiş bir dosyayı `Teslimler` klasöründen başka yere
      taşıyın: birkaç saniyede öğrenci kırmızı “Dosya klasörde yok” oluyor; geri koyunca
      yeniden “Teslim etti”. Henüz teslim etmemiş bir öğrenci için klasöre
      `<numarası>_deneme.pka` adlı bir dosya kopyalayın: öğrenci “Teslim etti” oluyor, ajanı
      “Teslim alındı” deyip kapanıyor.
- [ ] **Başka masaüstü.** Öğrencide Win+Ctrl+D ile yeni masaüstü açın: panelde “Başka bir
      masaüstüne geçti” uyarısı, öğrencide bildirim çıkıyor. Win+Ctrl+F4 ile kapatın.
- [ ] **Ekran boyutu ve liste.** Üst satırdaki − / + / kaydırıcı ile kutular büyüyüp
      küçülüyor; **Sığdır** hepsini ekrana sığdırıyor. **Öğrenciler** başlığının yanındaki ok
      listeyi sağda ince bir şeride daraltıyor; şeride tıklayınca liste geri açılıyor.
- [ ] İki öğrenci aynı dosyayı teslim edince kırmızı “birebir aynı dosya” uyarısı; hiç
      değiştirmeden teslimde “sınav dosyasının kendisi” uyarısı.
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
**bekleme aşamasında** yapılmalıdır (OGRENCI.md'de yazıyor); sınav başladıktan sonra tarayıcı
kapatılır. Ajan Packet Tracer'ı kendisi başlatmaz: öğrenci indirdiği dosyayı, bekleme
aşamasında açıp giriş yaptığı Packet Tracer penceresinde *File → Open* ile açar. Provada
bir öğrencinin Packet Tracer'ı kapatıp yeniden açtığında (ya da dosyaya çift tıkladığında)
yeniden giriş istenip istenmediğini deneyin; isteniyorsa öğrencilere Packet Tracer'ı sınav
boyunca **kapatmamalarını** söyleyin.

### Risk 3 — Panel performansı (35 WebRTC görüntüsü)

Geliştirme ortamında 35 yayın tek tarayıcıda oynatıldı (toplam ~175 kare/sn çözüldü),
ancak bu ölçüm sizin bilgisayarınızı temsil etmez. Öğretmen bilgisayarında
`sim_agent.py --count 35 --stream` ile (ya da gerçek sınıfla) deneyin; Görev Yöneticisi'nde
tarayıcının işlemci kullanımına ve görüntülerin akıcılığına bakın. Zorlanıyorsa **Diğer**
menüsünden **Görünmeyen ekranları duraklat**'ı açın, gerekirse `yayin.genislik: 960` yapın.

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
