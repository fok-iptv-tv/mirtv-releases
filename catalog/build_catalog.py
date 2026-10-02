#!/usr/bin/env python3
"""
Сборщик каталога «Мир ТВ».
Скачивает все источники, объединяет дубликаты (по ссылке и по названию в стране),
определяет жанры и языки, отбрасывает заведомо нерабочие ссылки и пишет catalog.json.gz.
Логика повторяет data/TvRepository.kt приложения.
"""
import gzip, json, os, re, sys, time, urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
GH = "https://raw.githubusercontent.com"
APS = "https://www.apsattv.com"
BCC = GH + "/BuddyChewChew/app-m3u-generator/main/playlists"
MJH = GH + "/matthuisman/i.mjh.nz/master"
PROVIDER_GUIDES = {
    "Pluto TV": MJH + "/PlutoTV/all.xml.gz", "Samsung TV Plus": MJH + "/SamsungTVPlus/all.xml.gz",
    "Plex": MJH + "/Plex/all.xml.gz", "Roku": MJH + "/Roku/all.xml.gz",
}

# ---------- источники (как Sources.kt) ----------
SOURCES = []
def S(provider, url, mode, country=None, group=None, category=None, language=None):
    SOURCES.append((provider, url, mode, country, group, category, language))
S("iptv-org", "https://raw.githubusercontent.com/iptv-org/iptv/gh-pages/index.country.m3u", "C")
S("iptv-org", "https://raw.githubusercontent.com/iptv-org/iptv/gh-pages/index.category.m3u", "G")
S("iptv-org", "https://raw.githubusercontent.com/iptv-org/iptv/gh-pages/index.language.m3u", "L")
S("Free-TV", GH + "/Free-TV/IPTV/master/playlist.m3u8", "C")
S("Pluto TV", BCC + "/plutotv_all.m3u", "C")
S("Samsung TV Plus", BCC + "/samsungtvplus_all.m3u", "C")
S("Plex", BCC + "/plex_all.m3u", "C")
S("Roku", BCC + "/roku_all.m3u", "G", "US")
for c in "ae ar at au be br ca ch cl co de dk es fi fr gb ie in it jp kr lu mx nl no nz pe pt pl sg se us".split():
    S("LG Channels", f"{APS}/{c}lg.m3u", "N", c.upper())
for c in "al at be bg ch cz de dk ee es fi fr gr hr ie it lt nl no pl pt ro rs se sk uk".split():
    S("Rakuten TV", f"{APS}/rakuten_{c}.m3u", "G", "GB" if c == "uk" else c.upper())
for f in "vizio xumo localnow distro tclplus hp freelivesports cineverse galxytv tablo firetv tcl".split():
    S("FAST США", f"{APS}/{f}.m3u", "G", "US")
for f, c in dict(ssungnz="NZ", ssungaus="AU", ssungsg="SG", ssungph="PH", ssungth="TH", ssungbra="BR", ssungmex="MX",
                 ssungnor="NO", ssungfin="FI", ssungden="DK", ssungswe="SE", ssungpor="PT", ssunglux="LU",
                 ssungbelg="BE", ssungire="IE", ssungneth="NL").items():
    S("Samsung (регионы)", f"{APS}/{f}.m3u", "G", c)
for f in "9fast 10fast fetchtv kogantvplus".split(): S("Австралия и Бразилия", f"{APS}/{f}.m3u", "G", "AU")
for f in "moviearkbr redeitv olhosnatv soultv".split(): S("Австралия и Бразилия", f"{APS}/{f}.m3u", "G", "BR")
for f in "vidaa orka metax whaletvplus_all veely rewardedtv".split(): S("Другие FAST", f"{APS}/{f}.m3u", "G")
# Дополнительные официальные трансляции, найденные вручную (файл лежит рядом)
S("Дополнительно", GH + "/fok-iptv-tv/mirtv-releases/main/catalog/extra.m3u", "C")
# YanG-1989: только киберспорт (группа «游戏「赛事」»)
S("Китай · киберспорт", GH + "/YanG-1989/m3u/main/Gather.m3u", "N", "CN", "游戏", "Esports", "Chinese")

