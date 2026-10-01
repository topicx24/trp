#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CAN TV - update_named_channels.py
OPTIMIZE SÜRÜM

Amaç:
- Kanal listesini categories.json'dan alır.
- sources.txt içindeki M3U kaynaklarını indirir.
- M3U kayıtlarını kanal adına göre önceden indeksler.
- Her kanal için bütün 13.000+ kaydı tekrar taramaz.
- Aynı URL'yi yalnızca bir kez kontrol eder.
- Çalışan yayınları data/kanal_kaynaklari.m3u içine yazar.
- data/kanal_raporu.json oluşturur.

Avantaj:
Eski sistem:
    189 kanal x 13.604 kayıt
    ≈ 2,5 milyon karşılaştırma

Yeni sistem:
    M3U bir kez indekslenir.
    Kanal aranırken doğrudan ilgili adaylara gidilir.
"""

import re
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    import requests
except ImportError:
    requests = None


# =========================================================
# DOSYALAR
# =========================================================

ROOT = Path(__file__).resolve().parent

CATEGORIES_FILE = ROOT / "categories.json"
SOURCES_FILE = ROOT / "sources.txt"

DATA = ROOT / "data"

OUT_FILE = DATA / "kanal_kaynaklari.m3u"
REPORT_FILE = DATA / "kanal_raporu.json"


# =========================================================
# AYARLAR
# =========================================================

# Önceki 12 saniyeye göre çok daha hızlı.
TIMEOUT = 15

# Bir kanal için en fazla kaç aday URL kontrol edilsin?
MAX_CANDIDATES_PER_CHANNEL = 20

UA = "Mozilla/5.0 (compatible; CAN-TV-Channel-Matcher/3.0)"


# =========================================================
# NORMALIZE
# =========================================================

def norm(text):

    s = str(text or "").upper().strip()

    tr_map = str.maketrans({
        "İ": "I",
        "Ş": "S",
        "Ğ": "G",
        "Ü": "U",
        "Ö": "O",
        "Ç": "C",
        "Â": "A",
        "Î": "I",
        "Û": "U",
    })

    s = s.translate(tr_map)

    # Yayın kalitesi ifadelerini kaldır.
    s = re.sub(
        r"\b(FHD|UHD|HD|SD|4K|HEVC|H265|H264|FULL HD)\b",
        " ",
        s
    )

    # Noktalama işaretlerini boşluk yap.
    s = re.sub(
        r"[^A-Z0-9]+",
        " ",
        s
    )

    return re.sub(
        r"\s+",
        " ",
        s
    ).strip()


# =========================================================
# ALIASLAR
# =========================================================

ALIASES = {

    "TV8": {
        "TV8",
        "TV 8",
    },

    "TV8 5": {
        "TV8 5",
        "TV 8 5",
        "TV85",
        "TV 85",
        "TV8.5",
        "TV 8.5",
    },

    "HABER TURK": {
        "HABERTURK",
        "HABER TURK",
    },

    "NATIONAL GEOGRAPHIC": {
        "NATIONAL GEOGRAPHIC",
        "NAT GEO",
    },

    "NATIONAL GEOGRAPHIC WILD": {
        "NATIONAL GEOGRAPHIC WILD",
        "NAT GEO WILD",
        "NAT WILD",
        "NATIONAL WILD",
    },

    "DISCOVERY ID": {
        "DISCOVERY ID",
        "ID DISCOVERY",
        "INVESTIGATION DISCOVERY",
    },

    "NR1": {
        "NR1",
        "NR1 TV",
        "NUMBER1",
    },

    "NR1 TURK": {
        "NR1 TURK",
        "NUMBER1 TURK",
    },

    "DREAM TURK": {
        "DREAM TURK",
    },

    "TRT MUZIK": {
        "TRT MUZIK",
    },

    "BENGUTURK": {
        "BENGUTURK",
        "BENGU TURK",
    },

    "BLOOMBERG HT": {
        "BLOOMBERG HT",
        "BLOOMBERGHT",
    },

    "EKOTURK": {
        "EKOTURK",
    },

    "LIFETIME": {
        "LIFETIME",
        "LIFE TIME",
    },

    "KRAL FM": {
        "KRAL FM",
        "KIRAL FM",
    },

    "KRAL POP": {
        "KRAL POP",
        "KIRAL POP",
    },
}


# =========================================================
# KANAL ANAHTARI
# =========================================================

def channel_key(name):

    n = norm(name)

    if not n:
        return ""

    # -----------------------------------------------------
    # TV8
    # -----------------------------------------------------

    if n in {
        "TV8",
        "TV 8",
    }:
        return "TV8"

    # -----------------------------------------------------
    # TV8.5
    # -----------------------------------------------------

    if n in {
        "TV8 5",
        "TV 8 5",
        "TV85",
        "TV 85",
    }:
        return "TV8 5"

    # -----------------------------------------------------
    # Özel kanallar
    # -----------------------------------------------------

    if n in {
        "BENGUTURK",
        "BENGU TURK",
    }:
        return "BENGUTURK"

    if n in {
        "HABERTURK",
        "HABER TURK",
    }:
        return "HABER TURK"

    if n in {
        "NAT GEO",
        "NATIONAL GEOGRAPHIC",
    }:
        return "NATIONAL GEOGRAPHIC"

    if n in {
        "NAT GEO WILD",
        "NAT WILD",
        "NATIONAL GEOGRAPHIC WILD",
        "NATIONAL WILD",
    }:
        return "NATIONAL GEOGRAPHIC WILD"

    if n in {
        "ID DISCOVERY",
        "DISCOVERY ID",
        "INVESTIGATION DISCOVERY",
    }:
        return "DISCOVERY ID"

    if n in {
        "BLOOMBERG HT",
        "BLOOMBERGHT",
    }:
        return "BLOOMBERG HT"

    if n in {
        "LIFETIME",
        "LIFE TIME",
    }:
        return "LIFETIME"

    if n in {
        "KRAL FM",
        "KIRAL FM",
    }:
        return "KRAL FM"

    if n in {
        "KRAL POP",
        "KIRAL POP",
    }:
        return "KRAL POP"

    return n


# =========================================================
# KANALLARI YÜKLE
# =========================================================

def load_channels():

    if not CATEGORIES_FILE.exists():

        raise FileNotFoundError(
            f"categories.json bulunamadı: {CATEGORIES_FILE}"
        )

    data = json.loads(
        CATEGORIES_FILE.read_text(
            encoding="utf-8"
        )
    )

    channels = []

    for category, names in data.items():

        if not isinstance(names, list):
            continue

        for name in names:

            if not isinstance(name, str):
                continue

            name = name.strip()

            if not name:
                continue

            channels.append({
                "name": name,
                "category": category,
                "key": channel_key(name),
            })

    return channels


# =========================================================
# SOURCES OKU
# =========================================================

def read_sources():

    if not SOURCES_FILE.exists():

        return []

    result = []

    for line in SOURCES_FILE.read_text(
        encoding="utf-8",
        errors="ignore"
    ).splitlines():

        line = line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if not (
            line.startswith("http://")
            or line.startswith("https://")
        ):
            continue

        result.append(line)

    return result


# =========================================================
# M3U İNDİR
# =========================================================

def fetch(url):

    if requests:

        response = requests.get(
            url,
            timeout=TIMEOUT,
            headers={
                "User-Agent": UA
            }
        )

        response.raise_for_status()

        return response.text

    request = Request(
        url,
        headers={
            "User-Agent": UA
        }
    )

    with urlopen(
        request,
        timeout=TIMEOUT
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="ignore"
        )


# =========================================================
# M3U PARSE
# =========================================================

def parse_m3u(text, source):

    lines = text.splitlines()

    result = []

    i = 0

    while i < len(lines):

        line = lines[i].strip()

        if line.startswith("#EXTINF"):

            ext = line

            j = i + 1

            while j < len(lines):

                candidate = lines[j].strip()

                if candidate:
                    break

                j += 1

            if j < len(lines):

                url = lines[j].strip()

                if (
                    url
                    and not url.startswith("#")
                    and (
                        url.startswith("http://")
                        or url.startswith("https://")
                    )
                ):

                    # Önce tvg-name
                    match = re.search(
                        r'tvg-name\s*=\s*"([^"]+)"',
                        ext,
                        flags=re.IGNORECASE
                    )

                    if match:

                        display = match.group(1).strip()

                    elif "," in ext:

                        display = ext.split(
                            ",",
                            1
                        )[1].strip()

                    else:

                        display = "KANAL"

                    result.append({
                        "name": display,
                        "key": channel_key(display),
                        "url": url,
                        "ext": ext,
                        "source": source
                    })

            i = j + 1

        else:

            i += 1

    return result


# =========================================================
# KALİTE
# =========================================================

def quality_score(text):

    u = str(text or "").upper()

    if re.search(r"\b4K\b", u):
        return 4

    if "UHD" in u:
        return 4

    if "FHD" in u:
        return 3

    if "FULL HD" in u:
        return 3

    if re.search(r"\bHD\b", u):
        return 2

    if re.search(r"\bSD\b", u):
        return 1

    return 0


# =========================================================
# KANAL EŞLEŞTİRME
# =========================================================

def channel_match(target, candidate):

    a = norm(target)
    b = norm(candidate)

    if not a or not b:
        return False

    if a == b:
        return True

    if a.replace(" ", "") == b.replace(" ", ""):
        return True

    # Alias kontrolü
    for canonical, aliases in ALIASES.items():

        canonical_norm = norm(canonical)

        if a == canonical_norm:

            if b == canonical_norm:
                return True

            for alias in aliases:

                if b == norm(alias):
                    return True

        if b == canonical_norm:

            if a == canonical_norm:
                return True

            for alias in aliases:

                if a == norm(alias):
                    return True

    return False


# =========================================================
# KANAL İNDEKSİ OLUŞTUR
# =========================================================

def build_index(candidates):

    index = {}

    for candidate in candidates:

        key = candidate["key"]

        if not key:
            continue

        if key not in index:

            index[key] = []

        index[key].append(candidate)

    return index


# =========================================================
# URL KONTROL
# =========================================================

def check_stream(url):

    try:

        parsed = urlparse(url)

        if parsed.scheme not in (
            "http",
            "https"
        ):

            return False, "unsupported-scheme"

        if requests:

            response = requests.get(
                url,
                timeout=TIMEOUT,
                headers={
                    "User-Agent": UA
                },
                stream=True,
                allow_redirects=True
            )

            status = response.status_code

            response.close()

            return (
                200 <= status < 400,
                f"http-{status}"
            )

        request = Request(
            url,
            headers={
                "User-Agent": UA
            }
        )

        with urlopen(
            request,
            timeout=TIMEOUT
        ) as response:

            status = getattr(
                response,
                "status",
                200
            )

            return (
                200 <= status < 400,
                f"http-{status}"
            )

    except Exception as e:

        return False, type(e).__name__


# =========================================================
# ADAYLARI SIRALA
# =========================================================

def sort_candidates(candidates):

    return sorted(
        candidates,
        key=lambda item: (
            -quality_score(item["name"]),
            len(item["name"]),
        )
    )


# =========================================================
# ANA PROGRAM
# =========================================================

def main():

    print()
    print("=" * 70)
    print("CAN TV - OPTIMIZED NAMED CHANNEL UPDATE")
    print("=" * 70)
    print()

    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    # -----------------------------------------------------
    # KANALLAR
    # -----------------------------------------------------

    try:

        channels = load_channels()

    except Exception as e:

        print(
            f"[HATA] Kanal listesi okunamadı: {e}"
        )

        return 1

    print(
        f"[KANALLAR] {len(channels)} sabit kanal bulundu."
    )

    # -----------------------------------------------------
    # SOURCES
    # -----------------------------------------------------

    sources = read_sources()

    print(
        f"[SOURCES] {len(sources)} kaynak bulundu."
    )

    if not sources:

        print(
            "[HATA] sources.txt boş."
        )

        return 1

    print()

    # -----------------------------------------------------
    # TÜM KAYNAKLARI OKU
    # -----------------------------------------------------

    candidates = []

    source_errors = []

    for number, source in enumerate(
        sources,
        start=1
    ):

        try:

            text = fetch(source)

            records = parse_m3u(
                text,
                source
            )

            candidates.extend(records)

            print(
                f"[OK] Kaynak {number}: "
                f"{len(records)} kayıt"
            )

        except Exception as e:

            source_errors.append({
                "source": source,
                "error": str(e)
            })

            print(
                f"[HATA] Kaynak {number}"
            )

            print(
                f"       {e}"
            )

    print()

    print(
        f"[TOPLAM] {len(candidates)} aday kayıt bulundu."
    )

    # -----------------------------------------------------
    # İNDEKS
    # -----------------------------------------------------

    print(
        "[INDEX] Kanal indeksi oluşturuluyor..."
    )

    index = build_index(
        candidates
    )

    print(
        f"[INDEX] {len(index)} farklı kanal anahtarı."
    )

    print()

    # -----------------------------------------------------
    # URL CACHE
    # -----------------------------------------------------

    tested_urls = {}

    # -----------------------------------------------------
    # ÇIKTI
    # -----------------------------------------------------

    output = [
        "#EXTM3U"
    ]

    report = {

        "total_channels": len(channels),

        "matched": 0,

        "not_found": 0,

        "source_count": len(sources),

        "candidate_count": len(candidates),

        "indexed_channels": len(index),

        "timeout": TIMEOUT,

        "max_candidates_per_channel":
            MAX_CANDIDATES_PER_CHANNEL,

        "source_errors": source_errors,

        "channels": []
    }

    # -----------------------------------------------------
    # KANALLARI ARA
    # -----------------------------------------------------

    for number, channel in enumerate(
        channels,
        start=1
    ):

        name = channel["name"]

        category = channel["category"]

        key = channel["key"]

        print(
            f"[{number}/{len(channels)}] "
            f"[ARAMA] {name}"
        )

        # -------------------------------------------------
        # DOĞRUDAN İNDEKSTEN AL
        # -------------------------------------------------

        matches = index.get(
            key,
            []
        )

        # -------------------------------------------------
        # Alias nedeniyle indeks bulunamadıysa
        # sınırlı fallback araması
        # -------------------------------------------------

        if not matches:

            fallback = []

            for candidate in candidates:

                if channel_match(
                    name,
                    candidate["name"]
                ):

                    fallback.append(candidate)

            matches = fallback

        # -------------------------------------------------
        # KALİTE
        # -------------------------------------------------

        matches = sort_candidates(
            matches
        )

        # Aynı URL'leri kaldır
        unique_matches = []

        seen_urls = set()

        for candidate in matches:

            url = candidate["url"]

            if url in seen_urls:
                continue

            seen_urls.add(url)

            unique_matches.append(
                candidate
            )

        # -------------------------------------------------
        # SADECE İLK N ADAY
        # -------------------------------------------------

        unique_matches = unique_matches[
            :MAX_CANDIDATES_PER_CHANNEL
        ]

        chosen = None

        attempts = []

        # -------------------------------------------------
        # URL KONTROL
        # -------------------------------------------------

        for candidate in unique_matches:

            url = candidate["url"]

            # Daha önce kontrol edilmişse cache kullan
            if url in tested_urls:

                ok, reason = tested_urls[url]

            else:

                ok, reason = check_stream(
                    url
                )

                tested_urls[url] = (
                    ok,
                    reason
                )

            attempts.append({

                "url": url,

                "source": candidate["source"],

                "ok": ok,

                "reason": reason
            })

            if ok:

                chosen = candidate

                break

        # -------------------------------------------------
        # ÇALIŞAN
        # -------------------------------------------------

        if chosen:

            output.append(
                '#EXTINF:-1 '
                f'tvg-name="{name}" '
                f'group-title="{category}",'
                f'{name}'
            )

            output.append(
                chosen["url"]
            )

            report["matched"] += 1

            report["channels"].append({

                "name": name,

                "category": category,

                "status": "working",

                "url": chosen["url"],

                "source": chosen["source"],

                "attempts": attempts
            })

            print(
                f"    [ÇALIŞIYOR]"
            )

        # -------------------------------------------------
        # BULUNAMADI
        # -------------------------------------------------

        else:

            report["not_found"] += 1

            report["channels"].append({

                "name": name,

                "category": category,

                "status": "not_found",

                "attempts": attempts
            })

            print(
                f"    [BULUNAMADI]"
            )

    # -----------------------------------------------------
    # DOSYALARI YAZ
    # -----------------------------------------------------

    OUT_FILE.write_text(
        "\n".join(output) + "\n",
        encoding="utf-8"
    )

    REPORT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    # -----------------------------------------------------
    # SONUÇ
    # -----------------------------------------------------

    print()
    print("=" * 70)
    print("SONUÇ")
    print("=" * 70)

    print(
        f"Toplam kanal       : "
        f"{report['total_channels']}"
    )

    print(
        f"Eşleşen/çalışan    : "
        f"{report['matched']}"
    )

    print(
        f"Bulunamayan        : "
        f"{report['not_found']}"
    )

    print(
        f"Kaynak sayısı      : "
        f"{report['source_count']}"
    )

    print(
        f"Aday kayıt         : "
        f"{report['candidate_count']}"
    )

    print(
        f"İndeks kanal       : "
        f"{report['indexed_channels']}"
    )

    print(
        f"URL timeout        : "
        f"{TIMEOUT} saniye"
    )

    print(
        f"Max aday/kanal     : "
        f"{MAX_CANDIDATES_PER_CHANNEL}"
    )

    print()

    print(
        f"Çıktı              : "
        f"{OUT_FILE}"
    )

    print(
        f"Rapor              : "
        f"{REPORT_FILE}"
    )

    print("=" * 70)

    return 0


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
    )

