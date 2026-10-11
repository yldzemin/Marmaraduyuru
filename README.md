# Marmara Üniversitesi Duyuru Takip Botu

Seçtiğiniz Marmara Üniversitesi sitelerini her gün otomatik kontrol edip yeni
duyuru çıktığında size **Telegram** üzerinden mesaj gönderen bir bot. Kendi
bilgisayarınızda çalışmaz — tamamen **GitHub Actions** üzerinde, ücretsiz ve
sunucusuz çalışır. Kurulum 15-20 dakika sürer, tamamen bu sayfadaki adımları
takip ederek yapılır, kod bilgisi gerekmez.

## Nasıl çalışır?

Bot her gün otomatik uyanır (Türkiye saatiyle 09:17 için zamanlanır; GitHub
yoğun zamanlarda bunu geciktirebilir), izlemesini istediğiniz siteleri kontrol
eder, daha önce görmediği duyuru varsa size Telegram'dan mesaj atar. Yeni
duyuru yoksa "✅ Duyuru yok" mesajı gelir, böylece botun çalıştığını bilirsiniz.
İlk kurulumda ya da yeni bir site eklediğinizde, o sitenin o anki duyuruları
"yeni" sayılıp toplu bildirim göndermez — sessizce referans olarak
kaydedilir; sadece bundan sonra çıkan gerçek yeni duyurular bildirilir.

Sitelerdeki listeler en fazla 15 duyuru gösterir. Süresi dolan bir duyuru
listeden kalkınca, aylar önceki bir duyuru alttan geri girebilir. Bot bunu
tarihinden anlar ve tekrar bildirmez. Listenin ortasına eski tarihle girilen
ya da başlığı düzeltilen duyuruları ise kaçırmaz. Bir site art arda 3 kontrolde
okunamazsa ya da boş/tanınmayan bir liste döndürürse Telegram'dan ⚠️ uyarısı gelir.

---

## Adım 1 — Bu repoyu kendinize kopyalayın (fork)

1. Bu reponun GitHub sayfasında sağ üstteki **"Fork"** butonuna basın.
2. Açılan ekranda **"Create fork"**'a basın. Artık `github.com/<kullanıcı-adınız>/Marmaraduyuru` adında kendi kopyanız var.
3. Bundan sonraki tüm adımlarda **kendi fork'unuzun** sayfasını kullanacaksınız (orijinal repoyu değil).

## Adım 2 — Telegram bot'unuzu oluşturun