# ---------- страны ----------
BY_NAME, NAME_BY_CODE = {}, {}
for line in open(os.path.join(HERE, "countries.csv"), encoding="utf-8"):
    p = line.rstrip("\n").split(";")
    if len(p) >= 4:
        BY_NAME[p[3].lower()] = p[0].upper()
        NAME_BY_CODE[p[0].upper()] = p[3]
EXTRA = {"uk": "GB", "usa": "US", "nz": "NZ", "korea": "KR", "macau": "MO", "trinidad": "TT",
         "日本 / japan": "JP", "vod italy": "IT", "turkey": "TR", "czechia": "CZ", "russian federation": "RU"}

def code(name):
    k = name.strip().lower()
    return BY_NAME.get(k) or EXTRA.get(k) or (k.upper() if len(k) == 2 and k.upper() in NAME_BY_CODE else None)

def canon(name):
    if name.lower() == "international": return "International"
    c = code(name)
    return NAME_BY_CODE.get(c) if c else None

# ---------- жанры (как Categorizer) ----------
RULES = [(re.compile(r, re.I), c) for r, c in [
    (r"\bxxx\b|\badult(?!\s*swim)|erotic|erotik|эрот|18\+|porn", "XXX"),
    (r"news|nachricht|noticia|notícia|nouvelle|notizi|nieuws|nyheter|uutis|wiadomo|xəbər|новост|haber|habere|opinion|local news|more cities", "News"),
    (r"sport|deport|esport|спорт|spor\b|football|soccer|futbol|fútbol|nfl|nba|golf|tennis|racing|fight|ufc|wrestl|poker", "Sports"),
    (r"anime|cartoon|toon|animation|мульт", "Animation"),
    (r"kid|child|kinder|infantil|enfant|niñ|crianç|bambin|детск|çocuk|uşaq|family fun|junior|baby", "Kids"),
    (r"movie|film|cine|kino|фильм|pelic|filme|filmes|western|horror|action|thriller", "Movies"),
    (r"music|musik|músic|musique|musica|музык|müzik|hits|karaoke|concert|\bmtv\b|\bvevo\b", "Music"),
    (r"comed|humor|юмор|komedi|laugh|funny|stand-up", "Comedy"),
    (r"docu|dokument|documental|nature|natur|wildlife|animal|history|histor|science|wissen|discovery|space", "Documentary"),
    (r"crime|mystery|drama|series|serie|séries|tv-show|tv show|sitcom|classic tv|reality|telenovela|novela", "Series"),
    (r"food|cook|cuisine|kitchen|кулин|yemek|kochen|recipe|chef", "Cooking"),
    (r"travel|reise|viaje|voyage|viagem|tour", "Travel"),
    (r"lifestyle|home|garden|design|fashion|beauty|health|fitness|wellness", "Lifestyle"),
    (r"religio|faith|church|gospel|islam|christian|bible|kerk|igreja|iglesia|quran|dini", "Religious"),
    (r"business|financ|bloomberg|market|money|econom|wirtschaft", "Business"),
    (r"weather|wetter|clima|погод", "Weather"),
    (r"\bauto|\bcar\b|cars|motor|garage", "Auto"),
    (r"game|gaming|esports", "Entertainment"),
    (r"entertain|unterhalt|entreten|divertiss|variety|show", "Entertainment"),
    (r"educa|learn|school|bildung", "Education"),
    (r"outdoor|fishing|hunting|adventure", "Outdoor"),
    (r"shop|shopping|teleshop", "Shop"),
]]
KNOWN = set("Esports General News Entertainment Religious Music Movies Series Sports Kids Documentary Education Comedy Culture "
            "Legislative Animation Lifestyle Classic Shop Outdoor Business Family Travel Cooking Public Auto Science "
            "Weather Relax Interactive XXX Undefined".split())

def cat(t):
    if not t or not t.strip(): return None
    t = t.strip()
    if t in KNOWN: return t
    for r, c in RULES:
        if r.search(t): return c
    return None

# ---------- M3U ----------
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
def parse(text):
    out, inf, ua, ref = [], None, None, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line: continue
        if line.startswith("#EXTINF"):
            inf, ua, ref = line, None, None
        elif line.startswith("#EXTVLCOPT"):
            opt = line.split(":", 1)[1] if ":" in line else ""
            if opt.startswith("http-user-agent="): ua = opt.split("=", 1)[1]
            if opt.startswith("http-referrer="): ref = opt.split("=", 1)[1]
        elif not line.startswith("#") and inf:
            attrs = dict(ATTR.findall(inf))
            lq = inf.rfind('"'); c = inf.find(",", max(lq, 0))
            name = inf[c + 1:].strip() if c >= 0 else line
            out.append((attrs, name, line, ua, ref)); inf = None
    return out

