# Kurulum ve Kullanım — Öğretmen

Bu belge öğretmen bilgisayarının kurulumunu, sınav günü akışını ve sorun gidermeyi anlatır.
Öğrencilere verilecek yönerge: [OGRENCI.md](OGRENCI.md). Sınavdan önce yapılacak prova:
[PROVA.md](PROVA.md).

## 1. Sistem nasıl çalışır?

```
 Öğrenci bilgisayarı (Windows)                 Öğretmen bilgisayarı (Windows)
 ┌──────────────────────────┐   UDP 47000     ┌────────────────────────────────────┐
 │ SinavAjan.exe            │ ── keşif ─────▶ │ Python sunucusu (server/)          │
 │  • giriş, heartbeat      │ ── TCP 8000 ──▶ │  • öğrenci API'si  (ağdan)         │
 │  • uygulama denetimi     │                 │  • öğretmen paneli (yalnızca       │
 │  • teslim                │                 │    localhost:8000/panel)           │
 │ ffmpeg.exe               │ ── TCP 8554 ──▶ │ MediaMTX (mediamtx/)               │
 │  • ekran → H.264 → RTSP  │                 │  • diske kayıt (sınav klasörü)     │
 └──────────────────────────┘                 │  • panele WebRTC (yalnızca yerel)  │
                                              └────────────────────────────────────┘
```

- Her sınıf **bağımsızdır**: kendi modemi, kendi öğretmen bilgisayarı, kendi sunucusu.
- Sınav sırasında **internet gerekmez**. Panel dahil her şey yereldir.
- Ajan sunucuyu **kendisi bulur** (UDP yayını). Ajanda kayıtlı IP adresi yoktur; aynı ajan
  paketi üç sınıfta da kullanılır.
- Öğrenci, ajanda büyük harflerle sınıf ve öğretmen adını görüp onaylar. Yanlış modeme
  bağlanan öğrenci bunu orada fark eder. **Bu yüzden her sınıfta sınıf adı farklı olmalı**
  (panelde sınıf adının yanındaki **Düzenle** ile değiştirilir).

Öğretmen bilgisayarında sınıf ağına açılan portlar:

| Port | Ne için | Kim bağlanır |
|---|---|---|
| UDP 47000 | Sunucu keşfi | Ajan |
| TCP 8000 | Öğrenci API'si (giriş, heartbeat, dosya, teslim) | Ajan |
| TCP 8554 | Ekran yayını (RTSP) | Ajanın ffmpeg'i |

Panel (`/panel`), MediaMTX'in WebRTC'si (8889, 8189) ve denetim API'si (9997) yalnızca
öğretmen bilgisayarının kendisinden (127.0.0.1) erişilebilir.

## 2. Gereksinimler

**Öğretmen bilgisayarı**

- Windows 10 veya 11
- Python **3.11 veya daha yenisi** (<https://www.python.org/downloads/> — kurulumda
  **“Add python.exe to PATH”** kutusunu işaretleyin)
- Güncel Chrome veya Edge
- Kurulum sırasında internet (sınav sırasında gerekmez)
- Ekran kayıtları için disk alanı: öğrenci başına saatte yaklaşık **225 MB**
  (500 kbps). 35 öğrenci × 1 saat ≈ **8 GB**.

**Modem (sınıf ağı)**

- DHCP açık.
- **AP izolasyonu / istemci izolasyonu / “Client Isolation” KAPALI olmalı.** Açıksa
  bilgisayarlar birbirini göremez; keşif de bağlantı da çalışmaz (elle IP girmek de
  işe yaramaz). Modem arayüzünde genelde Kablosuz → Gelişmiş altındadır. “Misafir ağı”
  (guest network) kullanmayın; misafir ağlarında izolasyon her zaman açıktır.
- Her sınıfın alt ağı farklı olmalı (ör. `192.168.1.x`, `192.168.2.x`, `192.168.3.x`).
- Öğretmen bilgisayarı da aynı modeme (tercihen **kabloyla**) bağlı olmalı. Öğretmen
  bilgisayarının IP adresi değişebilir; sistem buna göre tasarlanmıştır.

## 3. Kurulum (sınavdan önce, internet varken)

1. **Depoyu indirin.** GitHub sayfasında *Code → Download ZIP* deyip zip'i açın (veya
   `git clone`). Klasörü kısa bir yola koyun, ör. `C:\sinav`.
2. **Python'u kurun** (bkz. Gereksinimler).
3. **`scripts\start-teacher.bat` dosyasına çift tıklayın.** İlk çalıştırmada sırasıyla:
   - `.venv` klasörüne Python ortamını kurar ve gerekli paketleri indirir,
   - MediaMTX'i indirir (`mediamtx\mediamtx.exe`, sabit sürüm),
   - Windows Güvenlik Duvarı kurallarını denetler. Eksikse **yönetici izni ister**
     (“Evet” deyin) ve açılan ikinci pencerede ne eklediğini yazar:
     - `Sinav Izleme - Kesif (UDP 47000)`
     - `Sinav Izleme - API (TCP 8000)`
     - `Sinav Izleme - RTSP (TCP 8554)`

     Kurallar yalnızca **Özel** ve **Ortak** ağ profilleri için eklenir (modem ağı
     genelde “Ortak” görünür).
   - MediaMTX'i ayrı (simge durumunda) bir pencerede, sunucuyu bu pencerede başlatır
     ve paneli tarayıcıda açar: <http://localhost:8000/panel>
