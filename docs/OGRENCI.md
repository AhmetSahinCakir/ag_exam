# Sınav Ajanı — Öğrenci Yönergesi

Packet Tracer sınavına **Sınav Ajanı** programıyla girilir. Program sınav boyunca ekranınızı
öğretmen bilgisayarına aktarır, sınav dosyasını indirmenizi sağlar ve sonunda dosyanızı
teslim eder. Sınavdan sonra bilgisayarınızda çalışan hiçbir şey bırakmaz.

## Sınavdan önce (evde, internet varken)

1. **Windows 10 veya 11** kullanan bir bilgisayar gerekir. Hesabınız yönetici hesabı olmalı.
2. **Cisco Packet Tracer** kurulu olsun ve Cisco (NetAcad / Skills for All) hesabınızla
   **giriş yapabildiğinizi deneyin**. Giriş ekranında **“Keep me logged in”** seçeneğini
   açın. Sınav salonunda **internet yoktur**; ilk girişinizi orada yapamazsınız.
3. Program paketini (`SinavAjan.zip`) öğretmeninizin söylediği yerden edinin. Sınav günü sınıf
   ağına bağlandıktan sonra tarayıcıda `http://<öğretmenin söylediği adres>:8000/` adresinden
   de indirebilirsiniz.
4. Zip dosyasına sağ tıklayın → **Tümünü ayıkla**. Açılan `SinavAjan` klasöründeki dosyaların
   **hepsi birlikte durmalı**. Klasörü Masaüstü gibi kolay bulacağınız bir yere koyun. Zip'in
   içinden çalıştırmayın.

## Sınav günü

1. **Öğretmeninizin verdiği Wi-Fi ağına bağlanın.** (Bu ağda internet yoktur; Windows
   “İnternet yok” diyebilir, sorun değil.)
2. `SinavAjan.exe` dosyasına **sağ tıklayın → Yönetici olarak çalıştır**.
   - “Bu uygulamanın cihazınızda değişiklik yapmasına izin vermek istiyor musunuz?” →
     **Evet**.
   - “Windows kişisel bilgisayarınızı korudu” çıkarsa **Ek bilgi → Yine de çalıştır**.
     (“SmartScreen'e şu anda ulaşılamıyor” yazarsa **Çalıştır**.)
3. Program sınavı kendisi bulur ve büyük harflerle gösterir:

   > **Sınıf: B-102**
   > **Öğretmen: …**

   Bu sizin sınıfınız ve öğretmeniniz ise **Doğru**'ya basın. Değilse yanlış Wi-Fi ağına
   bağlısınız: **Yanlış**'a basın, doğru ağa bağlanın, **Tekrar ara** deyin.
4. **Öğrenci numaranızı, adınızı ve soyadınızı** yazıp **Giriş yap**'a basın.
5. **“Sınavın başlamasını bekleyin”** ekranı gelir. Bu andan itibaren ekranınız öğretmene
   aktarılır. Beklerken:
   - **Packet Tracer'ı açın ve giriş yapın** (giriş bir tarayıcı penceresi açabilir —
     sınav başladıktan sonra tarayıcı açılamaz, o yüzden **şimdi** yapın). Packet Tracer'ı
     **açık bırakın**.
   - Başka programlarda kaydetmediğiniz işleriniz varsa **kaydedin ve kapatın**.
   - Program penceresini kapatmayın.
6. Öğretmen sınav dosyasını paylaştığında sınav başlar:
   - “Sınav başlıyor. İzin verilmeyen programlar 10 saniye içinde kapatılacak.” uyarısı ve
     geri sayım görünür.
   - Program ekranın sağında küçük bir panele dönüşür. Paneli başlığından tutup taşıyabilir
     ya da simge durumuna küçültebilirsiniz; görev çubuğundaki simgesine tıklayınca geri gelir.
7. Paneldeki **Sınav dosyasını indir** düğmesine basın, dosyayı **nereye kaydedeceğinizi
   seçin** (ör. Masaüstü) ve **Kaydet** deyin.
8. Packet Tracer'da **File → Open** ile indirdiğiniz dosyayı açın ve sınava başlayın.

## Sınav sırasında

