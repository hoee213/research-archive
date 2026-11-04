"""리서치 아카이브 빌드·배포.

사용:
  python build.py          # Desktop\\기업리포트 → docs/ 재생성 (새 파일은 catalog.json에 자동 등록)
  python build.py --push   # 재생성 후 GitHub에 커밋·푸시 (1~2분 뒤 사이트 반영)

type: company(기업분석) / call(컨콜) / industry(산업) / market(시장)
새 리포트 추가 = 기업리포트 폴더에 HTML 저장 → build.py --push.
자동 등록된 항목은 sector가 "미분류"이므로 catalog.json에서 섹터만 고치면 된다.
공개하지 않을 파일은 catalog.json에 {"src": "...", "exclude": "사유"} 로 남긴다.
"""
import html
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DIR = Path.home() / "Desktop" / "기업리포트"
CATALOG = ROOT / "catalog.json"
DOCS = ROOT / "docs"
OUT_R = DOCS / "r"
OUT_DATA = DOCS / "data"
TEXT_CAP = 40000


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def save_catalog(cat):
    lines = ",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in cat)
    CATALOG.write_text("[\n" + lines + "\n]\n", encoding="utf-8")


def guess_entry(path: Path, raw: str):
    stem = path.stem
    m_code = re.search(r"(?<![0-9A-Z])(\d{6}|\d{4}[A-Z]\d)(?![0-9A-Z])", stem)
    m_date = re.search(r"(?<!\d)(2[5-9][01]\d[0-3]\d)(?!\d)", stem)
    if m_date:
        d = m_date.group(1)
        date = f"20{d[:2]}-{d[2:4]}-{d[4:]}"
    else:
        date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    title = extract_title(raw) or stem
    name = re.split(r"[_\s(]", stem)[0] if m_code else title
    code = m_code.group(1) if m_code else None
    if re.search(r"컨콜|컨퍼런스콜|어닝콜|실적발표|IR|미팅|콥데이|탐방", stem + title):
        typ = "call"
    elif code:
        typ = "company"
    elif re.search(r"산업|섹터|밸류체인", stem + title):
        typ = "industry"
    else:
        typ = "company"
    ymd = date.replace("-", "")[2:]
    ident = f"{code}-{ymd}" if code else f"x-{abs(hash(stem)) % 10**8:08d}-{ymd}"
    e = {"id": ident, "src": path.name, "name": name, "type": typ, "sector": ["미분류"], "date": date}
    if code:
        e["code"] = code
    return e


def extract_title(raw):
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def extract_desc(raw):
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']*)', raw, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def extract_text(raw):
    t = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:TEXT_CAP]


def ensure_head(raw):
    """doctype·charset·viewport 보장 (없으면 한글 깨짐·모바일 축소)."""
    head_add = []
    if not re.search(r"<meta[^>]+charset", raw, re.I):
        head_add.append('<meta charset="utf-8">')
    if not re.search(r'<meta[^>]+name=["\']viewport', raw, re.I):
        head_add.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    if head_add:
        block = "\n".join(head_add)
        if re.search(r"<head[^>]*>", raw, re.I):
            raw = re.sub(r"(<head[^>]*>)", r"\1\n" + block, raw, count=1, flags=re.I)
        else:
            raw = block + "\n" + raw
    if not raw.lstrip().lower().startswith("<!doctype"):
        raw = "<!doctype html>\n" + raw
    return raw


def build():
    cat = load_catalog()
    known = {e["src"] for e in cat}
    added = []
    for p in sorted(SRC_DIR.glob("*.html")):
        if p.name not in known:
            e = guess_entry(p, p.read_text(encoding="utf-8", errors="replace"))
            cat.append(e)
            added.append(e)
    if added:
        save_catalog(cat)

    OUT_R.mkdir(parents=True, exist_ok=True)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    meta, search = [], {}
    live_ids = set()
    for e in cat:
        if e.get("exclude"):
            continue
        src = SRC_DIR / e["src"]
        if not src.exists():
            print(f"[경고] 원본 없음: {e['src']}")
            continue
        raw = src.read_text(encoding="utf-8", errors="replace")
        (OUT_R / f"{e['id']}.html").write_text(ensure_head(raw), encoding="utf-8")
        live_ids.add(e["id"])
        meta.append({
            "id": e["id"], "name": e["name"], "code": e.get("code"), "type": e["type"],
            "sector": e["sector"], "date": e["date"],
            "title": extract_title(raw), "desc": extract_desc(raw)[:200],
        })
        search[e["id"]] = extract_text(raw)
    for f in OUT_R.glob("*.html"):
        if f.stem not in live_ids:
            f.unlink()

    meta.sort(key=lambda x: x["date"], reverse=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    (OUT_DATA / "reports.json").write_text(
        json.dumps({"updated": stamp, "reports": meta}, ensure_ascii=False), encoding="utf-8")
    (OUT_DATA / "search.json").write_text(json.dumps(search, ensure_ascii=False), encoding="utf-8")

    print(f"게시 {len(meta)}건 · 제외 {sum(1 for e in cat if e.get('exclude'))}건")
    for e in added:
        print(f"[신규 자동등록] {e['src']} → {e['name']} / {e['type']} / 섹터 미분류 (catalog.json에서 수정)")
    return added


def push():
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8")
    git("add", "-A")
    if not git("status", "--porcelain").stdout.strip():
        print("변경 없음 — 푸시 생략")
        return
    git("commit", "-m", f"archive: {datetime.now():%Y-%m-%d %H:%M} 갱신")
    git("pull", "--rebase", "-q")
    git("push", "-q")
    print("푸시 완료 → https://hoee213.github.io/research-archive/")


if __name__ == "__main__":
    build()
    if "--push" in sys.argv:
        push()