4. **Sınıf (salon) ve öğretmen adını yazın.** Panelin sol üstünde sınıf adının yanındaki
   **Düzenle**'ye basın, **Sınıf / salon adı** ile **Öğretmen adı**nı yazıp **Kaydet** deyin.
   Öğrenciler programı açtığında bu adları görür. Sınıf adı **her sınıfın bilgisayarında
   farklı** olmalı. Yazdığınız adlar kalıcıdır; sınav sürerken değiştirilemez.
   (İlk açılıştaki adlar `server\config.yaml` dosyasındaki `sinif_adi` / `ogretmen_adi`
   değerleridir; panelde yazdığınız onların yerine geçer.)
5. **Ajan paketini edinin.** GitHub'da depo sayfası → **Actions** → **build-agent** → en
   üstteki yeşil çalıştırma → sayfanın altındaki **Artifacts** → **SinavAjan-win-x64**.
   İnen dosya bir zip'tir; içinde `SinavAjan` klasörü vardır (`SinavAjan.exe`,
   `ffmpeg.exe`, `agent.json`, birkaç `.dll`, `OKUBENI.md`).
   - İndirdiğiniz zip'in adını **`SinavAjan.zip`** yapıp deponun içinde **`dist\`**
     klasörüne koyun (`C:\sinav\dist\SinavAjan.zip`). Böylece öğrenciler sınıf ağına
     bağlıyken tarayıcıdan `http://<öğretmen-ip>:8000/` adresini açıp ajanı indirebilir
     (internet gerekmez). Öğretmen IP'si sunucu penceresinde ve panelin üstünde yazar.
   - İsterseniz zip'i önceden (e-posta, USB bellek, ders sayfası) dağıtın.
   - Artifact'ler 90 gün sonra silinir. Yeniden üretmek için Actions → build-agent →
     **Run workflow**. Kalıcı bir indirme bağlantısı isterseniz depoya `v1.0.0` gibi bir
     etiket (tag) gönderin; iş akışı aynı zip'i *Releases* altında yayınlar.
6. **Prova yapın:** [PROVA.md](PROVA.md).

> Kurulumdan sonra `start-teacher.bat` internet olmadan çalışır.

### Windows Güvenlik Uyarısı penceresi çıkarsa

Betiğin eklediği kurallar sayesinde normalde **çıkmaz**. Yine de “Windows Güvenlik Duvarı
bu uygulamanın bazı özelliklerini engelledi” penceresi çıkarsa **“Özel ağlar” ve “Ortak
ağlar” kutularının ikisini de işaretleyip “Erişime izin ver”** deyin. **“İptal”e basmayın:**
Windows o program için *engelleme* kuralı oluşturur ve bu kural izin kurallarını ezer
(düzeltmek için bkz. Sorun giderme).

## 4. Sınav günü

1. Öğretmen bilgisayarını sınıf modemine bağlayın. `scripts\start-teacher.bat`'ı çalıştırın.
   Panel açılır; üstte sınıf ve öğretmen adı ile **Sınav başlamadı** yazar. Ad yanlışsa
   yanındaki **Düzenle** ile değiştirin.
2. Üstteki hazırlık satırında, sırayla:
   - **1 Sınav klasörü → Klasör seç** — Windows'un klasör penceresi açılır; bu sınavın
     dosyalarının duracağı klasörü seçin (ör. `D:\Sınavlar\Ağ Temelleri Vize`; pencerede
     yeni klasör de oluşturabilirsiniz). Seçtiğiniz klasörün içinde üç klasör açılır:
     - **`Kayıtlar`** — öğrencilerin ekran kayıtları,
     - **`Teslimler`** — öğrencilerin teslim ettiği dosyalar,
     - **`Uyarılar`** — her öğrencinin uyarıları, öğrenci başına ayrı bir dosyada.

     Klasör seçilmeden sınav başlatılamaz. Her sınav için ayrı bir klasör seçin. (Klasör penceresi açılamazsa panel, klasörün yolunu elle
     yazmanız için bir kutu gösterir.)
   - **2 Sınav dosyası → Dosya seç** — öğrencilere dağıtılacak `.pka` dosyası.
   - **3 Öğrenci listesi → Dosya seç** — isteğe bağlı Excel listesi (bkz. bölüm 6).
3. Öğrenciler modeme bağlanır, programı **yönetici olarak** çalıştırır, sınıf/öğretmen adını
   onaylar ve giriş yapar. Her öğrenci solda canlı ekranıyla bir kutu, sağda **Öğrenciler**
   listesinde **tek satır** olarak belirir.
   - Bu aşamada izin listesi **uygulanmaz**. Öğrenciler Packet Tracer'ı açıp Cisco
     hesabıyla giriş yapsın (giriş tarayıcı açar; sınav başlayınca tarayıcı kapatılır).
   - “Giriş yapmayanlar” bölümü listede olup henüz girmeyenleri gösterir.
   - **Ekran boyutu:** üst satırda, **Diğer** düğmesinin solundaki **− / kaydırıcı / +** ile
     öğrenci ekranlarını büyütüp küçültebilirsiniz (ekranların üzerinde Ctrl + fare tekerleği
     de olur). **Sığdır** bütün ekranları kaydırmadan görünecek boyuta getirir.
   - **Listeyi daraltma:** sağdaki **Öğrenciler** başlığının yanındaki ok, listeyi sağ kenarda
     ince bir şeride daraltır; ekranlar boşalan yeri kullanır. Şeritte bağlı / uyarılı / kopuk /
     teslim etti sayıları ve görülmemiş uyarı sayısı görünmeye devam eder. Şeride tıklayınca
     liste yeniden açılır.
