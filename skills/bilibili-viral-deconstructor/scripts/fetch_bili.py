#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_bili.py — 取 B 站视频的「口播字幕 + 数据 + 元信息」，喂给拆解分析。

它复刻了油猴脚本里用的那套 B 站接口，但跑在命令行：
  1. /x/web-interface/view   → 标题、封面、cid、三连数据（公开，无需登录）
  2. /x/relation/stat        → UP 主粉丝数（公开）
  3. /x/player/wbi/v2        → 字幕列表（CC / AI 字幕，需要登录 SESSDATA + wbi 签名）
  4. 字幕 subtitle_url 的 json → body[]{from,to,content}

字幕为什么要登录：B 站的 CC / AI 字幕只在登录态下返回，所以要么传 --sessdata
（浏览器 Cookie 里的 SESSDATA），要么用油猴脚本在网页上导出 SRT 再用 --srt 传进来。
没有字幕也没关系——脚本会把能拿到的数据都存下，分析时优雅降级。

用法：
  python fetch_bili.py <链接或BV号> [--sessdata XXX] [--srt 本地字幕] [--out-dir 目录]
  # SESSDATA 也可以放环境变量 BILI_SESSDATA
输出：
  <out-dir>/<bvid>_data.json   结构化全量数据（meta / stat / owner / subtitle）
  <out-dir>/<bvid>_subtitle.txt 纯文本口播稿（带时间戳，方便人看）
