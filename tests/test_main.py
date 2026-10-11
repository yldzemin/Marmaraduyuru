"""main.py'deki duyuru tespit kurallarının testleri.

Çalıştırmak için (repo kökünde): python -m unittest discover tests
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402

START = date(2026, 10, 10)


def setUpModule():
    main.logger.disabled = True


def tearDownModule():
    main.logger.disabled = False


def notice(name, d, link=None):
    return {
        "baslik": name,
        "tarih": d.strftime("%d.%m.%Y"),
        "link": link or f"https://ornek.marmara.edu.tr/notice/{name}",
    }


class FakeSite:
    """Gerçek temanın davranışı: liste tarihe göre sıralı (sabitlenmişler en
    üstte, aynı gün girilenlerden son girilen önce) ve en fazla PAGE_SIZE
    duyuru gösteriyor, gerisi gizli kalıyor."""

    def __init__(self, count, pinned_old=False):
        self.items, self.seq = [], 0
        if pinned_old:
            self.add(date(2025, 1, 1), "sabit", pinned=True)
        for i in range(count):
            self.add(date(2026, 9, 30) - timedelta(days=2 * i), f"eski-{i + 1}")

    def add(self, d, name=None, pinned=False):
        self.seq += 1
        item = {"name": name or f"yeni-{self.seq}", "date": d, "pinned": pinned, "seq": self.seq}
        self.items.append(item)
        return item

    def remove(self, item):
        self.items.remove(item)

    def visible(self):
        ordered = sorted(self.items, key=lambda x: (not x["pinned"], -x["date"].toordinal(), -x["seq"]))
        return ordered[:main.PAGE_SIZE]

    def page(self):
        return [notice(x["name"], x["date"]) for x in self.visible()]


def link(item):
    return notice(item["name"], item["date"])["link"]


class Bot:
    """Bir sitenin her gün bir kez kontrol edilmesini process_site ile canlandırır."""

    def __init__(self, first_page):
        self.day = START
        self.state, new, _ = main.process_site(None, first_page, self.day)
        assert new == [], "ilk görülen sitenin duyuruları bildirilmemeli"
        self.warnings = []

    def check(self, page):
        self.day += timedelta(days=1)
        self.state, new, warning = main.process_site(self.state, page, self.day)
        if warning:
            self.warnings.append(warning)
        return {n["link"] for n in new}


class SiteScenarioTests(unittest.TestCase):
    def test_yeni_duyuru_en_uste_girer(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        new = site.add(START)
        self.assertEqual(bot.check(site.page()), {link(new)})

    def test_en_ustteki_silinir_ve_yeni_girer(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        site.remove(site.visible()[0])
        new = site.add(START)
        self.assertEqual(bot.check(site.page()), {link(new)})

    def test_en_ustteki_iki_duyuru_silinir_ve_yeni_girer(self):
        # "Son 2 duyuruyu hatırla" yaklaşımı burada bütün listeyi yeni sanıyordu.
        site = FakeSite(30)
        bot = Bot(site.page())
        for item in site.visible()[:2]:
            site.remove(item)
        new = site.add(START)
        self.assertEqual(bot.check(site.page()), {link(new)})

    def test_eski_tarihle_girilen_yeni_duyuru_ortada_cikar(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        new = site.add(site.visible()[4]["date"])
        self.assertEqual(bot.check(site.page()), {link(new)})

    def test_basligi_duzeltilen_duyurunun_linki_degisir(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        old = site.visible()[3]
        site.remove(old)
        new = site.add(old["date"])
        self.assertEqual(bot.check(site.page()), {link(new)})

    def test_ortadan_biri_kalkinca_alttan_gelen_eski_bildirilmez(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        site.remove(site.visible()[6])
        self.assertEqual(bot.check(site.page()), set())

    def test_yedi_duyurunun_suresi_dolunca_alttan_gelenler_bildirilmez(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        for item in site.visible()[3:10]:
            site.remove(item)
        self.assertEqual(bot.check(site.page()), set())

    def test_tek_seferde_yirmi_yeni_duyuru(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        for _ in range(20):
            site.add(START)
        page = site.page()
        self.assertEqual(bot.check(page), {n["link"] for n in page})

    def test_en_ustte_sabitlenmis_eski_duyuru(self):
        site = FakeSite(30, pinned_old=True)
        bot = Bot(site.page())
        new = site.add(START)
        self.assertEqual(bot.check(site.page()), {link(new)})

    def test_az_duyurulu_sitede_hepsinden_eski_tarihli_yeni(self):
        # Liste dolu değilse gizli duyuru yoktur, alttan gelen de yenidir.
        site = FakeSite(3)
        bot = Bot(site.page())
        new = site.add(site.visible()[-1]["date"] - timedelta(days=5))
        self.assertEqual(bot.check(site.page()), {link(new)})

    def test_kaldirilip_geri_konan_duyuru_tekrar_bildirilmez(self):
        site = FakeSite(8)
        bot = Bot(site.page())
        item = site.visible()[3]
        site.remove(item)
        self.assertEqual(bot.check(site.page()), set())
        site.items.append(item)
        self.assertEqual(bot.check(site.page()), set())

    def test_yarim_gelen_liste_ertesi_gun_duzelir(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        self.assertEqual(bot.check(site.page()[:8]), set())
        self.assertEqual(bot.check(site.page()), set())

    def test_bos_gelen_liste_ertesi_gun_duzelir(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        new = site.add(START)
        self.assertEqual(bot.check([]), set())
        self.assertEqual(bot.check(site.page()), {link(new)})

    def test_alakasiz_linkler_gelir_ertesi_gun_duzelir(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        garbage = [{"baslik": f"menü {i}", "tarih": "", "link": f"https://ornek/menu/{i}"} for i in range(15)]
        new = site.add(START)
        self.assertEqual(bot.check(garbage), set())
        self.assertEqual(bot.check(site.page()), {link(new)})

    @unittest.expectedFailure
    def test_kor_nokta_bosluga_en_alttakinden_eski_tarihli_yeni_girer(self):
        # Bilinen sınır: bir duyuru kalkarken aynı anda listenin en
        # altındakinden de eski tarihli yeni bir duyuru girerse, alttan geri
        # gelen eski bir duyurudan ayırt edilemez ve bildirilmez.
        site = FakeSite(30)
        bot = Bot(site.page())
        floor = site.visible()[-1]["date"]
        site.remove(site.visible()[6])
        new = site.add(floor - timedelta(days=1))
        self.assertEqual(bot.check(site.page()), {link(new)})

    @unittest.expectedFailure
    def test_kor_nokta_alttan_gelen_eski_en_alttakiyle_ayni_gunlu(self):
        # Bilinen sınır: alttan geri gelen eski duyuru en alttakiyle aynı
        # tarihliyse yeni sanılır (fazladan bir bildirim, kaçırma değil).
        site = FakeSite(30)
        site.items[14]["date"] = site.items[15]["date"]
        bot = Bot(site.page())
        site.remove(site.visible()[6])
        self.assertEqual(bot.check(site.page()), set())


class ProblemTests(unittest.TestCase):
    def test_okunamayan_site_esikte_bir_kez_uyarir_kaydi_korur(self):
        site = FakeSite(30)
        bot = Bot(site.page())
        saved = bot.state
        for _ in range(main.PROBLEM_THRESHOLD + 2):
            self.assertEqual(bot.check(None), set())
        self.assertEqual(len(bot.warnings), 1)
        self.assertIn("okunamadı", bot.warnings[0])
        self.assertEqual(bot.state["sayfa"], saved["sayfa"])

        new = site.add(START)
        self.assertEqual(bot.check(site.page()), {link(new)})
        self.assertNotIn("hata", bot.state)

    def test_kalici_degisen_liste_esikte_referans_alinir(self):
        # Linklerin yapısı değişti: aynı duyurular başka linklerle geliyor.
        site = FakeSite(30)
        bot = Bot(site.page())
        new = site.add(START)

        def moved(n):
            return {**n, "link": n["link"].replace("/notice/", "/duyuru/")}

        page = [moved(n) for n in site.page()]
        for _ in range(main.PROBLEM_THRESHOLD - 1):
            self.assertEqual(bot.check(page), set())
        got = bot.check(page)
        # Önceki listenin en yeni tarihinden eski olmayanlar bildirilir: yeni
        # duyuru ve onunla aynı tarihli eski duyuru (kaçırmaktansa fazla).
        newest_old = moved(notice("eski-1", date(2026, 9, 30)))["link"]
        self.assertEqual(got, {moved(notice(new["name"], new["date"]))["link"], newest_old})
        self.assertEqual(len(bot.warnings), 1)
        self.assertIn("referans", bot.warnings[0])
        self.assertEqual(bot.check(page), set())


class KeyAndMemoryTests(unittest.TestCase):
    def test_ayni_dis_linki_kullanan_yeni_duyuru_bildirilir(self):
        old = notice("Burs başvuruları", date(2025, 10, 1), link="https://burs.example.org/basvuru")
        bot = Bot([old])
        again = notice("2026 burs başvuruları", START, link=old["link"])
        self.assertEqual(len(main.process_site(bot.state, [again, old], START)[1]), 1)

    def test_listede_iki_kez_gecen_duyuru_bir_kez_bildirilir(self):
        bot = Bot([notice("a", date(2026, 9, 1))])
        new = notice("b", START)
        _, got, _ = main.process_site(bot.state, [new, new, notice("a", date(2026, 9, 1))], START)
        self.assertEqual(got, [new])

    def test_listeden_dusen_duyuru_belirli_sure_sonra_unutulur(self):
        bot = Bot([notice("a", date(2026, 9, 2)), notice("b", date(2026, 9, 1))])
        bot.check([notice("a", date(2026, 9, 2))])
        self.assertIn(notice("b", date(2026, 9, 1))["link"], bot.state["gecmis"])

        later = bot.day + timedelta(days=main.FORGET_AFTER_DAYS + 1)
        state, _, _ = main.process_site(bot.state, [notice("a", date(2026, 9, 2))], later)
        self.assertEqual(state["gecmis"], {})


class StorageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "duyurular.json")
        patcher = mock.patch.object(main, "DATA_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_eski_bicim_otomatik_donusturulur(self):
        page = [notice("a", START)]
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"ornek.marmara.edu.tr": page}, f)
        self.assertEqual(main.load_known(), {"ornek.marmara.edu.tr": {"sayfa": page, "gecmis": {}}})

    def test_kaydet_ve_geri_yukle(self):
        data = {
            "b.marmara.edu.tr": {"sayfa": [], "gecmis": {"y": "2026-10-02", "x": "2026-10-01"}},
            "a.marmara.edu.tr": {"sayfa": [notice("a", START)], "gecmis": {}, "hata": 2},
        }
        main.save_known(data)
        self.assertEqual(main.load_known(), data)
        with open(self.path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(list(saved), ["a.marmara.edu.tr", "b.marmara.edu.tr"])
        self.assertEqual(list(saved["b.marmara.edu.tr"]["gecmis"]), ["x", "y"])


class MainTests(unittest.TestCase):
    """main()'i ağ ve Telegram olmadan, sahte site listeleriyle çalıştırır."""

    SITES = [
        {"name": "Site A", "host": "a.marmara.edu.tr", "notices_url": "https://a.marmara.edu.tr/allnotices"},
        {"name": "Site B", "host": "b.marmara.edu.tr", "notices_url": "https://b.marmara.edu.tr/allnotices"},
    ]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "duyurular.json")
        self.sent = []
        for patcher in (
            mock.patch.object(main, "DATA_FILE", self.path),
            mock.patch.object(main, "random_delay", lambda: None),
            mock.patch.object(main, "load_sites", lambda: self.SITES),
            mock.patch.object(main, "send_telegram_text", self.fake_send),
            mock.patch.object(main.time, "sleep", lambda s: None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_send(self, text):
        self.sent.append(text)
        return True

    def run_main(self, pages):
        with mock.patch.object(main, "fetch_all_sites", lambda sites: pages):
            main.main()
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_izlenmeyen_sitenin_kaydi_silinir(self):
        old = {"eski.marmara.edu.tr": [notice("x", START)], "a.marmara.edu.tr": [notice("a", START)]}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(old, f)
        saved = self.run_main({"a.marmara.edu.tr": [notice("a", START)], "b.marmara.edu.tr": [notice("b", START)]})
        self.assertEqual(sorted(saved), ["a.marmara.edu.tr", "b.marmara.edu.tr"])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Duyuru yok", self.sent[0])

    def test_yeni_duyuru_gonderilir(self):
        self.run_main({"a.marmara.edu.tr": [notice("a", START)], "b.marmara.edu.tr": []})
        self.sent.clear()
        new = notice("yeni", START + timedelta(days=1))
        self.run_main({"a.marmara.edu.tr": [new, notice("a", START)], "b.marmara.edu.tr": []})
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Site A", self.sent[0])
        self.assertIn(new["link"], self.sent[0])


if __name__ == "__main__":
    unittest.main()