4. Herkes hazır olunca **Sınavı başlat**'a basın. (Klasör ve sınav dosyası seçilmeden bu
   düğme basılamaz.) Açılan pencerede:
   - **Başlangıç:** **Hemen** ya da **Şu saatte** (ör. 10:30). Saat seçerseniz sınav o
     saatte kendiliğinden başlar; o zamana kadar üstte “Sınav saat 10:30 için planlandı”
     yazar, öğrenciler de bu saati görür, **İptal et** ile vazgeçebilirsiniz.
   - **Sınav süresi (isteğe bağlı):** Dakika yazarsanız öğrenciler kalan süreyi görür,
     panelde geri sayım yazar ve **süre dolunca sınav kendiliğinden biter**. Boş
     bırakırsanız süre tutulmaz; sınavı siz bitirirsiniz. Ek süreyi sınav sırasında
     **Sınavı bitir** penceresinden verirsiniz (aşağıda).
   - **Ekranları kaydet:** İşaretliyse öğrenci ekranları sınav klasöründeki `Kayıtlar`a
     kaydedilir. İşaretli değilse ekranlar yalnızca panelde **canlı izlenir**, diske
     yazılmaz. Öğrenci bu seçimi göremez; her iki durumda da ekranı size aktarılır. Sınav
     başlamadan önce (bekleme aşamasında) hiçbir zaman kayıt yapılmaz. Panelin üstünde
     “kayıt açık / kayıt kapalı” yazar.

   **Sınav başlayınca öğrencinin bilgisayarında hiçbir şey kendiliğinden açılmaz ya da
   inmez.** Ayrı bir “paylaş” adımı da yoktur: sınav başladığı anda öğrencinin panelinde
   **Sınav dosyasını indir** düğmesi çıkar ve dosyayı kendisi indirir. Öğrencide:
   - “Sınav başlıyor. İzin verilmeyen programlar 10 saniye içinde kapatılacak.” uyarısı
     ve geri sayım görünür,
   - geri sayım bitince uygulama denetimi başlar; program küçük bir panele dönüşür,
   - panelde **Sınav dosyasını indir** düğmesi çıkar. Öğrenci dosyayı **kendi seçtiği
     yere** kaydeder ve Packet Tracer'da kendisi açar (*File → Open*).
5. Sınav boyunca paneli izleyin:
   - Renkli nokta ve kutu çerçevesi durumu gösterir: **yeşil** = bağlı, **sarı** =
     görülmemiş uyarı var, **kırmızı** = bağlantı yok (10 sn sinyal yok ya da ekran
     gelmiyor) ya da teslim dosyası klasörde yok, **gri** = teslim etti.
   - Sağdaki listede her öğrenci tek satırdır. Bir olay olduğunda uyarı **o öğrencinin
     satırında**, adının yanında görünür (sığmayan metin “…” ile kesilir; fareyle
     üzerine gelince tamamı okunur). Birden çok uyarı varsa sayısı da yazar. Satırı okundan
     açınca o öğrencinin son uyarıları, **IP · bilgisayar adı · MAC** bilgisi ve teslim
     dosyası görünür; **Görüldü** uyarıları kapatır, **Ekranı büyüt** büyük görüntüyü açar.
   - Listenin üstündeki **Uyarılar** sekmesi bütün uyarıları, en yenisi üstte olacak
     şekilde **tek satırlık düz bir liste** olarak gösterir (saat, öğrenci, uyarı). Satıra
     tıklayınca o öğrencinin ekranı açılır. Görüldü işaretlediğiniz uyarılar listede
     soluk kalır; **Tümünü görüldü yap** hepsini birden işaretler.
   - Kutuya tıklayınca öğrencinin ekranı büyür; yanında tüm **olay geçmişi** ve “Bilgisayar
     ve teslim bilgileri” bulunur.
   - Sesli uyarı isterseniz sağ üstteki **Diğer** menüsünden **Uyarılarda ses çal**'ı açın.
   - **Teslim edenlerin ekranı kendiliğinden en alta gider;** üstte hâlâ sınavda olanlar
     kalır. (Sağdaki liste numara sırasında kalır.)
   - Süre vermediyseniz **süreyi siz tutarsınız**: panelde yalnızca sınavın başladığı saat
     yazar, öğrenci süre görmez.
6. Öğrenci **Teslim et**'e basınca açılan pencereden **teslim edeceği dosyayı kendisi
   seçer.** Dosya öğretmen bilgisayarındaki **`Teslimler`** klasörüne gelir; sistem dosyanın
   klasöre gerçekten ulaştığını denetler, öğrencinin **ekran yayınını durdurur**, kutusu
   griye döner (“Teslim etti”) ve programı kapanır. Ayrıntı için aşağıdaki “Teslim nasıl
   denetlenir?” bölümüne bakın.
7. **Sınavı bitir**'e basınca bir pencere açılır (aynı pencere **Diğer → Ek süre ver…**
   ile de açılır). Henüz teslim etmeyen öğrenci sayısını gösterir ve iki seçenek sunar:
   - **Ek süre ver:** dakikayı yazıp düğmeye basın. Süreli sınavda bitiş saati o kadar
     ileri alınır; süresiz sınavda sınav yazdığınız süre sonunda kendiliğinden biter.
     Öğrenciler yeni kalan süreyi hemen görür.
   - **Sınavı bitir:** sınav biter (süre verdiyseniz süre dolunca kendiliğinden de biter).
