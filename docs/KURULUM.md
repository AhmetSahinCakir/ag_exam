# Sınav İzleme Sistemi — Kullanım Kılavuzu

Bu kılavuz sınavı yapan kişi içindir. Öğrencilere verilecek kılavuz: [OGRENCI.md](OGRENCI.md).
Sınavdan önce yapılacak deneme: [PROVA.md](PROVA.md).

## Sistem ne yapar?

- Öğrencilerin ekranını canlı gösterir; isterseniz kaydeder.
- Sınav sırasında Packet Tracer dışındaki programları kapatır ve size bildirir.
- Sınav dosyasını öğrencilere verir, teslim edilen dosyaları toplar.

İnternet gerekmez. Her sınıf kendi modemi ve kendi bilgisayarıyla çalışır.

## İlk kurulum (bir kez)

1. **Kurulum dosyasını indirin.** [İndirme sayfasından](https://github.com/AhmetSahinCakir/ag_exam/releases/latest)
   **`SinavIzleme-Kurulum.exe`** dosyasını indirin.
2. **Dosyaya çift tıklayın**, açılan pencerede **Kur**'a, kurulum bitince **Bitti**'ye basın.
   Başka bir şey kurmanız gerekmez; **Bitti**'ye basınca sistem kendiliğinden açılır.
   - “Windows kişisel bilgisayarınızı korudu” çıkarsa **Ek bilgi → Yine de çalıştır** deyin.
   - “Bu uygulamanın cihazınızda değişiklik yapmasına izin veriyor musunuz?” sorusuna
     **Evet** deyin.
3. **Sınıf adını ve adınızı yazın.** Panel ilk açıldığında bunları sorar. Öğrenciler doğru
   sınıfa bağlandıklarını bu addan anlar; her sınıfta farklı olmalıdır. Sonradan değiştirmek
   için panelin sol üstündeki **Düzenle**'ye basın.
4. **Sonraki açılışlarda** masaüstündeki **Sınav İzleme Sistemi** simgesine çift tıklayın;
   birkaç saniye içinde panel açılır.
5. **Öğrencilere programı gönderin.** Aynı indirme sayfasındaki **`SinavAjan-Kurulum.exe`**
   dosyasını (ya da sayfanın bağlantısını) öğrencilere gönderin. Öğrenci dosyaya çift
   tıklayınca program kurulur ve masaüstüne **Sınav Ajanı** simgesi gelir.
   - Kurmayı unutan öğrenci sınav günü programı sınıf ağından da indirebilir: panelde
     **Diğer** menüsünde yazan adresi tarayıcısına yazar.
6. **Modemi kontrol edin.** Sizin ve öğrencilerin bilgisayarı aynı modeme bağlı olmalıdır.
   Modemde cihazların birbirini görmesini engelleyen ayar (“AP izolasyonu”) kapalı olmalıdır.
7. **Bir deneme yapın:** [PROVA.md](PROVA.md).

Kurulumdan sonra internet gerekmez.

**Yeni sürüm çıkarsa** yeni kurulum dosyasını indirip çalıştırın; eskisinin üzerine kurulur.
**Kaldırmak için:** Ayarlar → Uygulamalar → *Sınav İzleme Sistemi* → Kaldır. Sınav
klasörleriniz (kayıtlar, teslimler) silinmez.

## Sınav günü

### 1. Sistemi açın

Bilgisayarınızı sınıf modemine bağlayın ve masaüstündeki **Sınav İzleme Sistemi** simgesine
çift tıklayın. Birkaç saniye içinde panel kendi penceresinde açılır.

### 2. Sınavı hazırlayın

Panelin üstündeki üç adımı sırayla yapın:

1. **Sınav klasörü → Klasör seç.** Bu sınavın dosyalarının duracağı klasörü seçin. İçinde üç
   klasör açılır: **Kayıtlar** (ekran kayıtları), **Teslimler** (teslim edilen dosyalar),
   **Uyarılar** (her öğrencinin kayıt dosyası). Her sınav için ayrı bir klasör seçin.
2. **Sınav dosyası → Dosya seç.** Öğrencilere verilecek `.pka` dosyası.
3. **Öğrenci listesi → Dosya seç.** İsteğe bağlıdır. Açılan pencere dosyanın nasıl olması
   gerektiğini gösterir (aşağıya bakın); oradaki **Dosya seç** ile listeyi yükleyin. Listeyi
   yüklediğiniz anda bütün öğrenciler siyah ekranlı kutular olarak ve sağdaki listede
   “Giriş yapmadı” diye görünür.

### 3. Öğrenciler giriş yapar

Öğrenciler modeme bağlanıp programı açar ve giriş yapar. Her öğrencinin ekranı solda, adı
sağdaki listede görünür (ekranın gelmesi 10 saniye kadar sürebilir). Liste yüklediyseniz giriş yapan öğrencinin siyah kutusu canlı
ekrana döner ve öne geçer; kimin eksik olduğunu kalan siyah kutulardan görürsünüz. Bu sırada
hiçbir program kapatılmaz; öğrenciler Packet Tracer'ı açıp hesaplarına giriş yapsın.

### 4. Sınavı başlatın

**Sınavı başlat**'a basın. Açılan pencerede:

- **Başlangıç:** hemen ya da seçtiğiniz saatte.
- **Sınav süresi:** isteğe bağlıdır. Yazarsanız öğrenciler geri sayım görür. **Süre dolunca
  sınav kendiliğinden bitmez;** panelde “süre aşıldı” yazar ve sınavı siz bitirirsiniz.
- **Ekranları kaydet:** işaretliyse ekranlar *Kayıtlar* klasörüne kaydedilir. İşaretli
  değilse ekranları yalnızca canlı izlersiniz. Öğrenci bu seçimi göremez.

Sınav başladıktan sonra kaydı istediğiniz an değiştirebilirsiniz: kayıt açıkken üstte
**Kaydı durdur**, kapalıyken **Kaydı başlat** düğmesi görünür. Kayıt yalnızca açık olduğu
sürelerde yapılır; kapalıyken geçen süre kaydedilmez. Kaydın durumu üst satırda **Kayıt**
başlığının altında yazar.

Bir öğrencinin kaydı, dosyasını teslim edince kendiliğinden biter. **Sınavı bitirmek kaydı
durdurmaz:** teslim etmemiş öğrencinin ekranı, teslim edene ya da siz **Kaydı durdur**'a
basana kadar kaydedilir. Giriş yapan herkes teslim edince kaydedilecek ekran kalmaz; üst
satırda **Kayıt: Bitti** yazar.

Sınav başlayınca öğrencilerde kısa bir geri sayımdan sonra izin verilmeyen programlar
kapanır ve öğrencinin panelinde **Sınav dosyasını indir** düğmesi çıkar. Hiçbir şey
kendiliğinden açılmaz ya da inmez; dosyayı öğrenci istediği yere kendisi indirir.

### 5. Sınavı izleyin

- **Renkler:** yeşil = bağlı, sarı = uyarı var, kırmızı = bağlantı yok (sınav bitince:
  teslim etmedi), mavi = teslim etti, gri = giriş yapmadı. Görüntüsü henüz gelmemiş ekranlar
  gri görünür.
- **Sayılar:** listenin üstünde toplam öğrenci sayısı ve her durumdaki öğrenci sayısı yazar.
- Ekranların altında ve listede öğrencinin **adı soyadı** yazar; öğrenciler ada göre
  sıralanır. Yalnızca numarayı ya da ikisini birlikte göstermek için **Diğer → Ayarlar →
  Öğrencilerin gösterimi**. Teslim dosyalarının, kayıt klasörlerinin adlarında ve kayıt
  dosyalarında numara her zaman vardır.
- **Uyarılar** öğrencinin satırında, adının yanında görünür. Satırdaki oka basınca o
  öğrencinin uyarıları açılır. **Görüldü**'ye basınca kaç uyarının işaretlendiği yazılır ve
  o uyarılar soluklaşıp **✓** alır. Hepsini birden işaretlemek için sayıların altındaki
  **Tümünü görüldü yap**.
- Bir ekrana tıklayınca büyür. Sağında yalnızca o öğrencinin **uyarıları** görünür; giriş,
  pencere geçişi gibi öteki kayıtlar altındaki **Diğer kayıtlar** başlığına basınca açılır.
- Öğrencinin Packet Tracer pencereleri arasında geçiş yapması (Alt+Tab) ve masaüstüne
  bakması uyarı sayılmaz; yalnızca “Diğer kayıtlar”a yazılır. Öne başka bir pencere gelirse
  uyarı çıkar.
- **Ekran boyutu:** üst satırdaki **− / +** ile ekranları büyütüp küçültün; **Sığdır**
  hepsini ekrana sığdırır.
- **Listenin genişliği:** listenin sol kenarını fareyle tutup sürükleyin; kenara çift
  tıklayınca ilk genişliğine döner.
- **Listeyi daraltmak:** “Öğrenciler” başlığının yanındaki oka basın; listeyi geri açmak için
  sağdaki şeride tıklayın.
- Teslim edenlerin ekranı kendiliğinden en alta gider.
- Sesli uyarı için **Diğer → Uyarılarda ses çal**.

### 6. Teslim

Öğrenci **Teslim et**'e basıp dosyasını seçer. Dosya *Teslimler* klasörüne gelir, öğrenci
“Teslim etti” olur ve programı kapanır.

- **Otomatik teslim yoktur.** Dosyayı yalnızca öğrencinin kendisi teslim eder.
- Öğrenci indirdiği sınav dosyasını hiç değiştirmeden ya da eski bir dosyayı teslim etmeye
  çalışırsa önce kendisi uyarılır; yine de teslim ederse size uyarı düşer.
- Elden aldığınız bir dosyayı *Teslimler* klasörüne kendiniz koyabilirsiniz. Dosyanın adı
  öğrencinin numarasıyla başlamalıdır (ör. `2021000001_ali.pka`); öğrenci “Teslim etti” olur.
- Sistem dosyanın içini değerlendiremez; çözümü görmek için dosyayı Packet Tracer'da açın.

### 7. Sınavı bitirin

**Sınavı bitir**'e basınca bir pencere açılır:

- **Ek süre ver:** dakikayı yazıp düğmeye basın; öğrencilerin geri sayımı uzar.
- **Sınavı bitir:** sınav biter.

Sınav bitince teslim etmemiş öğrencilerin programı kapanmaz; ekranlarında **Teslim
edilmedi** yazar. Dosyalarını yine teslim edebilirler; bu teslim **geç teslim** olarak
işaretlenir ve size uyarı düşer.

### 8. Sistemi kapatın

Herkes teslim ettikten sonra **panel penceresini kapatın; sistem kendiliğinden kapanır.**

- Bağlı öğrenci varken sistem kapanmadan önce 2 dakika bekler. Pencereyi yanlışlıkla
  kapattıysanız bu sürede masaüstündeki simgeye yeniden çift tıklayın: panel geri açılır,
  sınav kaldığı yerden sürer.
- **Teslim etmemiş öğrenci varken sistemi kapatırsanız o öğrencilerin dosyası alınmaz.**
  Kapatmadan önce listede herkesin “Teslim etti” olduğuna bakın.
- Aynı gün ikinci bir sınav yapacaksanız sistemi kapatmadan **Yeni sınav**'a basın.

## Sınavdan sonra

Her şey seçtiğiniz sınav klasöründedir (**Sınav klasörünü aç** düğmesi klasörü açar):

| Klasör / dosya | İçinde ne var |
|---|---|
| **Teslimler** | Teslim edilen dosyalar: `numara_AdSoyad.pka`. `index.csv` dosyası kimin ne zaman teslim ettiğini ve geç teslimleri listeler. |
| **Kayıtlar** | Her öğrencinin ekran kaydı, numarası ve adıyla adlandırılmış klasörlerde (ör. `2021000001_AliVeli`). Video oynatıcıyla (ör. VLC) açılır. |
| **Uyarılar** | Her öğrenci için bir dosya (ör. `2021000001_AliVeli.csv`); Excel'de açılır. En üstte öğrencinin bilgileri (numara, ad soyad, bilgisayar adı, IP ve MAC adresi, teslim durumu), altında o öğrencinin **bütün kayıtları** vardır: uyarılar ve giriş, pencere geçişi gibi öteki kayıtlar. |
| `olay-kaydi.csv` | Sınav boyunca olan her şeyin saatli dökümü; Excel'de açılır. |

Ekran kayıtları kendiliğinden silinmez; saklama süresi dolunca *Kayıtlar* klasörünü siz
silin. Ekran durduğu sürece kayıt çok az yer tutar; ne kadar yer tutacağı öğrencilerin
ekranının ne kadar değiştiğine bağlıdır:

| Ekran görüntüsü (Ayarlar) | 35 öğrenci, 100 dakika — genellikle | En çok (ekranlar sürekli değişirse) |
|---|---|---|
| Düşük (540p) | 0,5–2,5 GB | 8 GB |
| Normal (720p) | 1–4 GB | 13,5 GB |
| Yüksek (900p) | 1,5–5 GB | 24 GB |

Öteki dosyalar (*Uyarılar*, *Teslimler*, `olay-kaydi.csv`) birkaç MB'ı geçmez.

Bu rakamlar öğrenci programının 1.0.3 ve sonraki sürümleri içindir. Daha eski sürümü
kullanan öğrencinin kaydı her zaman “en çok” sütunundaki kadar yer tutar; öğrencilerin
güncel kurulum dosyasını kurmuş olması yeterlidir.

## Öğrenci listesi (isteğe bağlı)

Excel (`.xlsx`) ya da `.csv` dosyası. İlk satır başlık olmalı; şu üç sütun yeterlidir:

| Numara | Ad | Soyad |
|---|---|---|
| 2021000001 | Ali | Veli |
| 2021000002 | Ayşe | Yılmaz |

- **Numara 10 haneli** olmalı ve yalnızca rakamlardan oluşmalıdır. Uymayan satır varsa liste
  yüklenmez; hangi satırların uymadığı yazılır.
- Sütunların sırası önemli değildir; başka sütunlar (sıra no, bölüm…) varsa dikkate alınmaz.
- Ad ve soyad tek sütunda (**Ad Soyad**) da olabilir.
- Dosyada birden çok sayfa varsa ilk sayfa okunur.
- Liste penceresindeki **Örnek dosyayı indir** ile boş bir örnek alıp doldurabilirsiniz.

Liste yüklüyse:

- Listede olmayan bir numarayla ya da farklı bir adla giriş yapılırsa uyarı çıkar (giriş yine
  kabul edilir).
- Listedeki bütün öğrenciler, sınav başlamadan da, siyah ekranlı kutular olarak ve sağdaki
  listede görünür. Giriş yapmayanların yanında **Giriş yapmadı** yazar; üstteki sayılarda
  kaç kişinin giriş yapmadığını görürsünüz.

**Elle öğrenci eklemek:** “Öğrenciler” başlığının yanındaki **+ Öğrenci ekle**'ye basıp
numarasını, adını ve soyadını yazın. Sınavdan önce, sınav sürerken ya da sonra eklenebilir;
liste dosyası yüklemeden de kullanılabilir. “Numara listede yok” uyarısı alan bir öğrenciyi
satırını açıp **Listeye ekle** ile tek tıkla ekleyebilirsiniz. Yanlış eklediğiniz ya da
gelmeyecek bir öğrenciyi, giriş yapmadıysa, satırını açıp **Listeden çıkar** ile silin.

## Ayarlar

Panelde **Diğer → Ayarlar**:

- **İzin verilen programlar:** Sınavda Packet Tracer dışında bir programa da izin vermek
  için **+ Program ekle**'ye basın. Açılan listede sık kullanılan programlar (tarayıcılar,
  Visual Studio Code, PuTTY…) ve bilgisayarınızda kurulu programlar görünür; üstteki kutuya
  adını yazarak arayın ve yanındaki **Ekle**'ye basın. Listede olmayan bir programı dosya
  adını yazarak (ör. `putty.exe`) ya da **Bilgisayardan seç** ile ekleyin. Sınav sürerken
  de eklenebilir; hemen geçerli olur.