1. Telegram'ı açın, arama kutusuna **@BotFather** yazıp resmi hesabı bulun, sohbeti açın.
2. `/newbot` yazıp gönderin.
3. BotFather bota bir **isim** soracak (örn. `Marmara Duyuru Botu`) — istediğinizi yazın.
4. Sonra bir **kullanıcı adı** soracak, `bot` ile bitmeli (örn. `marmara_duyuru_bot`). Alınmışsa farklı bir tane deneyin.
5. BotFather size şöyle bir mesajla bir **token** verecek:
   ```
   Use this token to access the HTTP API:
   123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   Bu satırdaki uzun kodu bir yere kopyalayın — bu sizin `TELEGRAM_BOT_TOKEN`'ınız. **Kimseyle paylaşmayın**, botunuzu ele geçirebilir.
6. Şimdi Telegram'da botunuzu bulun (BotFather'ın mesajındaki `t.me/...` linkine tıklayın) ve sohbeti açıp **`/start`** yazın. (Bot size ilk mesajı siz atmadan mesaj gönderemez, tek şart bu — bir kere yeterli.)

### `chat_id`'nizi öğrenin

1. Tarayıcınızda şu adresi açın, `<TOKEN>` yerine adım 5'te aldığınız token'ı yapıştırın:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
2. Sayfada şöyle bir JSON göreceksiniz, içinde `"chat":{"id":123456789, ...}` kısmındaki sayı sizin **`chat_id`**'niz:
   ```json
   {"ok":true,"result":[{"message":{"chat":{"id":123456789, ...}, "text":"/start", ...}}]}
   ```
3. `"result":[]` (boş) görüyorsanız, adım 6'daki `/start`'ı henüz göndermemişsiniz demektir — önce onu yapıp sayfayı yenileyin.

## Adım 3 — GitHub Secrets'a bilgileri ekleyin

1. Kendi fork'unuzun GitHub sayfasında **Settings** sekmesine girin.
2. Sol menüden **Secrets and variables → Actions**'a tıklayın.
3. Sağ üstteki yeşil **"New repository secret"** butonuna basın.
4. **Name**: `TELEGRAM_BOT_TOKEN`, **Secret**: Adım 2.5'teki token → **"Add secret"**.
5. Tekrar **"New repository secret"** → **Name**: `TELEGRAM_CHAT_ID`, **Secret**: Adım 2'nin sonundaki chat_id sayısı → **"Add secret"**.
6. Artık listede iki secret görmelisiniz: `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID`.

## Adım 4 — Hangi siteleri izleyeceğinizi seçin

Repoda `secilecek_siteler.txt` adında düz metin bir dosya var, GitHub üzerinden
düzenleyebilirsiniz (bilgisayarınıza indirmenize gerek yok):

1. Fork'unuzda `secilecek_siteler.txt` dosyasına tıklayın.
2. Sağ üstteki kalem ✏️ ikonuna (Edit) basın.
3. Dosyanın en üstünde `HEPSI` satırı varsa ve **tüm 97 siteyi** izlemek istiyorsanız dokunmayın.
4. **Sadece belirli siteleri** izlemek istiyorsanız:
   - `HEPSI` satırının başına `#` koyup pasif hale getirin (`# HEPSI`).
   - Aşağıdaki referans listede istediğiniz sitelerin başındaki `#` işaretini silin — sadece # kalkan satırlar aktif olur.
5. Sağ üstte **"Commit changes..."** → **"Commit changes"** ile kaydedin.

> Yeni bir Marmara sitesi eklemek isterseniz (aynı temayı kullanıyorsa) önce
> `sites.json`'a `{"name", "host", "notices_url"}` şeklinde bir kayıt eklemeniz,
> sonra burada aktif etmeniz gerekir.

## Adım 5 — İlk çalıştırmayı yapın

