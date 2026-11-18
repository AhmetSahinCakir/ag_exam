# Sınav İzleme Sistemi

Cisco Packet Tracer ile yapılan sınavlar için, internet gerektirmeyen bir izleme sistemi.

- Öğrencilerin ekranını canlı gösterir; isterseniz kaydeder.
- Sınav sırasında Packet Tracer dışındaki programları kapatır ve bildirir.
- Sınav dosyasını öğrencilere verir, teslim edilen dosyaları toplar.

## Kılavuzlar

| Kılavuz | Kimin için |
|---|---|
| [Kullanım kılavuzu](docs/KURULUM.md) | Sınavı yapan kişi: kurulum, sınav günü, sorunlar |
| [Öğrenci kılavuzu](docs/OGRENCI.md) | Öğrenciler: programı çalıştırma ve teslim |
| [Sınavdan önce deneme](docs/PROVA.md) | Sınavdan önce bir kez yapılacak deneme listesi |

## Kısaca

1. Python'u kurun, bu sayfadan sistemi indirin.
2. `scripts\start-teacher.bat` dosyasını çalıştırın; panel açılır.
3. Öğrenci programını (**Actions → build-agent → SinavAjan-win-x64**) indirip öğrencilere
   dağıtın.
4. Sınav günü: klasörü ve sınav dosyasını seçin, öğrenciler giriş yapsın, **Sınavı başlat**'a
   basın.

Ayrıntılar: [kullanım kılavuzu](docs/KURULUM.md).