- **Yalnızca Packet Tracer kullanılabilir.** Tarayıcı, mesajlaşma, not, PDF, ofis ve benzeri
  programlar açıldığı anda **kapatılır**; ekranın sağ altında “… sınav sırasında
  kullanılamaz.” yazar ve öğretmene bildirilir.
- Packet Tracer dışında bir pencere (Dosya Gezgini, Ayarlar, Komut İstemi…) **5 saniyeden
  uzun** önde kalırsa öğretmene uyarı gider. Başlat menüsüne yanlışlıkla basmak gibi kısa
  geçişler sorun olmaz.
- **İkinci ekran takmayın;** takılı ekran ve ekran takıp çıkarma öğretmene bildirilir.
- **Başka bir masaüstüne geçmeyin** (Görev Görünümü, Win+Ctrl+→). Geçerseniz “Başka bir
  masaüstündesiniz” bildirimi çıkar ve öğretmene bildirilir.
- **Sık sık Ctrl+S ile kaydedin** ve dosyayı **indirdiğiniz yerde, aynı adla** tutun.
  Teslimde bu dosyayı seçeceksiniz. Öğretmen sınavı siz teslim etmeden bitirirse de
  **bu dosyanın** son kaydettiğiniz hâli otomatik gönderilir; “Farklı Kaydet” ile başka bir
  yere ya da başka bir adla kaydettiğiniz kopya otomatik gönderilmez.
- Süreyi öğretmeniniz tutar; panelde süre görünmez.
- Wi-Fi koparsa panelde “Sunucuya ulaşılamıyor — yeniden deneniyor…” yazar; program
  kendiliğinden yeniden bağlanır, siz çalışmaya devam edin. Uzun sürerse öğretmeninize haber verin.
- Program çökerse veya bilgisayar yeniden başlarsa programı yeniden çalıştırıp **aynı
  numarayla** giriş yapın; indirdiğiniz dosya yerinde durur, yeniden indirmeniz gerekmez.
- Programı kapatmayın. Kapatırsanız öğretmene bildirilir ve dosyanız **teslim edilmez**.

## Teslim

1. Packet Tracer'da **Ctrl+S** ile kaydedin.
2. Paneldeki **Teslim et** düğmesine basın. (Bu düğme, dosyayı indirdikten sonra çıkar.)
3. Açılan pencerede **teslim edeceğiniz dosyayı seçin** ve **Aç**'a basın. Pencere,
   sınav dosyasını indirdiğiniz klasörde açılır ve o dosyanın adı hazır yazılıdır;
   dosyanızı başka bir yere kaydettiyseniz oradan seçin. Yalnızca `.pka` dosyası seçilebilir.
4. Program seçtiğiniz dosyayı göndermeden önce denetler:
   - **“Dosyada değişiklik yok”** — seçtiğiniz dosya indirdiğiniz sınav dosyasının aynısı;
     içine hiçbir şey kaydedilmemiş. Dosyayı indirdikten sonra hiç kaydetmemişsiniz ya da
     yanlış dosyayı seçtiniz. **Vazgeç** deyin, Packet Tracer'da **Ctrl+S** ile kaydedip
     yeniden deneyin.
   - **“Yanlış dosya olabilir”** — seçtiğiniz dosya, sınav dosyasını indirmenizden önce
     kaydedilmiş. Eski bir dosya seçtiniz. **Vazgeç** deyip doğru dosyayı seçin.
   - Sorun yoksa **“Teslim edilsin mi?”** penceresinde dosyanın **adı ve son kayıt saati**
     gösterilir. Bilgiler doğruysa **Evet, teslim et** deyin. Teslimden sonra değişiklik
     yapamazsınız.
5. **“Teslim alındı”** penceresi çıkar; program kapanır ve ekran aktarımı biter. Bu pencere,
   dosyanızın öğretmen bilgisayarına **eksiksiz ulaştığı doğrulandıktan sonra** çıkar.

Teslim etmeden öğretmen sınavı bitirirse, indirdiğiniz dosyanın **son kaydettiğiniz hâli
otomatik olarak** teslim edilir ve “Sınav sona erdi” penceresi çıkar.

## Sınavdan sonra

Program kurulum yapmaz; kaldırılacak bir şey yoktur. İndirdiğiniz sınav dosyası kaydettiğiniz
yerde kalır. İsterseniz `SinavAjan` klasörünü silebilirsiniz.

