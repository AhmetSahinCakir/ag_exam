# Sınav Ajanı — Öğrenci Yönergesi

Packet Tracer sınavına **Sınav Ajanı** programıyla girilir. Program sınav boyunca ekranınızı
öğretmen bilgisayarına aktarır, sınav dosyasını Packet Tracer'da açar ve sonunda dosyanızı
teslim eder. Sınavdan sonra bilgisayarınızda çalışan hiçbir şey bırakmaz.

## Sınavdan önce (evde, internet varken)

1. **Windows 10 veya 11** kullanan bir bilgisayar gerekir. Hesabınız yönetici hesabı olmalı.
2. **Cisco Packet Tracer** kurulu olsun ve Cisco (NetAcad / Skills for All) hesabınızla
   **giriş yapabildiğinizi deneyin**. Giriş ekranında **“Keep me logged in”** seçeneğini
   açın. Sınav salonunda **internet yoktur**; ilk girişinizi orada yapamazsınız.
3. Ajan paketini (`SinavAjan.zip`) öğretmeninizin söylediği yerden edinin. Sınav günü sınıf
   ağına bağlandıktan sonra tarayıcıda `http://<öğretmenin söylediği adres>:8000/` adresinden
   de indirebilirsiniz.
4. Zip dosyasına sağ tıklayın → **Tümünü ayıkla**. Açılan `SinavAjan` klasöründeki dosyaların
   **hepsi birlikte durmalı** (`SinavAjan.exe`, `ffmpeg.exe`, `agent.json` ve `.dll` dosyaları).
   Klasörü Masaüstü gibi kolay bulacağınız bir yere koyun. Zip'in içinden çalıştırmayın.

## Sınav günü

1. **Öğretmeninizin verdiği Wi-Fi ağına bağlanın.** (Bu ağda internet yoktur; Windows
   “İnternet yok” diyebilir, sorun değil.)
2. `SinavAjan.exe` dosyasına **sağ tıklayın → Yönetici olarak çalıştır**.
   - “Bu uygulamanın cihazınızda değişiklik yapmasına izin vermek istiyor musunuz?” →
     **Evet**.
   - “Windows kişisel bilgisayarınızı korudu” çıkarsa **Ek bilgi → Yine de çalıştır**.
     (“SmartScreen'e şu anda ulaşılamıyor” yazarsa **Çalıştır**.)
3. Program sınav sunucusunu kendisi bulur ve büyük harflerle gösterir:

   > **Sınıf: B-102**
   > **Öğretmen: …**

   Bu sizin sınıfınız ve öğretmeniniz ise **Doğru**'ya basın. Değilse yanlış Wi-Fi ağına
   bağlısınız: **Yanlış**'a basın, doğru ağa bağlanın, **Tekrar ara** deyin.
4. **Öğrenci numaranızı, adınızı ve soyadınızı** yazıp **Giriş yap**'a basın.
5. **“Sınavın başlamasını bekleyin”** ekranı gelir. Bu andan itibaren ekranınız öğretmene
   aktarılır. Beklerken:
   - **Packet Tracer'ı açın ve giriş yapın** (giriş bir tarayıcı penceresi açabilir —
     sınav başladıktan sonra tarayıcı açılamaz, o yüzden **şimdi** yapın).
   - Başka programlarda kaydetmediğiniz işleriniz varsa **kaydedin ve kapatın**.
   - Ajan penceresini kapatmayın.
6. Öğretmen sınavı başlatınca:
   - “Sınav başlıyor. İzin verilmeyen programlar 10 saniye içinde kapatılacak.” uyarısı ve
     geri sayım görünür.
   - Sınav dosyası (`sinav.pka`) Packet Tracer'da **kendiliğinden açılır**. (Daha önce
     açtığınız boş Packet Tracer penceresini kapatabilirsiniz.)
   - Program, ekranın sağında küçük bir panele dönüşür: kalan süre (öğretmen süre verdiyse),
     bağlantı durumu, **Teslim et** ve **Sınav dosyasını aç** düğmeleri. Paneli başlığından
     tutup taşıyabilir ya da simge durumuna küçültebilirsiniz; görev çubuğundaki simgesine
     tıklayınca geri gelir (kalan süre simgenin üzerine gelince de görünür).

## Sınav sırasında

- **Yalnızca Packet Tracer kullanılabilir.** Tarayıcı, mesajlaşma, not, PDF, ofis ve benzeri
  programlar açıldığı anda **kapatılır**; ekranın sağ altında “… sınav sırasında
  kullanılamaz.” yazar ve öğretmene bildirilir.
- Packet Tracer dışında bir pencere (Dosya Gezgini, Ayarlar, Komut İstemi…) **5 saniyeden
  uzun** önde kalırsa öğretmene uyarı gider. Başlat menüsüne yanlışlıkla basmak gibi kısa
  geçişler sorun olmaz.
- **İkinci ekran takmayın;** takılı ekran ve ekran takıp çıkarma öğretmene bildirilir.
- **Sık sık Ctrl+S ile kaydedin.** Teslim edilen şey, *kaydettiğiniz* dosyadır. Dosyayı
  “Farklı Kaydet” ile başka yere kaydetmeyin; açılan dosyanın üzerine kaydedin.
- Wi-Fi koparsa panelde “Sunucuya ulaşılamıyor — yeniden deneniyor…” yazar; program
  kendiliğinden yeniden bağlanır, siz çalışmaya devam edin. Uzun sürerse öğretmeninize haber verin.
- Packet Tracer'ı yanlışlıkla kapatırsanız paneldeki **Sınav dosyasını aç** düğmesine basın;
  son kaydettiğiniz hâliyle açılır.