8. **Sınav bitince teslim etmemiş öğrencilerin programı kapanmaz.** Panellerinde “Sınav
   bitti” yazar; ekranları izlenmeye, izinsiz programlar kapatılmaya devam eder ve
   dosyalarını yine **Teslim et** ile teslim edebilirler. Bu teslim kabul edilir ama **geç
   teslim** olarak işaretlenir: öğrencinin satırında “Geç teslim etti” yazar, size
   “Geç teslim: dosyasını sınav bittikten … dakika sonra teslim etti” uyarısı düşer,
   `index.csv` dosyasında “gec_teslim: evet” yazar. Sınav bittikten sonra sınav dosyası
   artık indirilemez. Henüz teslim etmeyenler kırmızı “Teslim yok” olarak görünür.
9. İşiniz bitince **Yeni sınav** ya da **Diğer → Sistemi kapat…** deyin. İkisi de hâlâ açık
   olan öğrenci programlarını kapatır; teslim etmemiş öğrencinin indirdiği dosyanın **son
   kaydedilmiş hâli** bu sırada otomatik alınır (olay kaydında “Otomatik teslim alındı”
   yazar; geç teslim sayılmaz). **Sınav klasörünü aç** düğmesi klasörü Dosya Gezgini'nde
   açar: kayıtlar, teslimler, uyarılar ve olay kaydı oradadır.

### Paneli kapatmak ve sistemi kapatmak

Panel bir tarayıcı penceresidir; küçültebilir, alta alabilirsiniz. **Pencereyi çarpıdan
kapattığınızda** sistem kapanmaz: birkaç saniye içinde masaüstünde bir soru çıkar —
“Panel penceresi kapatıldı”:

- **Arka planda çalışsın** — yalnızca pencere kapanmış olur. Öğrenciler bağlı kalır, ekranlar
  ve teslimler alınmaya devam eder. Paneli yeniden açmak için `start-teacher.bat` dosyasını
  bir kez daha çalıştırın (sistem zaten çalışıyorsa yalnızca paneli açar) ya da tarayıcıda
  <http://localhost:8000/panel> adresine gidin.
- **Paneli yeniden aç** — yanlışlıkla kapattıysanız.
- **Sistemi kapat** — sınav sürüyorsa bir kez daha sorulur. Sınav biter, açık öğrenci
  programları son kaydedilen dosyayı teslim edip kapanır, sunucu, MediaMTX ve başlatma
  penceresi kapanır.

(Tarayıcılar bir sayfanın kendi penceresi kapanırken soru sormasına izin vermediği için soru,
pencere kapandıktan hemen sonra çıkar.) Sistemi panelin içinden de kapatabilirsiniz:
**Diğer → Sistemi kapat…**

### Teslim nasıl denetlenir?

Öğrenci tarafında (dosya gönderilmeden önce):

- Yalnızca `.pka` dosyası seçilebilir; boş ya da 50 MB'tan büyük dosya gönderilmez.
- Seçilen dosya **indirilen sınav dosyasının birebir aynısıysa** (hiçbir şey
  kaydedilmemişse) öğrenci uyarılır: “… indirdiğiniz sınav dosyasının aynısı: içine hiçbir
  değişiklik kaydedilmemiş …”. Öğrenci yine de göndermek isterse gönderebilir; bu durumda
  size de uyarı düşer.
- Seçilen dosya **sınav dosyası indirilmeden önce kaydedilmişse** (büyük olasılıkla başka
  bir dosya) öğrenci uyarılır; yine de gönderirse size uyarı düşer.
- Doğru dosyada öğrenciye dosyanın adı ve son kayıt saati gösterilip onay istenir.

Öğretmen tarafında:

- Dosya yüklenirken **bozulmadığı** iki yönden doğrulanır: öğrenci bilgisayarının hesapladığı
  özet (SHA-256) ile öğretmen bilgisayarına ulaşan dosyanın özeti karşılaştırılır; dosya
  `Teslimler` klasörüne yazıldıktan sonra **klasörden yeniden okunup** bir kez daha
  karşılaştırılır. Tutmazsa teslim kabul edilmez ve öğrenci yeniden dener.
- Öğrenci ancak dosyası **`Teslimler` klasöründe durduğu sürece** “Teslim etti” görünür.
  Sistem klasörü birkaç saniyede bir denetler; dosya silinir ya da taşınırsa öğrenci
  kırmızı “Dosya klasörde yok” olur ve uyarı düşer.
- `Teslimler` klasörüne **elle koyduğunuz** bir dosya (ör. USB bellekten), adı öğrencinin
  numarasıyla başlıyorsa (`2021001_….pka`) o öğrencinin teslimi sayılır: öğrenci “Teslim
  etti” olur, yayını durur, programı “Teslim alındı” deyip kapanır.
- Teslim edilen dosya **sınav dosyasının kendisiyse**, **başka bir öğrencinin dosyasıyla
  birebir aynıysa** ya da **boyutu sınav dosyasından çok farklıysa** uyarı çıkar.

Sistemin **denetleyemediği** şey: dosyanın Packet Tracer'da açılıp açılmadığı ve içindeki
çözüm. `.pka` dosyaları şifreli olduğu için içi öğretmen bilgisayarında okunamaz. Yukarıdaki
denetimler “yanlış dosya / kaydedilmemiş dosya / bozuk yükleme” durumlarını yakalar; içeriği
değerlendirmek için dosyayı Packet Tracer'da açmanız gerekir.

### Uyarılar ne anlama gelir?