## Sorun mu var?

**“Bu program yönetici olarak çalıştırılmalıdır.”**
Programı kapatıp sağ tık → **Yönetici olarak çalıştır** ile açın.

**“Sınav sunucusu bulunamadı.”**
Öğretmeninizin verdiği Wi-Fi ağına bağlı olduğunuzdan emin olup **Tekrar dene**'ye basın.
Olmazsa öğretmeninizin söyleyeceği IP adresini alttaki kutuya yazıp **Bağlan**'a basın.

**“Ekran aktarımı başlatılıyor…” yazısı gitmiyor / antivirüs programı engelliyor**
Antivirüsünüz `SinavAjan.exe` veya `ffmpeg.exe` dosyasını engellemiş olabilir.
**Antivirüsü kapatmayın;** yalnızca program klasörünü istisna olarak ekleyin. Windows
Güvenliği (Defender) için:

1. Başlat → **Windows Güvenliği** → **Virüs ve tehdit koruması**.
2. “Virüs ve tehdit koruması ayarları” altında **Ayarları yönet**.
3. En altta **Dışlamalar** → **Dışlama ekle veya kaldır** → **Dışlama ekle** → **Klasör**.
4. `SinavAjan` klasörünü seçin.
5. Antivirüs dosyayı silmişse zip'i yeniden ayıklayın ve programı yeniden başlatın.

Başka bir antivirüs kullanıyorsanız onun “istisna / dışlama / exclusion” ayarına aynı klasörü
ekleyin. Sınavdan sonra istisnayı kaldırabilirsiniz.

**İndirdiğim dosyayı bulamıyorum / yanlış yere kaydettim**
Panelde dosyanızın adı ve klasörü yazar. Bulamıyorsanız **Sınav dosyasını yeniden indir**
ile yeniden indirebilirsiniz; yeni indirilen dosya boş sınav dosyasıdır, önceki
çalışmanızı içermez.

**Packet Tracer giriş istiyor ve tarayıcı açılmıyor**
Sınav başladıktan sonra tarayıcı açılamaz. Öğretmeninize haber verin. (Bu yüzden girişi
bekleme ekranındayken yapın, “Keep me logged in”i açın ve Packet Tracer'ı kapatmayın.)

**“Bu numarayla başka bir bilgisayarda açık bir oturum var.”**
Numaranızı yanlış yazmış olabilirsiniz. Doğruysa öğretmeninize haber verin.

## Bu program bilgisayarımda ne yapıyor?

- **Yaptıkları (yalnızca giriş yaptığınız andan teslime/kapanışa kadar):**
  - Ekranınızın tamamını (birden çok monitör varsa hepsini) öğretmen bilgisayarına aktarır;
    görüntü orada kaydedilir. Kaydın ne kadar saklanacağı giriş ekranında yazar.
  - Öndeki pencerenin program adını ve başlığını, bilgisayar adınızı, ağ (IP/MAC) adresinizi
    ve monitör sayınızı öğretmene bildirir.
  - Sınav **başladıktan sonra** izin verilmeyen programları kapatır.
  - Sınav dosyasını sizin seçtiğiniz yere kaydeder; ayrıca `%LOCALAPPDATA%\SinavAjan\`
    klasörüne küçük bir günlük dosyası yazar.
  - Teslimde **sizin seçtiğiniz** dosyayı öğretmen bilgisayarına gönderir. Başka bir
    masaüstüne geçerseniz bunu öğretmene bildirir.
- **Yapmadıkları:**
  - Kurulum yapmaz, Windows ile birlikte açılmaz, servis ya da zamanlanmış görev oluşturmaz,
    kayıt defterine yazmaz, sistem ayarlarınızı değiştirmez.
  - Kamera ve mikrofonu kullanmaz; dosyalarınızı, tarayıcı geçmişinizi, şifrelerinizi okumaz.
  - Kapandıktan sonra **hiçbir şey çalışmaya devam etmez.**
- Yönetici izni, yönetici olarak açılmış programları da görebilmesi ve kapatabilmesi için
  gereklidir.
- Yönetici izni penceresi (UAC) açıkken Windows ekranı korumaya aldığı için öğretmene kısa
  süre siyah görüntü gidebilir; bu normaldir.
