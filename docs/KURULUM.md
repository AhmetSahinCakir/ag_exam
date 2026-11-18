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
 │  • ekran → H.264 → RTSP  │                 │  • diske kayıt (recordings/)       │
 └──────────────────────────┘                 │  • panele WebRTC (yalnızca yerel)  │
                                              └────────────────────────────────────┘
```

- Her sınıf **bağımsızdır**: kendi modemi, kendi öğretmen bilgisayarı, kendi sunucusu.
- Sınav sırasında **internet gerekmez**. Panel dahil her şey yereldir.
- Ajan sunucuyu **kendisi bulur** (UDP yayını). Ajanda kayıtlı IP adresi yoktur; aynı ajan
  paketi üç sınıfta da kullanılır.
- Öğrenci, ajanda büyük harflerle sınıf ve öğretmen adını görüp onaylar. Yanlış modeme
  bağlanan öğrenci bunu orada fark eder. **Bu yüzden her sınıfta `sinif_adi` farklı olmalı.**

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
4. **`server\config.yaml` dosyasını düzenleyin** (Not Defteri ile):
   ```yaml
   sinif_adi: "B-102"
   ogretmen_adi: "Adınız Soyadınız"
   ```
   Kaydedip `start-teacher.bat` penceresini kapatın ve yeniden başlatın. Bu iki satır
   **her sınıfın bilgisayarında farklı** olmalı.
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
   Panel açılır; üstte sınıf/öğretmen adı ve **BEKLİYOR** yazar.
2. Panelde:
   - **Sınav dosyası yükle (.pka)** — öğrencilere dağıtılacak dosya.
   - **Öğrenci listesi yükle (Excel)** — isteğe bağlı (bkz. bölüm 6).
3. Öğrenciler modeme bağlanır, ajanı **yönetici olarak** çalıştırır, sınıf/öğretmen adını
   onaylar ve giriş yapar. Her öğrenci panelde canlı görüntüsüyle bir kutu olarak belirir.
   Kutuda numara, ad soyad, **IP · bilgisayar adı · MAC** ve öndeki program yazar.
   - Bu aşamada izin listesi **uygulanmaz**. Öğrenciler Packet Tracer'ı açıp Cisco
     hesabıyla giriş yapsın (giriş tarayıcı açar; sınav başlayınca tarayıcı kapatılır).
   - “Listede olup giriş yapmayanlar” bölümü kimin eksik olduğunu gösterir.
4. Herkes hazır olunca isterseniz **Süre (dk)** yazıp **Sınavı başlat**'a basın. Öğrencide:
   - “Sınav başlıyor. İzin verilmeyen programlar 10 saniye içinde kapatılacak.” uyarısı
     ve geri sayım görünür,
   - sınav dosyası indirilir ve Packet Tracer ile açılır,
   - geri sayım bitince uygulama denetimi başlar; ajan küçük bir yan panele dönüşür.
5. Sınav boyunca paneli izleyin:
   - **Yeşil** = normal, **sarı** = görülmemiş uyarı var, **kırmızı** = bağlantı yok
     (10 sn sinyal yok ya da ekran yayını yok), **gri** = teslim etti.
   - Sağdaki **Son uyarılar** akışında en yeni uyarı üsttedir; tıklayınca o öğrenci
     büyür. **Sesli bildirim** kutusunu işaretleyebilirsiniz.
   - Kutuya tıklayınca büyük görüntü, öğrencinin bilgileri ve **olay geçmişi** açılır.
     “Uyarıları görüldü işaretle” kutuyu yeniden yeşile çevirir.
   - Süre vermişseniz üstte kalan süre görünür. Süre dolunca sınav **kendiliğinden
     bitmez**; bitirmek için düğmeye basmanız gerekir.
6. Öğrenci **Teslim et**'e basınca dosyası yüklenir, kutusu griye döner, ajanı kapanır.
7. Süre bitince **Sınavı bitir**'e basın (onay ister). Teslim etmemiş öğrencilerin son
   kaydettiği dosya **otomatik** toplanır (olay kaydında “Otomatik teslim” yazar) ve
   ajanlar kapanır. Teslim dosyası gelmeyenler kırmızı “Teslim yok” olarak kalır.
8. **Olayları CSV olarak dışa aktar** ile olay kaydını indirin (Excel'de açılır).

### Uyarılar ne anlama gelir?

| Uyarı | Anlamı |
|---|---|
| `chrome.exe kapatıldı — pencere: “…”` | İzinsiz bir program pencere açtı; ajan onu kapattı. |
| `Packet Tracer dışında bir pencere önde: explorer.exe (6 sn)` | İzin listesinde olmayan bir pencere 5 sn'den uzun süre öndeydi. Windows'un kendi programları (Dosya Gezgini, Ayarlar, Komut İstemi…) kapatılmaz, yalnızca bu şekilde bildirilir. |
| `Monitör sayısı: 2` | İkinci ekran takılı ya da sınav sırasında takıldı/çıkarıldı. |
| `Bağlantı koptu — ajandan sinyal gelmiyor / ekran yayını yok` | Wi-Fi koptu, bilgisayar uyudu ya da ajan kapandı. Bağlantı gelince kutu kendiliğinden yeşile döner. |
| `Ajan öğrenci tarafından kapatıldı` | Öğrenci ajan penceresini kapattı (onay vererek). |
| `Aynı numarayla ikinci oturum açma girişimi reddedildi` | Bu numara başka bir bilgisayarda zaten açık. |
| **`Bu bilgisayardan daha önce <numara> giriş yapmıştı`** (kırmızı) | Aynı bilgisayardan (MAC) farklı bir numarayla giriş yapıldı. |
| `Farklı bir bilgisayardan yeniden giriş yaptı` | Öğrencinin oturumu düştükten sonra başka bir bilgisayardan girildi. |
| `Ad uyuşmuyor` / `Numara öğrenci listesinde yok` | Girişteki bilgiler listeyle uyuşmuyor (giriş yine de kabul edilir). |
| **`… ile birebir aynı dosyayı teslim etti`** (kırmızı) | İki farklı öğrencinin dosyasının SHA-256 özeti aynı. |
| `Teslim edilen dosya sınav dosyasıyla birebir aynı` | Öğrenci hiçbir şey kaydetmeden teslim etti (boş teslim). |
| **`Ekran yayını farklı bir IP adresinden geliyor`** (kırmızı) | Yayın, giriş yapılan bilgisayardan gelmiyor. |
| `Packet Tracer açılamadı` | Öğrencide Packet Tracer bulunamadı; öğrenci dosyayı elle açmalı. |

Her öndeki pencere değişimi, yayın yeniden başlatmaları, girişler ve teslimler uyarı
olarak değil **olay kaydına** yazılır (büyük pencerede ve CSV'de görünür).

## 5. Sınavdan sonra

| Ne | Nerede |
|---|---|
| Teslim dosyaları | `submissions\<numara>_<AdSoyad>.pka` (Türkçe harfler çevrilir: `2021001_AhmetSahinCakir.pka`). Aynı öğrencinin sonraki teslimleri `_v2`, `_v3` olarak ayrıca saklanır. |
| Teslim dökümü | `submissions\index.csv` — zaman, numara, ad, dosya, **SHA-256**, boyut, otomatik mi, sürüm, IP, bilgisayar, MAC |
| Ekran kayıtları | `recordings\s\<numara>\<tarih-saat>.mp4` — 10 dakikalık bölümler. Bağlantı kopup geri gelince yeni dosya başlar. VLC ile oynatılır. |
| Olay kaydı | Panelden CSV; ham hali `data\events.jsonl` |
| MediaMTX günlüğü | `data\mediamtx.log` |

- **Yeni sınav:** Paneldeki **Yeni sınav** düğmesi (sınav sürerken kullanılamaz) mevcut
  teslimleri, olay kaydını ve sınav dosyasını **silmez**; `data\arsiv\<tarih-saat>\`
  klasörüne taşır ve paneli boşaltır. Öğrenci listesi korunur. Ekran kayıtları
  `recordings\` altında kalır.
- Sunucu sınav sırasında kapanırsa (elektrik, yanlışlıkla kapatma) `start-teacher.bat`'ı
  yeniden çalıştırın: sınav durumu, öğrenciler ve olaylar `data\state.json` dosyasından
  **geri yüklenir**, ajanlar kendiliğinden yeniden bağlanır.
- **Kayıt saklama:** Ekran kayıtları **otomatik silinmez**. Kurumunuzun kuralına göre
  `config.yaml` içindeki `kayit_saklama_notu` metnini düzenleyin (öğrenciye giriş
  ekranında gösterilir) ve süre dolunca `recordings\` klasörünü elle silin.

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
| `sinif_adi`, `ogretmen_adi` | — | Ajanda gösterilir; her sınıfta farklı olmalı |
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
| `klasorler.*` | `../submissions` … | Klasör yolları |
| `kayit_saklama_notu` | — | Öğrenciye ve panelde gösterilen saklama açıklaması |

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
adres `webrtcAdditionalHosts` ile verilir; HLS/RTMP/SRT/MoQ kapalı; `s/` altındaki tüm
yollar fMP4 olarak 10 dakikalık bölümlerle kaydedilir; okuma yalnızca `127.0.0.1`.

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
5. Yedek yol: öğrenci ajanda **elle IP** girer. IP, sunucu penceresinde ve panelin
   üstündeki sarı şeritte yazar. Elle IP çalışıp keşif çalışmıyorsa sorun UDP yayınındadır
   (modem ayarı ya da güvenlik duvarı).

**Öğrenci giriş yaptı ama görüntü yok / kutu “ekran yayını yok” ile kırmızı**

- MediaMTX penceresi açık mı? Panelin üstünde “MediaMTX çalışmıyor” yazıyorsa
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

Paneldeki **Görünmeyen kutuları duraklat** kutusunu işaretleyin ve **Kutu boyutu** ile
kutuları küçültün. Yetmezse `config.yaml` → `yayin` altından fps/genişlik/bit hızını düşürün.

**Wi-Fi zorlanıyor (görüntüler takılıyor, kopmalar oluyor)**

35 öğrenci × 500 kbps ≈ 17,5 Mbps sürekli yükleme demektir. `yayin.fps: 3`,
`genislik: 960`, `bitrate_kbps: 300` deneyin. Öğretmen bilgisayarını modeme kabloyla bağlayın.

## 10. Gizlilik ve sınırlar

- Ajan öğrenci bilgisayarında **kalıcı iz bırakmaz**: servis kurmaz, başlangıca
  eklenmez, kayıt defterine yazmaz, zamanlanmış görev oluşturmaz. Yalnızca
  `%LOCALAPPDATA%\SinavAjan\` altına sınav dosyasını ve günlük kaydını yazar; öğrenci
  “Sınav dosyalarımı temizle” ile bunları siler. Ajan kapanınca ffmpeg dahil hiçbir şey
  çalışmaya devam etmez (ffmpeg bir Windows *Job Object* içinde çalışır; ajan Görev
  Yöneticisi'nden sonlandırılsa bile Windows ffmpeg'i kapatır).
- Giriş anından teslime/kapanışa kadar öğretmene şunlar gider: ekranın tamamı (tüm
  monitörler), öndeki pencerenin program adı ve başlığı, kapatılan programların adı,
  bilgisayar adı, IP ve MAC adresi, monitör sayısı.
- Kapsam dışı: macOS/Linux öğrenci bilgisayarı, telefon gibi ikinci cihazların tespiti,
  ajanın sahte görüntü göndermeye karşı korunması, sınıflar arası merkezî sunucu.