脚本最后会在 stdout 打印一段 SUMMARY，分析时先看这段。
"""
import sys, os, re, json, time, hashlib, argparse
from urllib import request, parse
from functools import reduce

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# wbi 混淆 key 的重排表（B 站固定算法）
MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def http_get(url, sessdata=None, referer="https://www.bilibili.com"):
    headers = {"User-Agent": UA, "Referer": referer, "Accept": "application/json, */*"}
    if sessdata:
        headers["Cookie"] = f"SESSDATA={sessdata}"
    req = request.Request(url, headers=headers)
    with request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def get_json(url, sessdata=None):
    return json.loads(http_get(url, sessdata))


def parse_bvid(s):
    """从链接 / BV号 / av号里抠出 bvid 或 aid。返回 (bvid, aid)。"""
    s = s.strip()
    m = re.search(r"(BV[0-9A-Za-z]{10})", s)
    if m:
        return m.group(1), None
    m = re.search(r"av(\d+)", s, re.I)
    if m:
        return None, int(m.group(1))
    if s.isdigit():
        return None, int(s)
    raise ValueError(f"无法从输入里识别 BV号/av号：{s}")


def get_wbi_keys(sessdata=None):
    data = get_json("https://api.bilibili.com/x/web-interface/nav", sessdata)
    wbi = data.get("data", {}).get("wbi_img", {})
    img = wbi.get("img_url", "")
    sub = wbi.get("sub_url", "")
    img_key = img.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def mixin_key(img_key, sub_key):
    s = img_key + sub_key
    return reduce(lambda acc, i: acc + s[i], MIXIN_TAB, "")[:32]


def wbi_sign(params, mk):
    params = dict(params)
    params["wts"] = int(time.time())
    items = sorted(params.items())
    # 值里过滤掉 ! ' ( ) * 这些字符
    query = parse.urlencode([(k, re.sub(r"[!'()*]", "", str(v))) for k, v in items])
    w_rid = hashlib.md5((query + mk).encode()).hexdigest()
    return query + "&w_rid=" + w_rid


def fetch_metadata(bvid, aid, sessdata):
    q = f"bvid={bvid}" if bvid else f"aid={aid}"
    data = get_json(f"https://api.bilibili.com/x/web-interface/view?{q}", sessdata)
    if data.get("code") != 0:
        raise RuntimeError(f"取视频信息失败：code={data.get('code')} {data.get('message')}")
    d = data["data"]
    stat = d.get("stat", {})
    owner = d.get("owner", {})
    return {
        "bvid": d.get("bvid"),
        "aid": d.get("aid"),
        "cid": d.get("cid"),
        "title": d.get("title"),
        "desc": d.get("desc"),
        "cover": d.get("pic"),
        "duration_sec": d.get("duration"),
        "pubdate": d.get("pubdate"),
        "tname": d.get("tname"),
        "owner": {"mid": owner.get("mid"), "name": owner.get("name")},
        "stat": {
            "view": stat.get("view"),
            "danmaku": stat.get("danmaku"),
            "reply": stat.get("reply"),
            "favorite": stat.get("favorite"),
            "coin": stat.get("coin"),
            "share": stat.get("share"),
            "like": stat.get("like"),
        },
    }


def fetch_follower(mid, sessdata):
    try:
        data = get_json(f"https://api.bilibili.com/x/relation/stat?vmid={mid}", sessdata)
        return data.get("data", {}).get("follower")
    except Exception:
        return None


def fetch_subtitle(aid, cid, sessdata):
    """返回 (subtitle_body[], lan_doc)。需要登录态。"""
    if not sessdata:
        return [], None, "未提供 SESSDATA，跳过在线字幕（可改用 --srt 传本地字幕）"
    try:
        img_key, sub_key = get_wbi_keys(sessdata)
        mk = mixin_key(img_key, sub_key)
        signed = wbi_sign({"aid": aid, "cid": cid}, mk)
        data = get_json(f"https://api.bilibili.com/x/player/wbi/v2?{signed}", sessdata)
        subs = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subs:
            return [], None, "该视频没有 CC/AI 字幕，或当前账号无权限"
        sub = subs[0]
        url = sub.get("subtitle_url", "")
        if url.startswith("//"):
            url = "https:" + url
        sub_json = get_json(url, sessdata)
        body = [
            {"from": it.get("from", 0), "to": it.get("to", 0), "content": it.get("content", "")}
            for it in sub_json.get("body", [])
        ]
        return body, sub.get("lan_doc"), None
    except Exception as e:
        return [], None, f"取字幕出错：{e}"


def parse_local_subtitle(path):
    """支持 .srt / .json(B站body格式) / .txt 纯文本。"""
    raw = open(path, encoding="utf-8", errors="replace").read()
    if path.lower().endswith(".json"):
        j = json.loads(raw)
        body = j.get("body", j if isinstance(j, list) else [])
        return [{"from": it.get("from", 0), "to": it.get("to", 0),
                 "content": it.get("content", it.get("text", ""))} for it in body]
    if "-->" in raw:  # SRT
        body = []
        for block in re.split(r"\n\s*\n", raw.strip()):
            lines = [l for l in block.splitlines() if l.strip()]
            ts = next((l for l in lines if "-->" in l), None)
            if not ts:
                continue
            a, b = [t.strip() for t in ts.split("-->")]
            text = " ".join(lines[lines.index(ts) + 1:])
            body.append({"from": _srt_sec(a), "to": _srt_sec(b), "content": text})
        return body
    # 纯文本：一行一句，无时间戳
    return [{"from": 0, "to": 0, "content": l.strip()} for l in raw.splitlines() if l.strip()]


def _srt_sec(t):
    t = t.replace(".", ",")
    h, m, rest = t.split(":")
    s, ms = (rest.split(",") + ["0"])[:2]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def fmt_time(sec):
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default="", help="视频链接 / BV号 / av号（只做字幕分析时可省略，配 --srt）")
    ap.add_argument("--sessdata", default=os.environ.get("BILI_SESSDATA", ""))
    ap.add_argument("--srt", help="本地字幕文件(.srt/.json/.txt)，优先于在线字幕")
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    notes = []

    bvid = aid = None
    if args.target:
        try:
            bvid, aid = parse_bvid(args.target)
        except ValueError as e:
            print(f"[错误] {e}", file=sys.stderr)
            sys.exit(1)
    elif not args.srt:
        print("[错误] 没给视频链接/BV号，也没给 --srt 字幕文件，无从下手", file=sys.stderr)
        sys.exit(1)

    meta = {"bvid": bvid, "aid": aid, "title": None, "stat": {}, "owner": {}}
    if bvid or aid:
        try:
            meta = fetch_metadata(bvid, aid, args.sessdata)
            bvid = meta["bvid"]; aid = meta["aid"]
        except Exception as e:
            notes.append(f"取视频元信息失败（可能是网络/风控）：{e}")
            meta = {"bvid": bvid, "aid": aid, "title": None, "stat": {}, "owner": {}}
    else:
        notes.append("仅做字幕分析（无视频链接/BV号），第一层数据将缺失")

    follower = None
    if meta.get("owner", {}).get("mid"):
        follower = fetch_follower(meta["owner"]["mid"], args.sessdata)

    # 字幕：本地优先
    if args.srt and os.path.exists(args.srt):
        body = parse_local_subtitle(args.srt)
        lan = "本地导入"
        notes.append(f"使用本地字幕：{args.srt}（{len(body)} 条）")
    else:
        body, lan, sub_note = fetch_subtitle(aid, meta.get("cid"), args.sessdata)
        if sub_note:
            notes.append(sub_note)

    out = {
        "source": args.target,
        "meta": meta,
        "follower": follower,
        "subtitle": {"lan": lan, "count": len(body), "body": body},
        "notes": notes,
    }
    stem = bvid or (f"av{aid}" if aid else "video")
    data_path = os.path.join(args.out_dir, f"{stem}_data.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    txt_path = os.path.join(args.out_dir, f"{stem}_subtitle.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for it in body:
            f.write(f"[{fmt_time(it['from'])}] {it['content']}\n")

    # ---- SUMMARY（分析时先读这段）----
    st = meta.get("stat", {}) or {}
    view = st.get("view")
    def ratio(n):
        return f"{n / view * 100:.2f}%" if view and n else "—"
    print("==== SUMMARY ====")
    print(f"标题: {meta.get('title')}")
    print(f"UP主: {meta.get('owner', {}).get('name')}  粉丝: {follower}")
    print(f"播放: {view}  点赞: {st.get('like')}  投币: {st.get('coin')}  收藏: {st.get('favorite')}  评论: {st.get('reply')}  转发: {st.get('share')}  弹幕: {st.get('danmaku')}")
    if view and follower:
        print(f"播粉比: {view / follower:.1f} 倍")
    print(f"点赞率: {ratio(st.get('like'))}  投币率: {ratio(st.get('coin'))}  收藏率: {ratio(st.get('favorite'))}  评论率: {ratio(st.get('reply'))}")
    print(f"时长: {fmt_time(meta.get('duration_sec'))}  字幕条数: {len(body)}（{lan or '无'}）")
    print(f"封面: {meta.get('cover')}")
    if notes:
        print("提示: " + " | ".join(notes))
    print(f"数据文件: {data_path}")
    print(f"口播稿:   {txt_path}")


if __name__ == "__main__":
    main()