| Uyarı | Anlamı |
|---|---|
| `chrome.exe kapatıldı — pencere: “…”` | İzinsiz bir program pencere açtı; ajan onu kapattı. |
| `Packet Tracer dışında bir pencere önde: explorer.exe (6 sn)` | İzin listesinde olmayan bir pencere 5 sn'den uzun süre öndeydi. Windows'un kendi programları (Dosya Gezgini, Ayarlar, Komut İstemi…) kapatılmaz, yalnızca bu şekilde bildirilir. |
| `Monitör sayısı: 2` | İkinci ekran takılı ya da sınav sırasında takıldı/çıkarıldı. |
| `Başka bir masaüstüne geçti` | Öğrenci Windows'un sanal masaüstlerinden bir başkasına geçti (Görev Görünümü, Win+Ctrl+→). Öğrenciye de bildirim gösterilir. Ekran yayını o masaüstünü de gösterir; izinsiz programlar orada da kapatılır. |
| `Bağlantı koptu — ajandan sinyal gelmiyor / ekran yayını yok` | Wi-Fi koptu, bilgisayar uyudu ya da ajan kapandı. Bağlantı gelince kutu kendiliğinden yeşile döner. |
| `Ajan öğrenci tarafından kapatıldı` | Öğrenci ajan penceresini kapattı (onay vererek). |
| `Aynı numarayla ikinci oturum açma girişimi reddedildi` | Bu numara başka bir bilgisayarda zaten açık. |
| **`Bu bilgisayardan daha önce <numara> giriş yapmıştı`** (kırmızı) | Aynı bilgisayardan (MAC) farklı bir numarayla giriş yapıldı. |
| `Farklı bir bilgisayardan yeniden giriş yaptı` | Öğrencinin oturumu düştükten sonra başka bir bilgisayardan girildi. |
| `Ad uyuşmuyor` / `Numara öğrenci listesinde yok` | Girişteki bilgiler listeyle uyuşmuyor (giriş yine de kabul edilir). |
| **`… ile birebir aynı dosyayı teslim etti`** (kırmızı) | İki farklı öğrencinin dosyasının SHA-256 özeti aynı. |
| `Teslim edilen dosya sınav dosyasının kendisi (hiç değişiklik kaydedilmemiş)` | Öğrenci hiçbir şey kaydetmeden, indirdiği dosyayı teslim etti (boş teslim). |
| `Teslim edilen dosya, sınav dosyası indirilmeden önce kaydedilmiş` | Öğrenci büyük olasılıkla yanlış (eski) bir dosya seçti. |
| `Teslim edilen dosyanın boyutu sınav dosyasından çok farklı` | Dosya sınav dosyasının üçte birinden küçük ya da beş katından büyük; yanlış dosya olabilir. |
| `Geç teslim: dosyasını sınav bittikten … dakika sonra teslim etti` | Öğrenci dosyasını sınav bittikten sonra teslim etti. Dosya alınır; teslim “geç” olarak işaretlenir. |
| **`Teslim dosyası klasörde bulunamıyor`** (kırmızı) | Teslim edilen dosya `Teslimler` klasöründen silinmiş ya da taşınmış. Geri konunca öğrenci yeniden “Teslim etti” olur. |
| `Teslimler klasöründe hiçbir öğrenciyle eşleşmeyen dosya var` | Klasöre elle konan dosyanın adı giriş yapmış bir öğrencinin numarasıyla başlamıyor. |
| **`Ekran yayını farklı bir IP adresinden geliyor`** (kırmızı) | Yayın, giriş yapılan bilgisayardan gelmiyor. |