- **Öğrencilerin gösterimi:** Ekranların altında ve listede **ad soyad**, **numara** ya da
  **ikisi birlikte** yazılır.
- **Ekran görüntüsü:** **Düşük** (540p), **Normal** (720p) ya da **Yüksek** (900p).
  Görüntüler takılıyorsa **Düşük**'ü seçin. Kalite arttıkça kayıtlar daha çok yer tutar
  (“Sınavdan sonra” bölümündeki tabloya bakın). Değişiklik, öğrencinin bir sonraki
  girişinde geçerli olur.
- **Uyarılar ve süreler:** Başka pencereye geçince kaç saniye sonra uyarı verileceği,
  sınav başlayınca programların kaç saniye sonra kapatılacağı gibi süreler.
- **Öğrenciye gösterilen bilgilendirme:** Öğrencinin giriş yapmadan önce gördüğü yazı.

**Varsayılanlara dön** bütün ayarları ilk hâline getirir.

## Uyarılar ne demek?

| Uyarı | Anlamı |
|---|---|
| … kapatıldı | Öğrenci izin verilmeyen bir program açtı; program kapatıldı. |
| Packet Tracer dışında bir pencere önde | Öğrenci 5 saniyeden uzun süre başka bir pencereye baktı. |
| Başka bir masaüstüne geçti | Öğrenci Windows'un ikinci masaüstüne geçti. |
| Monitör sayısı: 2 | İkinci bir ekran takılı. |
| Bağlantı … kesik kaldı | Öğrencinin bağlantısı 1 dakikadan uzun süre koptu (Wi-Fi kapandı ya da bilgisayar uyudu). Bağlantı koptuğu sürece kutu kırmızıdır. |
| Ajan öğrenci tarafından kapatıldı | Öğrenci programı kapattı. |
| Bu bilgisayardan daha önce … giriş yapmıştı | Aynı bilgisayardan başka bir numarayla giriş yapıldı. Uyarıda önceki girişin numarası ve yazılan ad soyad da yer alır. |
| Aynı numarayla ikinci oturum açma girişimi | Bu numara başka bir bilgisayarda zaten açık. |
| Ad uyuşmuyor / Numara listede yok | Girişteki bilgiler öğrenci listesiyle uyuşmuyor. |
| Teslim edilen dosya sınav dosyasının kendisi | Öğrenci hiçbir şey kaydetmeden teslim etti. |
| … ile birebir aynı dosyayı teslim etti | İki öğrencinin dosyası tıpatıp aynı. |
| Geç teslim | Dosya sınav bittikten sonra teslim edildi. |
| Teslim dosyası klasörde bulunamıyor | Teslim edilen dosya *Teslimler* klasöründen silinmiş ya da taşınmış. |
| Sınav süresi doldu | Verdiğiniz süre bitti; sınav sürüyor, bitirmek size kalmış. |

