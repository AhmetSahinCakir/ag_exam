# Sınav İzleme Sistemi — Kullanım Kılavuzu

Bu kılavuz sınavı yapan kişi içindir. Öğrencilere verilecek kılavuz: [OGRENCI.md](OGRENCI.md).
Sınavdan önce yapılacak deneme: [PROVA.md](PROVA.md).

## Sistem ne yapar?

- Öğrencilerin ekranını canlı gösterir; isterseniz kaydeder.
- Sınav sırasında Packet Tracer dışındaki programları kapatır ve size bildirir.
- Sınav dosyasını öğrencilere verir, teslim edilen dosyaları toplar.

İnternet gerekmez. Her sınıf kendi modemi ve kendi bilgisayarıyla çalışır.

## İlk kurulum (bir kez, internet varken)

1. **Python'u kurun.** <https://www.python.org/downloads/> adresinden indirin. Kurulumun ilk
   ekranında **“Add python.exe to PATH”** kutusunu işaretleyin.
2. **Sistemi indirin.** GitHub sayfasında **Code → Download ZIP** deyin, zip'i bir klasöre
   açın (ör. `C:\sinav`).
3. **`scripts` klasöründeki `start-teacher.bat` dosyasına çift tıklayın.** İlk seferde
   gerekenleri kendisi indirir ve bir izin penceresi açar; **Evet** deyin. Birkaç dakika
   sonra panel açılır.
   - “Windows Güvenlik Uyarısı” çıkarsa iki kutuyu da işaretleyip **Erişime izin ver** deyin.
4. **Sınıf adını ve adınızı yazın.** Panelin sol üstündeki **Düzenle**'ye basın. Öğrenciler
   doğru sınıfa bağlandıklarını bu addan anlar; her sınıfta farklı olmalıdır.
5. **Öğrenci programını indirin.** GitHub sayfasında **Actions → build-agent →** en üstteki
   yeşil satır **→** sayfanın altında **Artifacts → SinavAjan-win-x64**. İnen zip'i
   öğrencilere dağıtın. (Adını `SinavAjan.zip` yapıp `dist` klasörüne koyarsanız öğrenciler
   sınav günü sınıf ağından da indirebilir.)
6. **Modemi kontrol edin.** Sizin ve öğrencilerin bilgisayarı aynı modeme bağlı olmalıdır.
   Modemde cihazların birbirini görmesini engelleyen ayar (“AP izolasyonu”) kapalı olmalıdır.
7. **Bir deneme yapın:** [PROVA.md](PROVA.md).

Kurulumdan sonra internet gerekmez.

## Sınav günü

### 1. Sistemi açın

Bilgisayarınızı sınıf modemine bağlayın ve `start-teacher.bat` dosyasını çalıştırın. Panel
kendi penceresinde açılır. Siyah başlatma penceresini kapatmayın (küçültebilirsiniz).

### 2. Sınavı hazırlayın

Panelin üstündeki üç adımı sırayla yapın:

1. **Sınav klasörü → Klasör seç.** Bu sınavın dosyalarının duracağı klasörü seçin. İçinde üç
   klasör açılır: **Kayıtlar** (ekran kayıtları), **Teslimler** (teslim edilen dosyalar),
   **Uyarılar** (her öğrencinin uyarıları). Her sınav için ayrı bir klasör seçin.
2. **Sınav dosyası → Dosya seç.** Öğrencilere verilecek `.pka` dosyası.
3. **Öğrenci listesi → Dosya seç.** İsteğe bağlıdır (aşağıya bakın).

### 3. Öğrenciler giriş yapar

Öğrenciler modeme bağlanıp programı açar ve giriş yapar. Her öğrencinin ekranı solda, adı
sağdaki listede görünür. Bu sırada hiçbir program kapatılmaz; öğrenciler Packet Tracer'ı
açıp hesaplarına giriş yapsın.

### 4. Sınavı başlatın

