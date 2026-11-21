# Sınav Programı — Öğrenci Kılavuzu

Packet Tracer sınavına **Sınav Ajanı** programıyla girilir. Program sınav boyunca ekranınızı
aktarır, sınav dosyasını indirmenizi ve sonunda dosyanızı teslim etmenizi sağlar.

## Sınavdan önce

1. **Windows 10 ya da 11** kullanan bir bilgisayar gerekir.
2. **Packet Tracer kurulu olsun ve hesabınızla giriş yapmış olun.** Giriş ekranında
   **“Keep me logged in”** seçeneğini açın. Sınav salonunda internet yoktur; ilk girişinizi
   orada yapamazsınız.
3. **Sınav Ajanı'nı kurun.** Size gönderilen **`SinavAjan-Kurulum.exe`** dosyasına çift
   tıklayın, açılan pencerede **Kur**'a, sonra **Bitti**'ye basın. Masaüstüne **Sınav Ajanı**
   simgesi gelir.
   - “Windows kişisel bilgisayarınızı korudu” çıkarsa **Ek bilgi → Yine de çalıştır** deyin.
   - “Bu uygulamanın cihazınızda değişiklik yapmasına izin veriyor musunuz?” sorusuna
     **Evet** deyin.

## Sınav günü

1. **Sınav için verilen Wi-Fi ağına bağlanın.** (“İnternet yok” yazması normaldir.)
2. Masaüstündeki **Sınav Ajanı** simgesine çift tıklayın ve izin sorusuna **Evet** deyin.
3. Ekranda **sınıfınızın adı** görünür. Doğruysa **Doğru**'ya basın. Yanlışsa başka bir Wi-Fi
   ağına bağlısınız: **Yanlış**'a basın, doğru ağa bağlanıp **Tekrar ara** deyin.
4. **Öğrenci numaranızı (10 haneli), adınızı ve soyadınızı** yazıp **Giriş yap**'a basın.
5. **“Sınavın başlamasını bekleyin”** ekranı gelir. Beklerken:
   - **Packet Tracer'ı açın, giriş yapın ve açık bırakın.**
   - Başka programlardaki işlerinizi kaydedip kapatın.
6. Sınav başlayınca kısa bir geri sayım görünür, sonra program küçük bir panele dönüşür.
7. Paneldeki **Sınav dosyasını indir**'e basın, dosyayı kaydedeceğiniz yeri seçin (ör.
   Masaüstü) ve **Kaydet** deyin.
8. Packet Tracer'da **File → Open** ile indirdiğiniz dosyayı açın.

## Sınav sırasında

- **Yalnızca Packet Tracer kullanılabilir.** Tarayıcı, mesajlaşma, not ve benzeri programlar
  açıldığı anda kapatılır.
- Başka bir pencereye uzun süre bakmayın, ikinci ekran takmayın, başka bir masaüstüne
  geçmeyin; bunlar kaydedilir.
- **Sık sık Ctrl+S ile kaydedin.**
- Panel Packet Tracer'ın arkasında kalabilir. Gerektiğinde görev çubuğundaki **Sınav**
  simgesine tıklayın.
- Süre verildiyse panelde geri sayım görünür. **Son 10 dakikada** bir uyarı çıkar ve süre
  kırmızıya döner.
- Wi-Fi koparsa çalışmaya devam edin; program kendiliğinden yeniden bağlanır.
- Program kapanırsa ya da bilgisayar yeniden başlarsa programı yeniden açıp **aynı
  numarayla** giriş yapın. Dosyanız yerinde durur.
- **Programı kapatmayın.** Kapatırsanız dosyanız teslim edilmez.

## Teslim

1. Packet Tracer'da **Ctrl+S** ile kaydedin.
2. Paneldeki **Teslim et**'e basın.
3. Açılan pencerede **teslim edeceğiniz dosyayı seçip Aç**'a basın.
4. Program dosyanızı kontrol eder:
   - **“Dosyada değişiklik yok”** — indirdiğiniz dosyayı hiç kaydetmemişsiniz ya da yanlış
     dosyayı seçtiniz. **Vazgeç** deyin, Ctrl+S ile kaydedip yeniden deneyin.
   - **“Yanlış dosya olabilir”** — eski bir dosya seçtiniz. **Vazgeç** deyip doğru dosyayı
     seçin.
   - Sorun yoksa dosyanın adı ve son kayıt saati gösterilir. Doğruysa **Evet, teslim et**
     deyin.
