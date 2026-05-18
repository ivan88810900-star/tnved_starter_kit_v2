import re, sys, time, pathlib, hashlib, yaml, collections
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE = pathlib.Path(__file__).resolve().parents[1]
RAW = BASE / "raw"

def sha256_bytes(b: bytes) -> str:
    import hashlib; h=hashlib.sha256(); h.update(b); return h.hexdigest()

def allowed(url: str, allowed_domains):
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and any(host.endswith(d) for d in allowed_domains)

def match_url(url: str, exts):
    u = url.lower()
    return any(u.endswith(ext) for ext in exts)

def harvest_recursive(start_urls, allowed_domains, exts, max_pages=200, max_depth=2):
    seen_pages=set(); out=set()
    Q=collections.deque([(u,0) for u in start_urls])
    headers={"User-Agent":"tnved-pro/1.1"}
    while Q and len(seen_pages) < max_pages:
        url,depth = Q.popleft()
        if url in seen_pages: continue
        seen_pages.add(url)
        try:
            r = requests.get(url, timeout=60, headers=headers)
            if r.status_code>=400: continue
            soup = BeautifulSoup(r.text, "lxml")
        except Exception:
            continue

        # собрать файлы
        for a in soup.find_all("a", href=True):
            link = urljoin(url, a["href"])
            link = link.split("#")[0]
            if not allowed(link, allowed_domains): continue
            if match_url(link, exts):
                out.add(link)
            # углубление по HTML
            if depth < max_depth and (link.lower().endswith(".html") or link.lower().endswith(".htm")):
                Q.append((link, depth+1))
    return sorted(out)

def main():
    cfg = yaml.safe_load(open(BASE / "sources.yml", "r", encoding="utf-8"))
    allowed_domains = cfg.get("allowed_domains", [])
    datasets = cfg.get("datasets", {})
    keys = (sys.argv[1].split(",") if len(sys.argv)>1 else list(datasets.keys()))
    for key in keys:
        meta = datasets[key]; version=meta["version"]
        exts = meta.get("match",{}).get("extensions",[".pdf",".xml",".html",".htm"])
        start_pages = meta.get("start_pages", [])
        files = harvest_recursive(start_pages, allowed_domains, exts, max_pages=400, max_depth=2)
        print(f"Found {len(files)} files for {key}")

        dl_urls=[]; save_as=[]; chks=[]
        RAW.joinpath(key, version).mkdir(parents=True, exist_ok=True)
        for url in files:
            try:
                resp = requests.get(url, timeout=120, headers={"User-Agent":"tnved-pro/1.1"})
                resp.raise_for_status()
                from urllib.parse import urlparse
                name = pathlib.Path(urlparse(url).path).name or f"file_{int(time.time()*1000)}"
                dst = RAW / key / version / name
                if dst.exists():  # пропустим дубликат по имени
                    continue
                dst.write_bytes(resp.content)
                digest = sha256_bytes(resp.content)
                dl_urls.append(url); save_as.append(name); chks.append(digest)
                print(f"✓ {name}  {len(resp.content)} bytes")
            except Exception as e:
                print(f"! skip {url}: {e}")

        # ДОКАЧКА ЯВНЫХ URL ИЗ КОНФИГА (если заданы)
        extra = meta.get("urls", [])
        for url in extra:
            try:
                import requests, time, pathlib
                from urllib.parse import urlparse
                resp = requests.get(url, timeout=120, headers={"User-Agent":"tnved-pro/1.1"})
                resp.raise_for_status()
                name = pathlib.Path(urlparse(url).path).name or f"file_{int(time.time()*1000)}"
                dst = RAW / key / version / name
                if not dst.exists():
                    dst.write_bytes(resp.content)
                    print(f"✓ extra {name}  {len(resp.content)} bytes")
            except Exception as e:
                print(f"! extra skip {url}: {e}")
        meta["urls"]=dl_urls; meta["save_as"]=save_as; meta["checksum"]=chks
    yaml.safe_dump(cfg, open(BASE / "sources.yml","w",encoding="utf-8"), allow_unicode=True, sort_keys=False)
    print("Done.")
if __name__=="__main__": main()