**Sınavı başlat**'a basın. Açılan pencerede:

- **Başlangıç:** hemen ya da seçtiğiniz saatte.
- **Sınav süresi:** isteğe bağlıdır. Yazarsanız öğrenciler geri sayım görür. **Süre dolunca
  sınav kendiliğinden bitmez;** panelde “süre aşıldı” yazar ve sınavı siz bitirirsiniz.
- **Ekranları kaydet:** işaretliyse ekranlar *Kayıtlar* klasörüne kaydedilir. İşaretli
  değilse ekranları yalnızca canlı izlersiniz. Öğrenci bu seçimi göremez.

Sınav başlayınca öğrencilerde kısa bir geri sayımdan sonra izin verilmeyen programlar
kapanır ve öğrencinin panelinde **Sınav dosyasını indir** düğmesi çıkar. Hiçbir şey
kendiliğinden açılmaz ya da inmez; dosyayı öğrenci istediği yere kendisi indirir.

### 5. Sınavı izleyin

- **Renkler:** yeşil = bağlı, sarı = uyarı var, kırmızı = bağlantı yok, gri = teslim etti.
- **Uyarılar** öğrencinin satırında, adının yanında görünür. Satırdaki oka basınca o
  öğrencinin uyarıları açılır; **Görüldü** uyarıyı kapatır.
- **Uyarılar** sekmesi bütün uyarıları tek liste hâlinde gösterir.
- Bir ekrana tıklayınca büyür.
- **Ekran boyutu:** üst satırdaki **− / +** ile ekranları büyütüp küçültün; **Sığdır**
  hepsini ekrana sığdırır.
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
  öğrencinin numarasıyla başlamalıdır (ör. `2021001_ali.pka`); öğrenci “Teslim etti” olur.
- Sistem dosyanın içini değerlendiremez; çözümü görmek için dosyayı Packet Tracer'da açın.

### 7. Sınavı bitirin

**Sınavı bitir**'e basınca bir pencere açılır:

- **Ek süre ver:** dakikayı yazıp düğmeye basın; öğrencilerin geri sayımı uzar.
- **Sınavı bitir:** sınav biter.

Sınav bitince teslim etmemiş öğrencilerin programı kapanmaz. Dosyalarını yine teslim
edebilirler; bu teslim **geç teslim** olarak işaretlenir ve size uyarı düşer.

### 8. Sistemi kapatın

Herkes teslim ettikten sonra **panel penceresini kapatın; sistem kendiliğinden kapanır.**

- Bağlı öğrenci varken sistem kapanmadan önce 2 dakika bekler. Pencereyi yanlışlıkla
  kapattıysanız bu sürede `start-teacher.bat` dosyasını yeniden çalıştırın: panel geri açılır,
  sınav kaldığı yerden sürer.
- **Teslim etmemiş öğrenci varken sistemi kapatırsanız o öğrencilerin dosyası alınmaz.**
  Kapatmadan önce listede herkesin “Teslim etti” olduğuna bakın.
- Aynı gün ikinci bir sınav yapacaksanız sistemi kapatmadan **Yeni sınav**'a basın.

## Sınavdan sonra

Her şey seçtiğiniz sınav klasöründedir (**Sınav klasörünü aç** düğmesi klasörü açar):

| Klasör / dosya | İçinde ne var |
|---|---|
| **Teslimler** | Teslim edilen dosyalar: `numara_AdSoyad.pka`. `index.csv` dosyası kimin ne zaman teslim ettiğini ve geç teslimleri listeler. |
| **Kayıtlar** | Her öğrencinin ekran kaydı, numarasıyla adlandırılmış klasörlerde. Video oynatıcıyla (ör. VLC) açılır. |
| **Uyarılar** | Uyarı alan her öğrenci için bir dosya; Excel'de açılır. |
| `olay-kaydi.csv` | Sınav boyunca olan her şeyin saatli dökümü; Excel'de açılır. |