Her öndeki pencere değişimi, yayın yeniden başlatmaları, girişler ve teslimler uyarı
olarak değil **olay kaydına** yazılır (büyük pencerede ve CSV'de görünür).

## 5. Sınavdan sonra

Her şey panelde seçtiğiniz **sınav klasörünün** içindedir (sınav bitince üstteki **Sınav
klasörünü aç** ya da her zaman **Diğer → Sınav klasörünü aç**):

| Ne | Nerede (sınav klasörünün içinde) |
|---|---|
| Teslim dosyaları | `Teslimler\<numara>_<AdSoyad>.pka` (Türkçe harfler çevrilir: `2021001_AhmetSahinCakir.pka`). Aynı öğrencinin sonraki teslimleri `_v2`, `_v3` olarak ayrıca saklanır. |
| Teslim dökümü | `Teslimler\index.csv` — zaman, numara, ad, dosya, **SHA-256**, boyut, otomatik mi, sürüm, IP, bilgisayar, MAC, geç teslim mi |
| Uyarılar (öğrenci öğrenci) | `Uyarılar\<numara>_<AdSoyad>.csv` — o öğrencinin bütün uyarıları (kapatılan programlar, başka pencere, başka masaüstü, bağlantı kopması, geç teslim…), saatleriyle. Uyarı geldikçe güncellenir; hiç uyarısı olmayan öğrenci için dosya açılmaz. Excel'de açılır. |
| Ekran kayıtları | `Kayıtlar\<numara>\<tarih-saat>.mp4` — 10 dakikalık bölümler. Bağlantı kopup geri gelince yeni dosya başlar. VLC ile oynatılır. |
| Olay kaydı | `olay-kaydi.csv` (sınav bitince yazılır; Excel'de açılır). Panelden de indirilebilir: **Diğer → Olay kaydını indir (CSV)**. |

Sunucunun kendi çalışma dosyaları (`data\` klasörü: sınav durumu, ham olay kaydı
`events.jsonl`, MediaMTX günlüğü `mediamtx.log`) deponun içinde kalır.

- **Yeni sınav:** Sınav bitince üstte beliren **Yeni sınav** düğmesi (ya da **Diğer → Yeni
  sınav hazırla**; sınav sürerken kullanılamaz) paneli boşaltır. Hâlâ açık olan öğrenci
  programları kapanır (teslim etmemiş olanların son kaydettiği dosya otomatik alınır). Biten
  sınavın kayıtları, teslimleri, uyarıları ve olay kaydı **sınav klasöründe kalır; hiçbir
  şey silinmez ya da taşınmaz.** Yeni sınav için yeniden klasör seçersiniz. Öğrenci listesi
  korunur.
- Sunucu sınav sırasında kapanırsa (elektrik, yanlışlıkla kapatma) `start-teacher.bat`'ı
  yeniden çalıştırın: sınav durumu, sınav klasörü, öğrenciler ve olaylar `data\state.json`
  dosyasından **geri yüklenir**, programlar kendiliğinden yeniden bağlanır, kayıt aynı
  klasöre sürer.
- Sınav klasörü çıkarılabilir bir diskteyse ve disk sınav sırasında çıkarılırsa panelin
  üstünde “Sınav klasörüne ulaşılamıyor” uyarısı çıkar; disk takılana kadar teslim alınamaz.
- **Kayıt saklama:** Ekran kayıtları (sınavı “Ekranları kaydet” işaretliyken başlattıysanız
  oluşur) **otomatik silinmez**. Kurumunuzun kuralına göre
  `config.yaml` içindeki `kayit_saklama_notu` metnini düzenleyin (öğrenciye giriş
  ekranında gösterilir) ve süre dolunca sınav klasöründeki `Kayıtlar` klasörünü elle silin.

## 6. Öğrenci listesi (Excel)

- `.xlsx` (veya `.csv`). Sütunlar: **numara, ad, soyad**. Başlıklar büyük/küçük harf ve
  Türkçe karakter farkına takılmaz (`NUMARA`, `Öğrenci No`, `Adı`, `SOYADI`, `Ad Soyad`…).
  Başlık satırı ilk 15 satır içinde aranır. Eski `.xls` dosyalarını Excel'de `.xlsx`
  olarak kaydedin.
- Liste **yüklüyse:**
  - numara listede ve ad uyuşuyor → normal; panelde ve dosya adında **listedeki** ad kullanılır,
  - ad uyuşmuyor → giriş kabul edilir, sarı uyarı çıkar,
  - numara listede yok → giriş kabul edilir, “listede yok” uyarısı çıkar.
- Liste **yüklü değilse** tüm girişler uyarısız kabul edilir.
- Liste sınav sırasında da yüklenebilir/değiştirilebilir; giriş yapmış öğrenciler yeniden
  denetlenir.

## 7. Ayarlar

### `server\config.yaml`

Dosyanın içindeki açıklamalar her ayarı anlatır. Özet:

| Anahtar | Varsayılan | Açıklama |
|---|---|---|
| `sinif_adi`, `ogretmen_adi` | — | Yalnızca ilk açılıştaki adlar. Panelde **Düzenle** ile yazdığınız adlar bunların yerine geçer (`data\settings.json`) |
| `sunucu.port` / `sunucu.kesif_portu` | 8000 / 47000 | Değiştirirseniz `start-teacher.bat`, `mediamtx.yml` (`webrtcAllowOrigins`) ve `agent.json` da değişmeli |
| `yayin.kullanici`, `yayin.sifre` | sinavajan / … | MediaMTX yayın kimliği (aşağıya bakın) |
| `yayin.fps`, `genislik`, `bitrate_kbps` | boş | Doldurursanız ajanların `agent.json` değerlerini ezer. Wi-Fi zorlanıyorsa buradan düşürün (ör. 3 fps, 960 px, 300 kbps); öğrencinin yeniden giriş yapması yeterlidir |
| `izin_listesi` | Packet Tracer klasörleri | İzinli program klasörleri (joker destekli) |
| `windows_altinda_kapatilacaklar` | notepad.exe, mspaint.exe… | `C:\Windows\` altında olduğu hâlde kapatılacak programlar |
| `kapatma_disi` | boş | Kapatılmayacak (ama öne geçerse bildirilecek) programlar |
| `sadece_uygulama_pencereleri` | true | false: görünür penceresi olan her süreç kapatılır (daha katı) |
| `esikler.on_pencere_toleransi_sn` | 5 | Öndeki pencere toleransı |
| `esikler.kopma_suresi_sn` | 10 | Kırmızıya dönme süresi |
| `esikler.kapatma_geri_sayim_sn` | 10 | Sınav başındaki geri sayım |
| `klasorler.veri`, `klasorler.dagitim` | `../data`, `../dist` | Sunucunun çalışma dosyaları ve dağıtılacak ajan paketi. (Kayıtlar ve teslimler burada değil, panelde seçilen sınav klasöründedir.) |
| `kayit_saklama_notu` | — | Öğrenciye giriş ekranında gösterilen saklama açıklaması |

İzin listesi bölümleri sunucu çalışırken de yeniden okunur ve birkaç saniye içinde
ajanlara ulaşır; diğer ayarlar için sunucuyu yeniden başlatın.

### Yayın şifresi

Tüm ajanlar MediaMTX'e **tek bir ortak** kullanıcı/şifreyle yayın yapar. Bu şifre üç
yerde aynı olmalıdır:

1. `mediamtx\mediamtx.yml` → `authInternalUsers` (asıl denetim burada)
2. `server\config.yaml` → `yayin.kullanici` / `yayin.sifre` (sunucu girişte ajana gönderir)
3. `agent.json` (ajanın yanında; sunucu göndermezse kullanılan yedek)

Depodaki varsayılan şifre herkese açıktır. Değiştirmek için 1 ve 2'yi değiştirmeniz
yeterlidir (ajan paketini yeniden dağıtmak gerekmez). Bu şifre yalnızca *yayın yapmaya*
yarar; izleme hiçbir şifreyle ağdan yapılamaz (yalnızca öğretmen bilgisayarından).

### `agent.json` (ajanın yanında)

```json
{
  "discovery_port": 47000,
  "stream": { "user": "sinavajan", "pass": "…", "fps": 5, "width": 1280, "bitrate_kbps": 500 }
}
```

Sunucu IP'si burada **yoktur** ve hiçbir yere kaydedilmez; her açılışta keşfedilir.

### `mediamtx\mediamtx.yml`

MediaMTX **v1.21.4** için yazılmıştır (`scripts\fetch-mediamtx.ps1` bu sürümü indirir ve
SHA-256 özetini doğrular). Sürümü yükseltirseniz anahtar adlarını yeni sürümün örnek
dosyasıyla karşılaştırın. RTSP yalnızca TCP; WebRTC açık, ICE sunucu listesi boş, yerel
adres `webrtcAdditionalHosts` ile verilir; HLS/RTMP/SRT/MoQ kapalı; okuma yalnızca
`127.0.0.1`. Her öğrencinin yayın yolu numarasıdır (`rtsp://<öğretmen>:8554/<numara>`).
Kayıt bu dosyada **kapalı** başlar: panelde sınav klasörü seçildiğinde sunucu, MediaMTX'in
denetim API'siyle kaydı açar ve kayıt yolunu o klasörün `Kayıtlar` klasörüne çevirir (fMP4,
10 dakikalık bölümler). Bu yüzden `recordPath` elle değiştirilmez.

## 8. Uygulama denetimi nasıl karar verir?

Sınav **sürerken** ajan saniyede bir:

1. Görünür penceresi olan süreçleri ve öndeki pencerenin sürecini bulur. Karar pencere
   başlığına göre değil, **sürecin tam yoluna** göre verilir.
2. Süreç şu sınıflardan birine girer:
   - **İzinli:** `izin_listesi` klasörlerinin altındaki her exe (Packet Tracer ve yardımcı
     süreçleri; router/switch CLI pencereleri de Packet Tracer'a aittir), ajanın kendisi,
     `ffmpeg.exe`.
   - **Windows:** `C:\Windows\` altındaki her şey. **Kapatılmaz**; 5 sn'den uzun önde
     kalırsa uyarı çıkar (Başlat menüsü, Alt+Tab, bildirimler, UAC gibi kısa geçişler
     uyarı üretmez).
   - **Yasak:** geri kalan her şey. Penceresi varsa **kapatılır**, panele olay düşer,
     öğrenciye “… sınav sırasında kullanılamaz.” bildirimi gösterilir.
3. Monitör sayısı 1'den fazlaysa ya da değişirse uyarı verir.
4. Öğrenci Windows'un başka bir **sanal masaüstüne** geçerse (Görev Görünümü, Win+Ctrl+D,
   Win+Ctrl+→) uyarı verir ve öğrenciye “Başka bir masaüstündesiniz” bildirimini
   gösterir. Geri döndüğünde kaç saniye orada kaldığı olay kaydına yazılır.

Bilmeniz gerekenler:

- **Not Defteri istisnası.** Windows 11'de Not Defteri `C:\Program Files\WindowsApps\…`
  altındadır ve kendiliğinden “yasak”tır. Windows 10'da `C:\Windows\System32\notepad.exe`
  olduğu için “C:\Windows altı kapatılmaz” kuralına takılır. Bu yüzden
  `windows_altinda_kapatilacaklar` listesi vardır (notepad, mspaint, wordpad, ekran
  alıntısı aracı, uzak masaüstü…). Listeyi dilediğiniz gibi daraltıp genişletebilirsiniz;
  `cmd.exe`/`powershell.exe` bilinçli olarak listede değildir (kapatılmaz, öndeyse bildirilir).
- **Yardımcı pencereler.** Varsayılan ayarda (`sadece_uygulama_pencereleri: true`) yalnızca
  gerçek uygulama pencereleri (başlığı olan, görev çubuğunda/Alt+Tab'da görünen) ve *öne
  geçen* pencereler “penceresi var” sayılır. Ekran kartı katmanları, ses/klavye
  sürücülerinin görünmez yardımcı pencereleri kapatılmaz. Daha katı davranış için `false`.
- **Erişilebilirlik / gerekli ek programlar** (ekran okuyucu vb.) için klasörü
  `izin_listesi`ne ekleyin.
- **Sürekli yeniden açılan bir program** provada tekrar tekrar “kapatıldı” uyarısı
  üretiyorsa onu `kapatma_disi`ne ekleyin.
- Öğrencinin hesabı yöneticidir; ajanı kapatabilir. Sistemin amacı bunu **engellemek değil
  tespit etmektir**: ajan kapanınca kutu kırmızıya döner, yayın ve kayıt o anda durur.

## 9. Sorun giderme

**Ajan “Sınav sunucusu bulunamadı” diyor**

1. Öğrenci doğru Wi-Fi'ya bağlı mı? (En sık neden.)
2. Sunucu penceresi açık mı, panel çalışıyor mu?
3. Modemde **AP/istemci izolasyonu** kapalı mı? Açıksa hiçbir yol çalışmaz.
4. Güvenlik duvarı kuralları var mı? `start-teacher.bat` açılışta “Güvenlik duvarı
   kuralları hazır” yazmalı. Üçüncü taraf güvenlik yazılımı (antivirüsün kendi güvenlik
   duvarı) varsa onda da UDP 47000, TCP 8000, TCP 8554 için gelen bağlantıya izin verin.
5. Yedek yol: öğrenci ajanda **elle IP** girer. IP, sunucu penceresinde ve paneldeki
   **Diğer** menüsünün altında yazar. Elle IP çalışıp keşif çalışmıyorsa sorun UDP
   yayınındadır (modem ayarı ya da güvenlik duvarı).

**Öğrenci giriş yaptı ama görüntü yok / kutu “ekran yayını yok” ile kırmızı**

- MediaMTX penceresi açık mı? Panelin üstünde “Ekran görüntüleri alınamıyor” yazıyorsa
  `start-teacher.bat`'ı kapatıp yeniden açın.
- TCP 8554 kuralı var mı?
- Öğrencide `ffmpeg.exe`, `SinavAjan.exe` ile aynı klasörde mi? Antivirüs ffmpeg'i
  engellemiş olabilir (bkz. OGRENCI.md → Antivirüs). Bu durumda panelde “ffmpeg.exe
  bulunamadı veya çalıştırılamadı” uyarısı çıkar.
- Görüntü zaman zaman **siyah** geliyorsa: UAC (yönetici onayı) penceresi açıkken Windows
  “güvenli masaüstü”ne geçer ve o ekran yakalanamaz. Bu normaldir.

**Yanlışlıkla Windows Güvenlik Uyarısı'nda “İptal”e bastım**

Windows, `python.exe` ya da `mediamtx.exe` için *engelleme* kuralı oluşturmuştur.
*Başlat → “Gelişmiş Güvenlik Özellikli Windows Defender Güvenlik Duvarı” → Gelen Kuralları*
bölümünde adı `python`/`mediamtx` olan ve **kırmızı engel simgeli** kuralları silin, sonra
`start-teacher.bat`'ı yeniden başlatın.

**“Sunucu başlatılamadı (port 8000 kullanımda olabilir)”**

Başka bir program 8000'i kullanıyor ya da eski sunucu penceresi hâlâ açık. Eski pencereyi
kapatın. Portu değiştirmek gerekirse bkz. bölüm 7.

**Panel başka bir bilgisayardan açılmıyor**

Bilinçli: panel yalnızca öğretmen bilgisayarından (`localhost`) açılır.

**35 kutu aynı anda oynarken tarayıcı zorlanıyor**

**Diğer** menüsünde **Görünmeyen ekranları duraklat**'ı açın; üst satırdaki
**Sığdır** açıkken kutular zaten en küçük uygun boyuttadır. Yetmezse `config.yaml` → `yayin`
altından fps/genişlik/bit hızını düşürün.

**“Klasör seç”e bastım, pencere gelmedi**

Klasör penceresi tarayıcının arkasında kalmış olabilir: görev çubuğuna bakın (düğmede
“Pencere açık…” yazar). Pencere hiç açılamıyorsa panel kendiliğinden bir kutu gösterir;
klasörün tam yolunu (ör. `D:\Sınavlar\Vize`) yazıp **Kullan**'a basın — klasör yoksa
oluşturulur.

**Panelde “Sınav klasörüne ulaşılamıyor” yazıyor**

Seçtiğiniz klasörün bulunduğu disk (USB bellek, ağ sürücüsü) çıkarılmış ya da klasör
silinmiş. Diski geri takın. Sınav başlamadıysa **Sınav klasörü → Değiştir** ile başka bir
klasör seçebilirsiniz.

**Wi-Fi zorlanıyor (görüntüler takılıyor, kopmalar oluyor)**

35 öğrenci × 500 kbps ≈ 17,5 Mbps sürekli yükleme demektir. `yayin.fps: 3`,
`genislik: 960`, `bitrate_kbps: 300` deneyin. Öğretmen bilgisayarını modeme kabloyla bağlayın.

## 10. Gizlilik ve sınırlar

- Ajan öğrenci bilgisayarında **kalıcı iz bırakmaz**: servis kurmaz, başlangıca
  eklenmez, kayıt defterine yazmaz, zamanlanmış görev oluşturmaz. Kendi klasörüne
  (`%LOCALAPPDATA%\SinavAjan\`) yalnızca küçük bir günlük ve not dosyası yazar. Sınav
  dosyası öğrencinin seçtiği yere kaydedilir ve sınavdan sonra orada kalır. Ajan kapanınca ffmpeg dahil hiçbir şey
  çalışmaya devam etmez (ffmpeg bir Windows *Job Object* içinde çalışır; ajan Görev
  Yöneticisi'nden sonlandırılsa bile Windows ffmpeg'i kapatır).
- Giriş anından teslime/kapanışa kadar öğretmene şunlar gider: ekranın tamamı (tüm
  monitörler), öndeki pencerenin program adı ve başlığı, kapatılan programların adı,
  bilgisayar adı, IP ve MAC adresi, monitör sayısı, başka bir sanal masaüstüne geçildiği,
  ve teslimde öğrencinin **seçtiği** dosya (adıyla birlikte). Program öğrencinin başka
  hiçbir dosyasını okumaz ya da göndermez.
- Kapsam dışı: macOS/Linux öğrenci bilgisayarı, telefon gibi ikinci cihazların tespiti,
  ajanın sahte görüntü göndermeye karşı korunması, sınıflar arası merkezî sunucu.