SKIP = ("twitch.tv", "youtube.com", "youtu.be", "facebook.com")
def usable(u):
    u = u.strip(); lu = u.lower()
    if not (lu.startswith("http://") or lu.startswith("https://")): return False
    if any(s in lu for s in SKIP): return False
    host = u.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0].split("@")[-1]
    if host.startswith("["): return False
    h = host.split(":")[0]; parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        if a in (10, 127, 0) or a >= 224 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31) \
                or (a == 169 and b == 254) or (a == 100 and 64 <= b <= 127): return False
    return bool(h)

def norm_url(u):
    u = u.strip(); scheme, rest = u.split("://", 1)
    host = rest.split("/", 1)[0].lower()
    if host.startswith("www."): host = host[4:]
    for suf in (":80", ":443"):
        if host.endswith(suf): host = host[: -len(suf)]
    path = rest[len(rest.split("/", 1)[0]):]
    return scheme.lower().replace("https", "http") + "://" + host + path.rstrip("/")

NOISE = re.compile(r"\((?:[^)]*)\)|\[(?:[^]]*)]|\b(?:hd|fhd|uhd|sd|4k|8k|hevc|h265|1080p|720p|576p|480p|360p|orig|backup|live)\b", re.I)
def norm_name(n): return "".join(ch for ch in NOISE.sub(" ", n).lower() if ch.isalnum())

def clean_name(n):
    n = re.sub(r"\s*\[(Not 24/7|Geo-blocked)]", "", n)
    n = re.sub(r"\s*\(\d{3,4}p\)", "", n)
    n = re.sub(r"\s*[ⒼⓈⓉⓎⒶ]\s*$", "", n)
    return n.strip()

import threading
# apsattv ограничивает частоту запросов: к нему — строго по одному и с паузой
_SLOW_HOSTS = {"www.apsattv.com": threading.Lock()}

def fetch(url):
    # свой файл с дополнительными каналами читаем с диска (в репозитории он может ещё не появиться)
    if url.endswith("/catalog/extra.m3u"):
        local = os.path.join(HERE, "extra.m3u")
        if os.path.exists(local):
            return open(local, encoding="utf-8").read()
    host = urllib.parse.urlparse(url).hostname or ""
    lock = _SLOW_HOSTS.get(host)
    if lock is None:
        return _fetch(url, 2)
    with lock:
        t = _fetch(url, 4)
        time.sleep(1.5)
        return t

def _fetch(url, attempts):
    """Скачать плейлист: не больше 90 с на попытку (медленный сайт не должен вешать всю сборку)."""
    for attempt in range(attempts):
        start = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                chunks = []
                while True:
                    if time.time() - start > 90: raise TimeoutError("too slow")
                    b = r.read(65536)
                    if not b: break
                    chunks.append(b)
                t = b"".join(chunks).decode("utf-8", "ignore")
                print(f"ok   {time.time()-start:5.1f}s {url}", flush=True)
                return t if "#EXTINF" in t else None
        except Exception as e:
            print(f"fail {time.time()-start:5.1f}s {url}: {e}", flush=True)
            time.sleep(2 + attempt * 5)
    return None