5. **“Teslim alındı”** yazısını görünce işiniz bitmiştir; program kapanır.

**Otomatik teslim yoktur.** Dosyanızı mutlaka kendiniz teslim edin.

## Sınav bittiyse ve teslim etmediyseniz

Program kapanmaz; panelde **“Sınav bitti”** yazar. **Teslim et** ile dosyanızı yine teslim
edebilirsiniz, ancak tesliminiz **geç teslim** olarak kaydedilir.

**“Sınav kapatıldı”** penceresi çıkarsa sınav tamamen kapatılmıştır; o ana kadar teslim
etmediyseniz dosyanız teslim edilmemiş olur.

## Sorun olursa

**“Sınav sunucusu bulunamadı.”**
Doğru Wi-Fi ağına bağlı olduğunuza bakıp **Tekrar dene**'ye basın. Olmazsa size söylenen
adresi alttaki kutuya yazıp **Bağlan**'a basın.

**“Ekran aktarımı başlatılamadı” uyarısı çıktı ya da “Ekran aktarımı başlatılıyor…” yazısı
gitmiyor.**
Antivirüsünüz programı engellemiş olabilir. Antivirüsü kapatmayın; `C:\Program Files\Sinav
Ajani` ve `%LOCALAPPDATA%\SinavAjan` klasörlerini antivirüsün “dışlamalar / istisnalar”
listesine ekleyip programı yeniden açın. Windows Güvenliği için: **Başlat → Windows Güvenliği
→ Virüs ve tehdit koruması → Ayarları yönet → Dışlamalar → Dışlama ekle.** Program
silindiyse yeniden kurun.

**Programı kurmayı unuttum.**
Sınavı yapan kişiye söyleyin; kurulum dosyasını ondan alıp kurun. Program sınav sırasında
sınıf ağından indirilemez.

**Packet Tracer giriş istiyor.**
Sınav başladıktan sonra tarayıcı açılamaz. Bu yüzden girişi sınav başlamadan yapın ve
Packet Tracer'ı kapatmayın.

**İndirdiğim dosyayı bulamıyorum.**
Panelde dosyanın adı yazar. Bulamazsanız **Sınav dosyasını yeniden indir**'e basın; yeni
inen dosya boştur, önceki çalışmanızı içermez.

**“Öğrenci numarası 10 haneli olmalı.”**
Numaranızı eksik ya da fazla yazdınız. Yalnızca rakamlarla, 10 hane olarak yazın.

**“Bu numarayla başka bir bilgisayarda açık bir oturum var.”**
Numaranızı yanlış yazmış olabilirsiniz.

## Bu program bilgisayarımda ne yapar?

Yalnızca giriş yaptığınız andan teslim edene ya da programı kapatana kadar:

- Ekranınız izlenir ve kaydedilebilir.
- Açık olan pencerenin adı, bilgisayarınızın adı ve ağ adresi kaydedilir.
- Sınav başladıktan sonra izin verilmeyen programlar kapatılır.
- Teslim ederken **sizin seçtiğiniz** dosya gönderilir; başka hiçbir dosyanız okunmaz.
- Ekran aktarımı için bir yardımcı dosya geçici olarak açılır; program kapanırken silinir.

Kurulum yalnızca programı bilgisayarınıza kopyalar ve masaüstüne simge koyar. Program
Windows ile birlikte açılmaz, arka planda çalışmaz, kamera ve mikrofonu kullanmaz; yalnızca
siz açtığınızda çalışır. Kapandıktan sonra hiçbir şey çalışmaya devam etmez. İşiniz bitince
**Ayarlar → Uygulamalar → Sınav Ajanı → Kaldır** ile kaldırabilirsiniz.