1. Fork'unuzda **Actions** sekmesine girin.
2. GitHub "Actions'ı etkinleştir" diye bir uyarı gösteriyorsa **"I understand my workflows, go ahead and enable them"** butonuna basın (fork'larda Actions varsayılan kapalı gelir).
3. Sol menüden **"Marmara Duyuru Takip Botu"**'na tıklayın.
4. Sağ üstte çıkan **"Run workflow"** açılır menüsüne tıklayın, sonra tekrar yeşil **"Run workflow"** butonuna basın.
5. Birkaç dakika sonra sayfayı yenileyin — çalışma yeşil tik ✅ ile bitmeli. Üstüne tıklayıp **"Run python main.py"** adımının loglarını görebilirsiniz.

Bundan sonra bot her gün otomatik olarak çalışacak (Türkiye saatiyle 09:17 için
zamanlanır; GitHub yoğun zamanlarda başlatmayı geciktirebilir) ve yeni bir
duyuru çıktığında size Telegram'dan mesaj gönderecektir.
Elle test etmek isterseniz her zaman Adım 5.3-5.4'ü tekrarlayabilirsiniz.

---

## Dosyalar

| Dosya | Görev |
|---|---|
| `main.py` | Seçilen siteleri kazır, önceki duyurularla karşılaştırır, Telegram'a gönderir |
| `secilecek_siteler.txt` | **Asıl kontrol dosyası** — hangi sitelerin izleneceği (bkz. Adım 4) |
| `sites.json` | Site kataloğu (isim, host, duyuru URL'si) — sadece yeni bir site eklerken dokunulur |
| `duyurular.json` | Her sitenin son listesi, listeden düşen duyuruların 180 günlük kaydı ve gönderilemeyip bekleyen duyurular (bot otomatik günceller, elle düzenlemeyin) |
| `.github/workflows/main.yml` | Günlük zamanlama ve çalıştırma tanımı |
| `.github/workflows/test.yml` | Kod değiştiğinde testleri çalıştırır |
| `tests/` | Duyuru tespit kurallarının testleri |
| `requirements.txt` | Python bağımlılıkları |

## Sorun giderme

- **Actions sekmesinde çalışma görünmüyor / hiç tetiklenmiyor:** Fork'larda Actions varsayılan kapalı gelir, Adım 5.2'yi kontrol edin.
- **Çalışma kırmızı ✗ ile bitiyor:** Bot, Telegram'a mesaj gönderemediğinde çalışmayı bilerek kırmızı bitirir ki GitHub size e-posta atsın. Loglara tıklayıp `Run python main.py` adımına bakın; genelde `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` eksik veya yanlış girilmiş olur (Adım 3'ü kontrol edin). Gönderilemeyen duyurular kaybolmaz, bir sonraki çalıştırmada tekrar denenir.
- **"✅ Duyuru yok" mesajı da gelmiyor:** Her çalıştırma ya duyuru ya da bu mesajı gönderir. Hiçbiri gelmediyse Actions sekmesinde o günün çalışmasına bakın.
- **⚠️ uyarısı geldi:** Uyarıdaki site art arda 3 kontrolde okunamamış ya da boş/tanınmayan bir liste döndürmüş demektir. Çoğu zaman site geçici olarak bozuktur ve kendiliğinden düzelir; bot o sırada eski kaydı korur, düzelince kaldığı yerden devam eder. Uyarı sürüyorsa linke tıklayıp siteyi kontrol edin.
- **"Duyuru yok (16/18 site kontrol edilebildi)" gibi bir mesaj:** O gün bazı sitelere ulaşılamamış demektir, bir sonraki çalıştırmada tekrar denenir.
- **Botu yeniden adlandırmak/token'ı yenilemek isterseniz:** Telegram'da BotFather'a `/mybots` yazıp botunuzu seçin.

## Başkalarına duyurmak ister misin?

Bu repoyu Marmara'daki arkadaşlarınla/gruplarınla paylaşmak istersen, aşağıdaki
metni olduğu gibi kopyalayıp Telegram/WhatsApp grubuna, sosyal medyaya vs.
atabilirsin:

> 📢 **Marmara Duyuru Botu**
>
> Bölümünün/enstitünün/birimin sitesindeki duyuruları kaçırmaktan bıktın mı? Bu bot senin için:
>
> Marmara Üniversitesi'nin istediğin sitelerini (fakülte, enstitü, daire başkanlığı vs.) her gün otomatik kontrol edip yeni duyuru çıktığında Telegram'a mesaj atıyor. Tamamen ücretsiz, GitHub üzerinde çalışıyor, sunucu falan gerekmiyor.
>
> Kurmak için kod bilgisi gerekmiyor — GitHub'da "Fork" butonuna basıp README'deki adımları takip etmen yeterli (~15 dk):
> 👉 https://github.com/yldzemin/Marmaraduyuru
>
> Herkes kendi bot'unu, kendi Telegram hesabına, kendi izlediği sitelerle kurar.

## ⭐ Beğendin mi?

Bu bot işine yaradıysa:

- Sağ üstteki **⭐ Star** butonuna basarak destekleyebilirsin.
- Bir hata bulursan veya öneri/istek varsa **Issues** sekmesinden açabilirsin.
- Kod katkısı yapmak istersen fork'la, değişikliğini yap, bir **Pull Request** aç.
- Aynı temayı kullanan başka bir Marmara sitesi biliyorsan `sites.json`'a ekleyip PR gönderebilirsin — herkes faydalanır.

## Yerel test (isteğe bağlı)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
DRY_RUN=1 python main.py   # Telegram'a göndermeden ve duyurular.json'a yazmadan, gidecek mesajları gösterir
python -m unittest discover tests   # testleri çalıştırır

export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
SKIP_RANDOM_DELAY=1 python main.py   # gerçek çalıştırma: rastgele beklemeyi atlayarak hemen çalışır
```