def main(out_path):
    with ThreadPoolExecutor(8) as ex:
        texts = list(ex.map(lambda s: fetch(s[1]), SOURCES))
    failed = sum(1 for t in texts if t is None)
    raws, rejected, per_provider = [], 0, {}
    for (prov, url, mode, cc, grp, fcat, flang), text in zip(SOURCES, texts):
        if not text: continue
        for attrs, name, u, ua, ref in parse(text):
            if not usable(u): rejected += 1; continue
            if grp and grp not in attrs.get("group-title", ""): continue
            countries, cats, langs = [], [], []
            if cc and NAME_BY_CODE.get(cc): countries.append(NAME_BY_CODE[cc])
            if fcat: cats.append(fcat)
            if flang: langs.append(flang)
            for g in [x.strip() for x in attrs.get("group-title", "").split(";") if x.strip()]:
                if mode == "C":
                    c = canon(g)
                    if c: countries.append(c)
                    else:
                        k = cat(g)
                        if k: cats.append(k)
                elif mode == "G":
                    k = cat(g)
                    if k: cats.append(k)
                elif mode == "L":
                    if g != "Undefined": langs.append(g)
            adult = "XXX" in cats or cat(name) == "XXX"
            raws.append(dict(a=attrs, n=name, u=u.strip(), ua=ua, ref=ref, p=prov, c=countries, g=cats, l=langs, adult=adult))
            per_provider[prov] = per_provider.get(prov, 0) + 1
    # 1) одинаковые ссылки
    by_url = OrderedDict()
    for r in raws:
        k = norm_url(r["u"])
        b = by_url.get(k)
        if b is None:
            b = by_url[k] = dict(urls=[r["u"]], name=r["n"], logo="", ua=None, ref=None, adult=False,
                                 c=[], g=[], l=[], p=[], t=[], e=None)
        for key in ("c", "g", "l"):
            for v in r[key]:
                if v not in b[key]: b[key].append(v)
        if r["p"] not in b["p"]: b["p"].append(r["p"])
        tid = r["a"].get("tvg-id", "").strip()
        if tid and tid not in b["t"]: b["t"].append(tid)
        if not b["e"]: b["e"] = PROVIDER_GUIDES.get(r["p"])
        if not b["logo"]: b["logo"] = r["a"].get("tvg-logo", "")
        b["ua"] = b["ua"] or r["ua"]; b["ref"] = b["ref"] or r["ref"]
        b["adult"] = b["adult"] or r["adult"]
    # общие отметки «18+» (adult.txt: ссылка или название канала в строке) — в 18+ у всех пользователей
    marks_u, marks_n = set(), set()
    try:
        with open(os.path.join(HERE, "adult.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                if line.lower().startswith(("http://", "https://")): marks_u.add(norm_url(line))
                else: marks_n.add(norm_name(line))
    except FileNotFoundError:
        pass
    marked = 0
    if marks_u or marks_n:
        for b in by_url.values():
            if not b["adult"] and (any(norm_url(u) in marks_u for u in b["urls"]) or norm_name(b["name"]) in marks_n):
                b["adult"] = True; marked += 1
    # 2) один канал — разные ссылки
    by_name, backups = OrderedDict(), 0
    for b in by_url.values():
        if not b["c"]: b["c"] = ["International"]
        nn = norm_name(b["name"])
        key = ("url:" + b["urls"][0]) if len(nn) < 2 else f"{nn}|{b['c'][0]}|{b['adult']}"
        ex = by_name.get(key)
        if ex is None: by_name[key] = b; continue
        if len(ex["urls"]) < 6:
            ex["urls"] += b["urls"]; backups += 1
        for k2 in ("c", "g", "l", "p", "t"):
            for v in b[k2]:
                if v not in ex[k2]: ex[k2].append(v)
        ex["logo"] = ex["logo"] or b["logo"]; ex["ua"] = ex["ua"] or b["ua"]; ex["ref"] = ex["ref"] or b["ref"]
        ex["e"] = ex["e"] or b["e"]
    name_cats = {}
    for b in by_name.values():
        c = [x for x in b["g"] if x != "Undefined"]
        if c: name_cats.setdefault(norm_name(b["name"]), c)
    channels = []
    for b in by_name.values():
        cats = [x for x in b["g"] if x != "Undefined"]
        if not cats:
            cats = name_cats.get(norm_name(b["name"]))
            if not cats:
                k = cat(b["name"])
                cats = [k] if k and (k != "XXX" or b["adult"]) else ["Undefined"]
        urls = sorted(dict.fromkeys(b["urls"]), key=lambda x: 0 if x.lower().startswith("https") else 1)
        ch = dict(u=urls[0], n=clean_name(b["name"]), l=b["logo"], c=b["c"], g=["XXX"] if b["adult"] else cats,
                  p=b["p"])
        if b["adult"]: ch["a"] = True
        if len(urls) > 1: ch["alt"] = urls[1:]
        if b["t"]: ch["t"] = b["t"][:6]
        if b["e"]: ch["e"] = b["e"]
        if b["l"]: ch["lang"] = b["l"]
        if b["ua"]: ch["ua"] = b["ua"]
        if b["ref"]: ch["ref"] = b["ref"]
        channels.append(ch)
    stats = dict(entries=len(raws), afterUrlMerge=len(by_url), channels=len(channels), backupStreams=backups,
                 rejected=rejected, adultMarked=marked, perProvider=per_provider, failedSources=failed, sources=len(SOURCES))
    root = dict(v=1, generated=int(time.time()), stats=stats, channels=channels)
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump(root, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    if len(channels) < 1000:
        sys.exit("слишком мало каналов — источники недоступны, каталог не публикуется")

# ---------- канал ФОК (YouTube): список обычных видео без Shorts, по плейлистам/языкам ----------
YT_HDR = {"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"}

def _yt_get(url):
    req = urllib.request.Request(url, headers=YT_HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def _yt_feed(query):
    """Лента YouTube (последние 15): [{id, title, published}] — Shorts отбрасываются."""
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    root = ET.fromstring(_yt_get("https://www.youtube.com/feeds/videos.xml?" + query))
    out = []
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", "", ns)
        link = (e.find("a:link", ns).get("href") if e.find("a:link", ns) is not None else "") or ""
        if not vid or "/shorts/" in link:
            continue
        out.append({"id": vid, "title": e.findtext("a:title", "", ns), "published": e.findtext("a:published", "", ns)})
    return out

def build_fok(out_path):
    cfg = json.load(open(os.path.join(HERE, "fok.json"), encoding="utf-8"))
    cid = cfg.get("channel_id") or ""
    if not cid:
        page = _yt_get("https://www.youtube.com/" + urllib.parse.quote(cfg["handle"]))
        m = re.search(r'"(?:externalId|channelId)":"(UC[A-Za-z0-9_-]{22})"', page) or re.search(r'/channel/(UC[A-Za-z0-9_-]{22})', page)
        cid = m.group(1) if m else ""
    if not cid:
        raise RuntimeError("не найден ID канала ФОК")
    # прошлый опубликованный список: если YouTube сейчас не ответил, лучше старый список, чем пустой
    prev = {}
    try:
        req = urllib.request.Request("https://github.com/fok-iptv-tv/mirtv-releases/releases/download/catalog/fok.json", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            for pf in json.loads(r.read().decode("utf-8")).get("feeds", []):
                if pf.get("videos"):
                    prev[pf.get("lang", "")] = pf["videos"]
    except Exception as e:
        print("ФОК: прошлый список не прочитан:", e)
    feeds = []
    for f in cfg.get("feeds", []):
        pl = f.get("playlist") or ""
        try:
            # без плейлиста — все загрузки канала без Shorts (особый плейлист UULF…)
            vids = _yt_feed("playlist_id=" + (pl or "UULF" + cid[2:]))
        except Exception as e:
            print("ФОК: лента", f.get("lang"), "не прочиталась:", e)
            vids = []
            if not pl:
                try:
                    vids = _yt_feed("channel_id=" + cid)
                except Exception:
                    pass
        if not vids and not pl:
            try:
                vids = _yt_feed("channel_id=" + cid)
            except Exception:
                pass
        if not vids and prev.get(f.get("lang", "")):
            vids = prev[f.get("lang", "")]
            print("ФОК: лента", f.get("lang"), "пустая — оставлен прошлый список")
        feeds.append({"lang": f.get("lang", ""), "title": f.get("title", ""), "playlist": pl, "videos": vids})
    res = {"generated": int(time.time()), "title": cfg.get("title", "ФОК"), "channel_id": cid,
           "youtube": "https://www.youtube.com/" + cfg["handle"], "telegram": cfg.get("telegram", ""),
           "pause": int(cfg.get("pause", 20)), "feeds": feeds}
    with open(out_path, "w", encoding="utf-8") as fo:
        json.dump(res, fo, ensure_ascii=False)
    print("ФОК:", cid, [(f["lang"], len(f["videos"])) for f in feeds])

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "catalog.json.gz")
    try:
        build_fok(os.path.join(os.path.dirname(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "catalog.json.gz")), "fok.json"))
    except Exception as e:
        print("ФОК: список видео не собран:", e)