Ekran kayıtları yer kaplar (öğrenci başına saatte yaklaşık 225 MB) ve kendiliğinden
silinmez; saklama süresi dolunca *Kayıtlar* klasörünü siz silin.

## Öğrenci listesi (isteğe bağlı)

Sütunları **numara, ad, soyad** olan bir Excel dosyası. Liste yüklüyse:

- Listede olmayan bir numarayla ya da farklı bir adla giriş yapılırsa uyarı çıkar (giriş yine
  kabul edilir).
- Henüz giriş yapmamış öğrencileri “Giriş yapmayanlar” bölümünde görürsünüz.

## Uyarılar ne demek?

| Uyarı | Anlamı |
|---|---|
| … kapatıldı | Öğrenci izin verilmeyen bir program açtı; program kapatıldı. |
| Packet Tracer dışında bir pencere önde | Öğrenci 5 saniyeden uzun süre başka bir pencereye baktı. |
| Başka bir masaüstüne geçti | Öğrenci Windows'un ikinci masaüstüne geçti. |
| Monitör sayısı: 2 | İkinci bir ekran takılı. |
| Bağlantı koptu | Wi-Fi koptu ya da bilgisayar uyudu. Bağlantı gelince kendiliğinden düzelir. |
| Ajan öğrenci tarafından kapatıldı | Öğrenci programı kapattı. |
| Bu bilgisayardan daha önce … giriş yapmıştı | Aynı bilgisayardan başka bir numarayla giriş yapıldı. |
| Aynı numarayla ikinci oturum açma girişimi | Bu numara başka bir bilgisayarda zaten açık. |
| Ad uyuşmuyor / Numara listede yok | Girişteki bilgiler öğrenci listesiyle uyuşmuyor. |
| Teslim edilen dosya sınav dosyasının kendisi | Öğrenci hiçbir şey kaydetmeden teslim etti. |
| … ile birebir aynı dosyayı teslim etti | İki öğrencinin dosyası tıpatıp aynı. |
| Geç teslim | Dosya sınav bittikten sonra teslim edildi. |
| Teslim dosyası klasörde bulunamıyor | Teslim edilen dosya *Teslimler* klasöründen silinmiş ya da taşınmış. |
| Sınav süresi doldu | Verdiğiniz süre bitti; sınav sürüyor, bitirmek size kalmış. |

## Sorun olursa

**Öğrenci programı sınavı bulamıyor.**
Öğrenci doğru Wi-Fi ağına bağlı mı? Başlatma penceresi açık mı? Olmuyorsa öğrenci,
başlatma penceresinde ve **Diğer** menüsünde yazan adresi programa elle yazabilir.

**Öğrenci giriş yaptı ama ekranı gelmiyor.**
Öğrencinin antivirüsü programı engellemiş olabilir (çözümü öğrenci kılavuzunda). Panelin
üstünde kırmızı bir uyarı varsa `start-teacher.bat` penceresini kapatıp yeniden çalıştırın.

**Görüntüler takılıyor.**
Bilgisayarınızı modeme kabloyla bağlayın. **Diğer → Görünmeyen ekranları duraklat**'ı açın.

**Panel penceresini yanlışlıkla kapattım.**
`start-teacher.bat` dosyasını yeniden çalıştırın; panel geri açılır.

**Bilgisayar ya da sistem sınav sırasında kapandı.**
`start-teacher.bat` dosyasını yeniden çalıştırın. Sınav kaldığı yerden sürer, öğrenciler
kendiliğinden yeniden bağlanır.

**“Klasör seç”e bastım, pencere gelmedi.**
Pencere başka bir pencerenin arkasında kalmış olabilir; görev çubuğuna bakın.

**Sınavda başka bir programa da izin vermem gerekiyor.**
İzin verilen programlar `server\config.yaml` dosyasında yazar; her ayarın açıklaması dosyanın
içindedir.
