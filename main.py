#!/usr/bin/env python3
"""Marmara Üniversitesi duyuru takip ve Telegram bildirim botu.

Akış:
1) `sites.json` (site kataloğu) + `secilecek_siteler.txt` (kullanıcının hangi
   siteleri izlemek istediği) birleştirilip izlenecek site listesi çıkarılır.
2) Bu sitelerin duyuru sayfaları eşzamanlı çekilir.
3) Her sitenin listesi `duyurular.json`'daki kaydıyla karşılaştırılıp gerçekten
   yeni olan duyurular bulunur (kurallar için bkz. `process_site`).
4) Yeni duyurular Telegram Bot API ile gönderilir.
5) `duyurular.json` güncellenir. Artık izlenmeyen sitelerin kaydı silinir;
   böylece bir site sonradan yeniden seçilirse aradaki duyurular toplu gelmez.

Yeni bir Marmara sitesi eklemek için `sites.json`'a bir kayıt eklemek yeterli
(host + notices_url) — main.py'de kod değişikliği gerekmez. Hangi sitelerin
izleneceğini seçmek için `secilecek_siteler.txt`'yi düzenle (bkz. o dosyanın
içindeki açıklama): "HEPSI" satırı tüm siteleri açar, ya da tek tek sitelerin
başındaki # işaretini kaldırıp sadece istediklerini seçebilirsin.

Git commit/push işlemi bilerek burada değil, GitHub Actions workflow'unda
yapılıyor (bkz. .github/workflows/main.yml) — script'in tek sorumluluğu
veri çekmek ve bildirim göndermek.
"""

import concurrent.futures
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SITES_FILE = os.path.join(PROJECT_DIR, "sites.json")
SELECTION_FILE = os.path.join(PROJECT_DIR, "secilecek_siteler.txt")
DATA_FILE = os.path.join(PROJECT_DIR, "duyurular.json")

# secilecek_siteler.txt'de yorumsuz (başında # olmayan) bir satırda bu
# kelimelerden biri geçerse, dosyadaki tek tek site seçimi yok sayılır ve
# sites.json'daki TÜM siteler izlenir.
ALL_SITES_KEYWORDS = {"HEPSI", "HEPSİ", "ALL", "TÜMÜ", "TUMU"}

# Site isimlerinde/hostlarında da geçebilecek genel bir domain deseni; seçim
# dosyasındaki her aktif satırdan host'u bu şekilde çıkarıyoruz.
HOST_PATTERN = r"([a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.marmara\.edu\.tr)"

# GitHub Actions cron'u zaten 09:00 TR civarında tetikliyor; script ek olarak
# 0-180 saniye (0-3 dk) rastgele bekleyerek her gün farklı bir saatte
# kontrol yapılmasını sağlıyor (bkz. proje talimatı madde 2.2).
MAX_RANDOM_DELAY_SECONDS = 180

# Tek seferde en fazla bu kadar site eşzamanlı çekilir — hem hızlı olsun hem de
# üniversite sunucularına makul bir yükten fazlası binmesin.
MAX_WORKERS = 8
REQUEST_TIMEOUT = (10, 20)  # (connect, read) saniye

# Marmara teması /allnotices'te tarihe göre sıralı en fazla bu kadar duyuru
# gösteriyor; daha eskiler gizli kalıyor.
PAGE_SIZE = 15

# Listeden düşen duyurular bu kadar gün daha hatırlanır, listeye geri dönerse
# tekrar bildirilmesin diye. Daha uzun süre sonra alttan geri dönen eski bir
# duyuruyu tarih kuralı yakalar (bkz. process_site).
FORGET_AFTER_DAYS = 180

# Bir site art arda bu kadar kontrolde okunamaz ya da şüpheli bir liste
# döndürürse kullanıcı Telegram'dan uyarılır.
PROBLEM_THRESHOLD = 3

# Telegram gönderimleri arasında API'ye art arda çok hızlı istek atmamak için
# kibarca bekleme.
TELEGRAM_SEND_DELAY_SECONDS = 0.5

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Yerel testte (`SKIP_RANDOM_DELAY=1 python main.py`) rastgele beklemeyi atlamak için.
SKIP_RANDOM_DELAY = os.environ.get("SKIP_RANDOM_DELAY") == "1"