**Uyarı sayılmayanlar** (yalnızca öğrencinin kayıt dosyasına ve “Diğer kayıtlar”a yazılır):

- Sınav başlarken açık olan programların kapatılması. Uyarı, yalnızca sınav sırasında
  açılan program için çıkar.
- Packet Tracer pencereleri arasında geçiş (Alt+Tab) ve masaüstüne bakmak.
- 1 dakikadan kısa bağlantı kesintileri.
- Aynı pencerenin önde kalmayı sürdürmesi: bunun için tek uyarı çıkar. Uyarıyı **Görüldü**
  yaptıktan sonra pencere hâlâ öndeyse yeniden uyarılırsınız.

## Sorun olursa

**Öğrenci programı sınavı bulamıyor.**
Öğrenci doğru Wi-Fi ağına bağlı mı? Sistem sizin bilgisayarınızda açık mı? Olmuyorsa
öğrenci, panelde **Diğer** menüsünde yazan adresi programa elle yazabilir.

**Öğrenci giriş yaptı ama ekranı gelmiyor.**
Öğrencinin antivirüsü programı engellemiş olabilir (çözümü öğrenci kılavuzunda). Panelin
üstünde kırmızı bir uyarı varsa yazanı uygulayın.

**Görüntüler takılıyor.**
Bilgisayarınızı modeme kabloyla bağlayın. **Diğer → Görünmeyen ekranları duraklat**'ı açın.
Yetmezse **Diğer → Ayarlar**'da ekran görüntüsünü **Düşük** yapın.

**Simgeye tıkladım, bir şey olmadı.**
Panelin açılması 10–20 saniye sürebilir. Açılmazsa simgeye yeniden çift tıklayın.

**Panel penceresini yanlışlıkla kapattım.**
Masaüstündeki simgeye yeniden çift tıklayın; panel geri açılır.

**Bilgisayar ya da sistem sınav sırasında kapandı.**
Sistemi masaüstündeki simgeden yeniden açın. Sınav kaldığı yerden sürer, öğrenciler
kendiliğinden yeniden bağlanır.

**“Klasör seç”e bastım, pencere gelmedi.**
Pencere başka bir pencerenin arkasında kalmış olabilir; görev çubuğuna bakın.

**Sınavda başka bir programa da izin vermem gerekiyor.**
Panelde **Diğer → Ayarlar**'ı açın, **İzin verilen programlar** bölümüne programın adını
ekleyip **Kaydet**'e basın. Hemen geçerli olur.