- Ajan çökerse veya bilgisayar yeniden başlarsa ajanı yeniden çalıştırıp **aynı numarayla**
  giriş yapın; kaydettiğiniz dosya yerinde durur ve kaldığınız yerden devam edersiniz.
- Ajanı kapatmayın. Kapatırsanız öğretmene bildirilir ve dosyanız **teslim edilmez**.

## Teslim

1. Packet Tracer'da **Ctrl+S** ile kaydedin.
2. Paneldeki **Teslim et** düğmesine basın.
   - “Önce Packet Tracer'da Ctrl+S ile kaydedin.” uyarısı çıkarsa dosyayı sınav başladıktan
     sonra hiç kaydetmemişsiniz demektir; kaydedip yeniden deneyin.
3. “Teslim etmek istediğinize emin misiniz? Teslimden sonra değişiklik yapamazsınız.” →
   **Evet**.
4. **“Teslim alındı”** penceresinde dosyanızın adı ve **SHA-256** özeti görünür (bu, teslim
   ettiğiniz dosyanın parmak izidir; isterseniz not alın). Ajan kapanır, ekran aktarımı biter.

Teslim etmeden süre biterse öğretmen sınavı bitirdiğinde **son kaydettiğiniz dosya otomatik
olarak** teslim edilir ve “Sınav sona erdi” penceresi çıkar.

## Sınavdan sonra

- Son pencerede **Sınav dosyalarını bu bilgisayardan sil ve kapat** derseniz programın
  bilgisayarınıza yazdığı her şey (sınav dosyası ve günlük) silinir. Daha sonra silmek
  isterseniz `%LOCALAPPDATA%\SinavAjan` klasörünü elle silin (adres çubuğuna aynen
  yapıştırabilirsiniz).
- `SinavAjan` klasörünü de silebilirsiniz. Program kurulum yapmaz; kaldırılacak başka bir
  şey yoktur.

## Sorun mu var?

**“Bu program yönetici olarak çalıştırılmalıdır.”**
Programı kapatıp sağ tık → **Yönetici olarak çalıştır** ile açın.

**“Sınav sunucusu bulunamadı.”**
Öğretmeninizin verdiği Wi-Fi ağına bağlı olduğunuzdan emin olup **Tekrar dene**'ye basın.
Olmazsa öğretmeninizin söyleyeceği IP adresini alttaki kutuya yazıp **Bağlan**'a basın.

**“Ekran aktarımı başlatılıyor…” yazısı gitmiyor / antivirüs programı engelliyor**
Antivirüsünüz `SinavAjan.exe` veya `ffmpeg.exe` dosyasını engellemiş olabilir.
**Antivirüsü kapatmayın;** yalnızca ajan klasörünü istisna olarak ekleyin. Windows Güvenliği
(Defender) için:

1. Başlat → **Windows Güvenliği** → **Virüs ve tehdit koruması**.
2. “Virüs ve tehdit koruması ayarları” altında **Ayarları yönet**.
3. En altta **Dışlamalar** → **Dışlama ekle veya kaldır** → **Dışlama ekle** → **Klasör**.
4. `SinavAjan` klasörünü seçin.
5. Antivirüs dosyayı silmişse zip'i yeniden ayıklayın ve ajanı yeniden başlatın.

Başka bir antivirüs kullanıyorsanız onun “istisna / dışlama / exclusion” ayarına aynı klasörü
ekleyin. Sınavdan sonra istisnayı kaldırabilirsiniz.

**Sınav başladı ama Packet Tracer açılmadı**
Packet Tracer'ı kendiniz açın, **File → Open** ile ajanın gösterdiği dosyayı açın:
`%LOCALAPPDATA%\SinavAjan\<numaranız>\sinav.pka` (adres çubuğuna aynen yapıştırabilirsiniz).

**Packet Tracer giriş istiyor ve tarayıcı açılmıyor**
Sınav başladıktan sonra tarayıcı açılamaz. Öğretmeninize haber verin. (Bu yüzden girişi
bekleme ekranındayken yapın ve “Keep me logged in”i açın.)

**“Bu numarayla başka bir bilgisayarda açık bir oturum var.”**
Numaranızı yanlış yazmış olabilirsiniz. Doğruysa öğretmeninize haber verin.

## Bu program bilgisayarımda ne yapıyor?

- **Yaptıkları (yalnızca giriş yaptığınız andan teslime/kapanışa kadar):**
  - Ekranınızın tamamını (birden çok monitör varsa hepsini) öğretmen bilgisayarına aktarır;
    görüntü orada kaydedilir. Kaydın ne kadar saklanacağı giriş ekranında yazar.
  - Öndeki pencerenin program adını ve başlığını, bilgisayar adınızı, ağ (IP/MAC) adresinizi
    ve monitör sayınızı öğretmene bildirir.
  - Sınav **başladıktan sonra** izin verilmeyen programları kapatır.
  - Sınav dosyasını ve küçük bir günlük dosyasını `%LOCALAPPDATA%\SinavAjan\` klasörüne yazar.
- **Yapmadıkları:**
  - Kurulum yapmaz, Windows ile birlikte açılmaz, servis ya da zamanlanmış görev oluşturmaz,
    kayıt defterine yazmaz, sistem ayarlarınızı değiştirmez.
  - Kamera ve mikrofonu kullanmaz; dosyalarınızı, tarayıcı geçmişinizi, şifrelerinizi okumaz.
  - Kapandıktan sonra **hiçbir şey çalışmaya devam etmez.**
- Yönetici izni, yönetici olarak açılmış programları da görebilmesi ve kapatabilmesi için
  gereklidir.
- Yönetici izni penceresi (UAC) açıkken Windows ekranı korumaya aldığı için öğretmene kısa
  süre siyah görüntü gidebilir; bu normaldir.