# Türkiye saat dilimi (UTC+3, DST yok) — GitHub Actions runner'ı UTC çalıştığı
# için "bugün"ün tarihini kullanıcının göreceği gibi göstermek için kullanılır.
TURKEY_UTC_OFFSET = timedelta(hours=3)
TURKISH_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

HEADERS = {
    # Bazı okul sunucuları tarayıcı User-Agent'ı olmayan istekleri engelliyor.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("marmara-duyuru-bot")


def random_delay():
    """09:00-09:03 arası rastgele bir saatte kontrol edebilmek için bekler."""
    if SKIP_RANDOM_DELAY:
        logger.info("SKIP_RANDOM_DELAY=1: rastgele bekleme atlanıyor.")
        return
    delay = random.randint(0, MAX_RANDOM_DELAY_SECONDS)
    logger.info("Rastgele bekleme: %s saniye.", delay)
    time.sleep(delay)


def load_site_catalog():
    """sites.json'daki TÜM siteleri (isim, host, url) yükler."""
    try:
        with open(SITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("sites.json okunamadı: %s", exc)
        return []


def load_selection():
    """secilecek_siteler.txt'yi okuyup hangi hostların izleneceğini belirler.

    Dönüş: ("all", None) -> tüm siteler; ("subset", {host, ...}) -> sadece
    bu hostlar. Dosya yoksa veya boşsa, güvenli varsayılan olarak "all" döner
    (sites.json'daki her şey izlenir).
    """
    if not os.path.exists(SELECTION_FILE):
        logger.info("secilecek_siteler.txt bulunamadı, varsayılan olarak tüm siteler izlenecek.")
        return "all", None

    try:
        with open(SELECTION_FILE, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError as exc:
        logger.error("secilecek_siteler.txt okunamadı, tüm siteler izlenecek: %s", exc)
        return "all", None

    active_lines = [
        line.strip() for line in raw_lines
        if line.strip() and not line.strip().startswith("#")
    ]

    for line in active_lines:
        if line.upper() in ALL_SITES_KEYWORDS:
            return "all", None

    selected_hosts = set()
    for line in active_lines:
        match = re.search(HOST_PATTERN, line, re.IGNORECASE)
        if match:
            selected_hosts.add(match.group(1).lower())
        else:
            logger.warning(
                "secilecek_siteler.txt: '%s' satırından bir marmara.edu.tr "
                "host'u çıkarılamadı, atlanıyor.", line,
            )

    if not selected_hosts:
        logger.warning(
            "secilecek_siteler.txt'de aktif hiçbir site/HEPSI bulunamadı; "
            "bu çalıştırmada hiçbir site izlenmeyecek."
        )

    return "subset", selected_hosts


def load_sites():
    """sites.json (katalog) + secilecek_siteler.txt (seçim) birleştirilerek izlenecek siteler döner."""
    catalog = load_site_catalog()
    if not catalog:
        return []

    mode, selected_hosts = load_selection()

    if mode == "all":
        logger.info("Seçim: HEPSI. %d site izlenecek.", len(catalog))
        return catalog

    sites = [s for s in catalog if s["host"] in selected_hosts]
    logger.info(
        "Seçim: özel liste. %d/%d site izlenecek.", len(sites), len(catalog)
    )

    matched_hosts = {s["host"] for s in sites}
    unknown = selected_hosts - matched_hosts
    if unknown:
        logger.warning(
            "secilecek_siteler.txt'deki şu hostlar sites.json'da bulunamadı: %s",
            ", ".join(sorted(unknown)),
        )

    return sites


def fetch_site_notices(site):
    """Bir sitenin duyuru sayfasını kazır ve [{baslik, tarih, link}] listesi döner.

    Site erişilemezse veya beklenen HTML yapısı yoksa None döner (bu site bu
    çalıştırmada atlanır, diğer siteleri etkilemez).
    """
    host = site["host"]
    url = site["notices_url"]

    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("[%s] duyuru sayfası çekilemedi: %s", host, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    container = soup.select_one("div.blog-pull-right")
    if container is None:
        logger.warning("[%s] beklenen HTML yapısı bulunamadı (site teması değişmiş olabilir).", host)
        return None

    base = f"https://{host}"
    notices = []
    for row in container.select("div.row.mb-15"):
        title_tag = row.select_one("h4")
        date_tag = row.select_one("h6")
        link_tag = row.select_one("a[href]")

        if title_tag is None or link_tag is None:
            continue

        notices.append({
            "baslik": title_tag.get_text(strip=True),
            "tarih": date_tag.get_text(strip=True) if date_tag else "",
            "link": urljoin(base, link_tag["href"]),
        })

    return notices


def fetch_all_sites(sites):
    """Tüm aktif siteleri eşzamanlı çeker. {host: notices} döner (başarısız olanlar dahil değil)."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_site = {executor.submit(fetch_site_notices, s): s for s in sites}
        for future in concurrent.futures.as_completed(future_to_site):
            site = future_to_site[future]
            try:
                notices = future.result()
            except Exception as exc:  # Bir sitedeki beklenmeyen hata tüm taramayı düşürmesin.
                logger.error("[%s] beklenmeyen hata: %s", site["host"], exc)
                continue
            if notices is not None:
                results[site["host"]] = notices
                logger.info("[%s] %d duyuru bulundu.", site["host"], len(notices))
    return results


def load_known():
    """duyurular.json'daki site kayıtlarını yükler.

    Dönüş: {host: {"sayfa": [...], "gecmis": {...}, ...}}. "sayfa" sitenin son
    sorunsuz okunan listesi, "gecmis" o listeden düşmüş duyuruların kimliği ve
    en son görüldükleri gün. Eski biçimdeki kayıtlar ({host: [duyuru, ...]})
    otomatik dönüştürülür.
    """
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("duyurular.json okunamadı, boş veriyle devam ediliyor: %s", exc)
        return {}

    known = {}
    for host, record in data.items():
        if isinstance(record, list):  # eski biçim: sadece son liste
            record = {"sayfa": record, "gecmis": {}}
        if isinstance(record, dict) and isinstance(record.get("sayfa"), list):
            record.setdefault("gecmis", {})
            known[host] = record
        else:
            logger.warning("[%s] duyurular.json'daki kaydı tanınmadı, site yeni sayılacak.", host)
    return known


def save_known(data):
    """Kayıtları önce geçici dosyaya yazıp sonra yerine koyar; yazma yarıda
    kesilirse duyurular.json bozulmaz. Sıralama sabit olduğu için git
    diff'lerinde sadece gerçekten değişen satırlar görünür."""
    ordered = {}
    for host in sorted(data):
        record = data[host]
        ordered[host] = {
            "sayfa": record["sayfa"],
            # Güne göre sıralı: yeni düşenler sona eklenir.
            "gecmis": dict(sorted(record["gecmis"].items(), key=lambda kv: (kv[1], kv[0]))),
            **{k: v for k, v in record.items() if k not in ("sayfa", "gecmis")},
        }

    tmp_file = DATA_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(ordered, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_file, DATA_FILE)
        logger.info("duyurular.json güncellendi (%d site).", len(data))
    except OSError as exc:
        logger.error("duyurular.json yazılamadı: %s", exc)


def parse_notice_date(text):
    """Listede yazan "gg.aa.yyyy" tarihini döner; okunamazsa None."""
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def notice_key(notice):
    """Bir duyurunun kimliği; aynı kimlikli duyuru ikinci kez bildirilmez.

    Sitenin kendi duyuru linkleri (/notice/...) her duyuru için tekildir (aynı
    başlık yeniden girilince bile sonuna -1, -2 eklenir). Bazı duyurular ise
    başka bir siteye ya da dosyaya link veriyor ve aynı link farklı
    duyurularda tekrar kullanılabiliyor; bunlar başlıkla birlikte ayırt edilir.
    """
    if "/notice/" in notice["link"]:
        return notice["link"]
    return f"{notice['link']} | {notice['baslik']}"


def process_site(state, page, today):
    """Bir sitenin bu kontroldeki listesini işler.

    Marmara temasında liste tarihe göre sıralı ve en fazla PAGE_SIZE duyuru
    gösteriyor. Süresi dolan duyurular listeden kalkınca gizli kalmış daha eski
    duyurular alttan geri giriyor; personel bazen yeni duyuruya eski bir tarih
    yazıyor, başlık düzeltilince de link değişiyor. Bu yüzden sadece son 1-2
    duyuruyu hatırlamak listenin ortasına giren duyuruları kaçırır. Kurallar:

    1) Daha önce görülmüş duyuru bir daha bildirilmez. Listedekilerin yanında
       listeden düşenler de FORGET_AFTER_DAYS gün hatırlanır ("gecmis").
    2) Önceki liste doluyken onun en eski tarihinden de eski tarihli bir
       duyuru yeni değil, alttan geri gelmiş eski bir duyurudur: dolu listeye
       o kadar eski bir duyuru ancak üstündekilerden biri kalkınca girebilir.
    3) Liste boşsa ya da bilinen hiçbir duyuruyu içermiyorsa (ve hepsi önceki
       listenin en yeni tarihinden yeni değilse) site geçici bir sorun
       yaşıyor sayılır: hiçbir şey bildirilmez, kayıt korunur. Sorun
       PROBLEM_THRESHOLD kontrol sürerse kullanıcı uyarılır. Liste o zaman da
       öncekiyle örtüşmüyorsa (ör. linklerin yapısı değişmiş) yeni liste
       referans alınır ve sadece önceki listenin en yeni tarihinden eski
       olmayan duyurular bildirilir.

    state: duyurular.json'daki site kaydı, site ilk kez görülüyorsa None.
    page: sitede şu an listelenen duyurular, site okunamadıysa None.
    Dönüş: (yeni kayıt, bildirilecek duyurular, uyarı metni ya da None)
    """
    if state is None:
        # Yeni kurulum ya da yeni seçilen site: mevcut duyuruları "yeni" sayıp
        # toplu bildirim göndermek yerine sadece referans olarak kaydet.
        return ({"sayfa": page, "gecmis": {}} if page is not None else None), [], None

    prev = state["sayfa"]
    seen = {notice_key(n) for n in prev} | set(state["gecmis"])
    prev_dates = [d for d in (parse_notice_date(n["tarih"]) for n in prev) if d]
    newest = max(prev_dates, default=None)

    problem = None
    if page is None:
        problem = "okunamadı"
    elif not page and prev:
        problem = "boş liste döndürdü"
    elif prev and seen.isdisjoint(notice_key(n) for n in page):
        # İki kontrol arasında bir listeden fazla yeni duyuru girdiyse hepsi
        # öncekilerden yeni tarihli olur; değilse sayfa bozuk ya da değişmiş.
        page_dates = [parse_notice_date(n["tarih"]) for n in page]
        if newest is None or not all(d and d >= newest for d in page_dates):
            problem = "bilinen hiçbir duyuruyu içermeyen bir liste döndürdü"

    warning = None
    if problem:
        streak = state.get("hata", 0) + 1
        if not page or streak < PROBLEM_THRESHOLD:
            if streak == PROBLEM_THRESHOLD:
                warning = f"art arda {streak} kontrolde {problem}"
            return {**state, "hata": streak}, [], warning
        warning = f"art arda {streak} kontrolde {problem}; yeni liste referans alındı"

    floor = min(prev_dates) if len(prev) == PAGE_SIZE and prev_dates else None

    def is_old(d):
        if problem:  # yeni referans: önceki listenin en yeni tarihinden eskiler
            return newest is None or d is None or d < newest
        return floor is not None and d is not None and d < floor

    new_notices, keys = [], set()
    for notice in page:
        key = notice_key(notice)
        if key in seen or key in keys:
            continue
        keys.add(key)
        if not is_old(parse_notice_date(notice["tarih"])):
            new_notices.append(notice)

    page_keys = {notice_key(n) for n in page}
    gecmis = {k: d for k, d in state["gecmis"].items() if k not in page_keys}
    gecmis.update({notice_key(n): today.isoformat() for n in prev if notice_key(n) not in page_keys})
    forget_before = (today - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    new_state = {"sayfa": page, "gecmis": {k: d for k, d in gecmis.items() if d >= forget_before}}
    return new_state, new_notices, warning


def turkey_now():
    return datetime.now(timezone.utc) + TURKEY_UTC_OFFSET


def turkish_today_str():
    """Türkiye saatiyle 'bugün'ü "15 Eylül" formatında döner."""
    tr_now = turkey_now()
    return f"{tr_now.day} {TURKISH_MONTHS[tr_now.month - 1]}"


def send_telegram_text(text):
    """Telegram Bot API üzerinden serbest metin mesaj gönderir.

    WhatsApp Cloud API'nin aksine Telegram'da onaylı şablon veya 24 saatlik
    "müşteri penceresi" kısıtlaması yok — kullanıcı bota bir kere /start
    dediğinde bot o chat_id'ye süresiz, serbest metin mesaj gönderebilir.
    """
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        logger.error(
            "Telegram ortam değişkenleri eksik (TELEGRAM_BOT_TOKEN / "
            "TELEGRAM_CHAT_ID). Mesaj gönderilemiyor."
        )
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info("Telegram mesajı gönderildi.")
        return True
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            detail = f" | Yanıt: {exc.response.text}"
        logger.error("Telegram mesajı gönderilemedi: %s%s", exc, detail)
        return False


def send_telegram_notification(site_name, title, link):
    """Yeni bir duyuru için bildirim gönderir."""
    text = (
        f"📢 Yeni duyuru: {site_name}\n\n"
        f"{title}\n\n"
        f"{link}"
    )
    return send_telegram_text(text)


def send_telegram_heartbeat():
    """Bugün yeni duyuru olmadığını, ama botun çalıştığını bildirir.

    Kullanıcı bunu her gün görüp botun gerçekten çalıştığından emin olabilsin
    diye — aksi halde tek bildirim kanalı yeni duyuru olduğunda gelen mesajlar
    olurdu ve günler boyu sessizlik "bot çalışıyor mu, bozuldu mu?" sorusunu
    doğururdu.
    """
    text = f"✅ {turkish_today_str()} - Duyuru yok"
    return send_telegram_text(text)


def send_telegram_warnings(warnings):
    """Art arda sorun çıkaran siteleri kullanıcıya bildirir. warnings: [(site, metin)]"""
    text = "\n\n".join(
        f"⚠️ {site['name']}: {warning}\n{site['notices_url']}" for site, warning in warnings
    )
    return send_telegram_text(text)


def main():
    logger.info("Marmara Üniversitesi duyuru botu başlatıldı.")
    random_delay()

    sites = load_sites()
    if not sites:
        logger.error("sites.json'da aktif site bulunamadı, işlem sonlandırılıyor.")
        sys.exit(1)

    current_by_host = fetch_all_sites(sites)

    if not current_by_host:
        logger.warning("Hiçbir siteden duyuru çekilemedi, işlem sonlandırılıyor.")
        sys.exit(0)

    today = turkey_now().date()
    known_by_host = load_known()
    updated_known = {}
    new_items = []  # [(site, notice)]
    warnings = []  # [(site, metin)]

    for site in sites:
        host = site["host"]
        notices = current_by_host.get(host)
        if host not in known_by_host and notices is not None:
            logger.info(
                "[%s] ilk kez görülüyor, bildirim gönderilmeden referans "
                "olarak kaydedilecek (%d duyuru).",
                host, len(notices),
            )

        state, site_new, warning = process_site(known_by_host.get(host), notices, today)
        if state is None:
            continue
        updated_known[host] = state
        if site_new:
            logger.info("[%s] %d yeni duyuru bulundu.", host, len(site_new))
            new_items.extend((site, n) for n in site_new)
        if warning:
            logger.warning("[%s] %s", host, warning)
            warnings.append((site, warning))

    dropped = len(set(known_by_host) - set(updated_known))
    if dropped:
        logger.info("Artık izlenmeyen %d sitenin kaydı siliniyor.", dropped)

    if not new_items:
        logger.info("Toplamda yeni duyuru yok.")
        send_telegram_heartbeat()
    else:
        logger.info("Toplam %d yeni duyuru Telegram ile gönderilecek.", len(new_items))
        sent = 0
        for site, notice in new_items:
            try:
                if send_telegram_notification(site["name"], notice["baslik"], notice["link"]):
                    sent += 1
            except Exception as exc:  # Beklenmeyen bir hata tüm çalıştırmayı düşürmesin.
                logger.error("[%s] duyuru gönderilirken beklenmeyen hata: %s", site["host"], exc)
            time.sleep(TELEGRAM_SEND_DELAY_SECONDS)

        if sent < len(new_items):
            logger.warning("%d/%d yeni duyuru Telegram ile gönderilebildi.", sent, len(new_items))

    if warnings:
        send_telegram_warnings(warnings)

    save_known(updated_known)


if __name__ == "__main__":
    main()
