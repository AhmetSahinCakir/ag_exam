# Sınav İzleme Sistemi

Cisco Packet Tracer ile yapılan ağ sınavları için yerel ağda çalışan izleme sistemi.
Öğrenci bilgisayarındaki küçük bir ajan ekranı öğretmen bilgisayarına aktarır, sınav
sırasında Packet Tracer dışındaki programları kapatır ve sınav dosyasını teslim eder.
Öğretmen tüm sınıfı tek bir web panelinden canlı izler. **İnternet gerektirmez.**

| Belge | Kimin için |
|---|---|
| [docs/KURULUM.md](docs/KURULUM.md) | Öğretmen: kurulum, sınav günü, ayarlar, sorun giderme |
| [docs/OGRENCI.md](docs/OGRENCI.md) | Öğrenci: ajanı çalıştırma, teslim, gizlilik |
| [docs/PROVA.md](docs/PROVA.md) | Sınavdan önce yapılacak prova ve test listesi |

## Bileşenler

```
/agent        C# .NET 8 WinForms öğrenci ajanı (Windows 10/11, yönetici olarak çalışır)
/server       Python 3.11+ FastAPI: öğrenci API'si, öğretmen paneli, teslimler, olay kaydı
/mediamtx     mediamtx.yml — ekran yayınlarını alan, kaydeden ve panele veren MediaMTX ayarı
/scripts      start-teacher.bat, fetch-mediamtx.ps1, fetch-ffmpeg.ps1
/docs         KURULUM.md, OGRENCI.md, PROVA.md
/.github/workflows/build-agent.yml   ajanı Windows'ta derleyip ffmpeg ile paketler
```

- Ajan `ffmpeg` ile ekranı H.264 olarak MediaMTX'e (RTSP/TCP) yayınlar; MediaMTX diske
  kaydeder ve panele WebRTC ile verir. Python sunucusu video işlemez.
- Öğretmen sınavdan önce panelde bir **sınav klasörü** seçer; içinde `Kayıtlar` (ekran
  kayıtları) ve `Teslimler` (teslim edilen dosyalar) klasörleri açılır. Öğrenci teslimde
  dosyasını kendisi seçer; sistem dosyanın klasöre ulaştığını denetleyip yayını durdurur.
- Ajan sunucuyu UDP yayınıyla kendisi bulur; sabit IP yoktur. Aynı ajan her sınıfta çalışır.
- Ajan öğrenci bilgisayarında kalıcı iz bırakmaz (servis, başlangıç kaydı, kayıt defteri,
  zamanlanmış görev yok).

## Hızlı başlangıç (öğretmen bilgisayarı)

1. Python 3.11+ kurun, depoyu indirin.
2. `scripts\start-teacher.bat` dosyasını çalıştırın (ilk seferde internet gerekir: Python
   paketlerini ve MediaMTX'i indirir, güvenlik duvarı kurallarını ekler).
3. Açılan panelde sol üstteki **Düzenle** ile sınıf (salon) ve öğretmen adını yazın;
   sınavdan önce **Sınav klasörü → Klasör seç** ile kayıtların ve teslimlerin duracağı
   klasörü seçin.
4. GitHub → Actions → **build-agent** → **SinavAjan-win-x64** artifact'ini indirip
   öğrencilere dağıtın (ya da `dist\SinavAjan.zip` olarak koyun; öğrenciler sınıf ağından
   `http://<öğretmen-ip>:8000/` adresinden indirir).

Ayrıntılar: [docs/KURULUM.md](docs/KURULUM.md).

## Geliştirme

```bash
# Sunucu testleri
pip install -r server/requirements-dev.txt
python -m pytest server/tests

# Sunucuyu elle başlatma (MediaMTX ayrıca çalışmalı: mediamtx mediamtx/mediamtx.yml)
python server/run.py

# Windows olmadan sahte öğrenciler (keşif, giriş, test yayını, teslim)
python server/tests/sim_agent.py --count 5 --stream

# Ajanın platformdan bağımsız çekirdek testleri (.NET 8 SDK)
dotnet run --project agent/tests/CoreSmoke            # yalnızca birim denetimleri
dotnet run --project agent/tests/CoreSmoke -- discover # çalışan sunucuya karşı da dener

# Ajanı derleme (Linux/macOS'ta da derlenir; yalnızca Windows'ta çalışır)
dotnet publish agent/SinavAjan.csproj -c Release -o publish/SinavAjan
```

Ajanın Windows'a özgü bölümleri `agent/Win` ve `agent/UI` altındadır; kurallar ve ağ
iletişimi `agent/Core` altında, Windows API'lerinden bağımsızdır.
