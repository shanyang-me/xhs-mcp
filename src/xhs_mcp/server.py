"""Xiaohongshu MCP Server - Playwright-based API with browser signing.

Uses Playwright browser for:
1. Generating XHS sign headers (X-s, X-t) via window._webmsxyw()
2. Making API calls via APIRequestContext (shares browser cookies, no CORS)
3. Image uploads to XHS CDN
"""

import json
import os
import threading
from pathlib import Path

from fastmcp import FastMCP

COOKIE_DIR = Path.home() / ".xhs-mcp"
COOKIE_FILE = COOKIE_DIR / "cookies.json"

mcp = FastMCP("xhs-mcp")

_lock = threading.Lock()
_pw = None
_browser = None
_ctx = None
_page = None


def _ensure_browser():
    """Initialize Playwright browser with cookies and sign function."""
    global _pw, _browser, _ctx, _page
    if _page is not None:
        return

    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=True)
    _ctx = _browser.new_context()

    cookies = _load_cookies()
    if cookies:
        _ctx.add_cookies(cookies)

    _page = _ctx.new_page()
    Stealth().apply_stealth_sync(_page)
    _page.goto("https://www.xiaohongshu.com", timeout=60000, wait_until="domcontentloaded")
    _page.wait_for_timeout(3000)


def _restart_browser():
    """Restart browser with fresh cookies."""
    global _pw, _browser, _ctx, _page
    if _browser:
        try:
            _browser.close()
        except Exception:
            pass
    if _pw:
        try:
            _pw.stop()
        except Exception:
            pass
    _pw = _browser = _ctx = _page = None
    _ensure_browser()


def _load_cookies() -> list[dict]:
    """Load cookies from saved file. Supports both Playwright and Chrome DevTools formats."""
    if not COOKIE_FILE.exists():
        return []
    try:
        with open(COOKIE_FILE) as f:
            raw = json.load(f)
    except Exception:
        return []

    # Playwright format: list of {name, value, domain, path, ...}
    if isinstance(raw, list) and raw and "name" in raw[0]:
        cookies = []
        for c in raw:
            cookie = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".xiaohongshu.com"),
                "path": c.get("path", "/"),
            }
            if c.get("expires", -1) > 0:
                cookie["expires"] = c["expires"]
            cookies.append(cookie)
        return cookies

    # String format: {"cookie": "k1=v1; k2=v2"}
    if isinstance(raw, dict) and "cookie" in raw:
        cookies = []
        for part in raw["cookie"].split("; "):
            if "=" in part:
                name, value = part.split("=", 1)
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".xiaohongshu.com",
                    "path": "/",
                })
        return cookies

    return []


def _save_cookies(cookies: list[dict]):
    """Save cookies in Playwright format."""
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_FILE, "w") as f:
        json.dump(cookies, f)


def _sign(uri: str, data=None) -> dict:
    """Generate XHS sign headers using browser JS."""
    signs = _page.evaluate(
        "([url, data]) => window._webmsxyw(url, data)", [uri, data]
    )
    return {
        "X-s": str(signs.get("X-s", "")),
        "X-t": str(signs.get("X-t", "")),
        "X-s-common": str(signs.get("X-s-common", "")),
    }


def _api_get(uri: str, params: dict | None = None, host: str = "https://edith.xiaohongshu.com") -> dict:
    """Signed GET request via Playwright APIRequestContext."""
    with _lock:
        _ensure_browser()
        url = f"{host}{uri}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{qs}"
        signs = _sign(uri if not params else f"{uri}?{qs}")
        resp = _ctx.request.get(url, headers={
            **signs,
            "Content-Type": "application/json",
            "Origin": "https://www.xiaohongshu.com",
            "Referer": "https://www.xiaohongshu.com/",
        })
        return resp.json()


def _api_post(uri: str, data: dict, host: str = "https://edith.xiaohongshu.com") -> dict:
    """Signed POST request via Playwright APIRequestContext."""
    with _lock:
        _ensure_browser()
        signs = _sign(uri, data)
        resp = _ctx.request.post(f"{host}{uri}", headers={
            **signs,
            "Content-Type": "application/json",
            "Origin": "https://www.xiaohongshu.com",
            "Referer": "https://www.xiaohongshu.com/",
        }, data=json.dumps(data, separators=(",", ":"), ensure_ascii=False))
        return resp.json()


def _upload_image(file_path: str) -> str:
    """Upload image to XHS CDN. Returns file_id."""
    from xhs.help import sign as quick_sign

    with _lock:
        _ensure_browser()
        browser_cookies = _ctx.cookies()
        a1 = next((c["value"] for c in browser_cookies if c["name"] == "a1"), "")

    uri = "/api/media/v1/upload/web/permit"
    qs = "biz_name=spectrum&scene=image&file_count=1&version=1&source=web"
    full_uri = f"{uri}?{qs}"
    signs = quick_sign(full_uri, a1=a1)

    with _lock:
        resp = _ctx.request.get(f"https://creator.xiaohongshu.com{full_uri}", headers={
            "x-s": signs["x-s"],
            "x-t": signs["x-t"],
            "x-s-common": signs["x-s-common"],
            "Content-Type": "application/json",
            "Origin": "https://creator.xiaohongshu.com",
            "Referer": "https://creator.xiaohongshu.com/",
        })
        permit = resp.json()

    permit_data = permit.get("data", permit)
    if not permit_data.get("uploadTempPermits"):
        raise RuntimeError(f"Upload permit failed: {permit}")

    temp_permit = permit_data["uploadTempPermits"][0]
    file_id = temp_permit["fileIds"][0]
    token = temp_permit["token"]

    content_type = "image/jpeg" if file_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    with _lock:
        with open(file_path, "rb") as f:
            resp = _ctx.request.put(
                f"https://ros-upload.xiaohongshu.com/{file_id}",
                headers={"X-Cos-Security-Token": token, "Content-Type": content_type},
                data=f.read(),
            )
        if resp.status not in (200, 204):
            raise RuntimeError(f"Upload failed: {resp.status}")

    return file_id


# ──────────────────── Login Tools ────────────────────

@mcp.tool
def check_login_status() -> str:
    """Check Xiaohongshu login status (检查小红书登录状态)"""
    try:
        result = _api_get("/api/sns/web/v1/user/selfinfo")
        if result.get("code") != 0:
            return f"Not logged in: {result.get('msg', 'unknown error')}\nUse get_login_qrcode to log in."
        data = result.get("data", {})
        nickname = data.get("basic_info", {}).get("nickname", "unknown")
        return f"Logged in as: {nickname}"
    except Exception as e:
        return f"Login check failed: {e}\nUse get_login_qrcode to log in."


@mcp.tool
def get_login_qrcode() -> str:
    """Get QR code for Xiaohongshu login. Scan with XHS app, then call check_qrcode_status.
    (获取小红书登录二维码，用小红书APP扫码后调用 check_qrcode_status)"""
    try:
        result = _api_post("/api/sns/web/v1/login/qrcode/create", {})
        data = result.get("data", result)
        qr_url = data.get("url", "")
        qr_id = data.get("qr_id", "")
        code = data.get("code", "")

        # Save QR image using qrcode library if available
        qr_image_path = ""
        try:
            import qrcode
            img = qrcode.make(qr_url)
            qr_image_path = str(COOKIE_DIR / "login_qr.png")
            COOKIE_DIR.mkdir(parents=True, exist_ok=True)
            img.save(qr_image_path)
        except ImportError:
            pass

        return json.dumps({
            "qr_url": qr_url,
            "qr_id": qr_id,
            "code": code,
            "qr_image": qr_image_path,
            "message": "Scan the QR code with Xiaohongshu app, then call check_qrcode_status with the qr_id and code.",
        }, ensure_ascii=False)
    except Exception as e:
        return f"Failed to get QR code: {e}"


@mcp.tool
def check_qrcode_status(qr_id: str, code: str) -> str:
    """Check QR code scan status. Call after scanning the QR code from get_login_qrcode.

    Args:
        qr_id: qr_id from get_login_qrcode response
        code: code from get_login_qrcode response
    """
    try:
        uri = "/api/sns/web/v1/login/qrcode/status"
        params = {"qr_id": qr_id, "code": code}
        result = _api_get(uri, params)
        data = result.get("data", result)
        status = data.get("code_status", -1)

        if status == 0:
            return "Waiting for scan..."
        elif status == 1:
            return "Scanned, waiting for confirmation..."
        elif status == 2:
            # Login success - save browser cookies
            with _lock:
                cookies = _ctx.cookies()
                _save_cookies(cookies)
                # Restart browser to pick up new session
                _restart_browser()
            return "Login successful! Cookies saved."
        else:
            return f"QR code expired (status={status}). Call get_login_qrcode again."
    except Exception as e:
        return f"Status check failed: {e}"


@mcp.tool
def reload_cookies() -> str:
    """Reload cookies after external login (e.g. via xiaohongshu-login CLI).
    (重新加载cookies)"""
    try:
        with _lock:
            _restart_browser()
        return check_login_status()
    except Exception as e:
        return f"Reload failed: {e}"


# ──────────────────── Publish Tools ────────────────────

@mcp.tool
def publish_content(
    title: str,
    content: str,
    images: list[str],
    tags: list[str] | None = None,
    is_private: bool = False,
    post_time: str | None = None,
) -> str:
    """Publish an image note to Xiaohongshu (发布小红书图文内容)

    Args:
        title: Note title (max ~20 Chinese characters)
        content: Note body text
        images: List of local image file paths (at least 1 required)
        tags: Optional topic tags, e.g. ["AI", "科技"]  (max 10)
        is_private: Whether to publish as private note
        post_time: Optional scheduled publish time, format "2024-01-20 10:30:00"
    """
    if not images:
        return _err("At least 1 image is required")
    for img in images:
        if not os.path.exists(img):
            return _err(f"Image not found: {img}")

    try:
        # 1. Upload images
        image_infos = []
        for img_path in images:
            file_id = _upload_image(img_path)
            image_infos.append({
                "file_id": file_id,
                "metadata": {"source": -1},
                "stickers": {"version": 2, "floating": []},
                "extra_info_json": '{"mimeType":"image/jpeg"}',
            })

        # 2. Resolve tags to topics
        topics = []
        if tags:
            for tag_name in tags[:10]:
                try:
                    result = _api_post("/web_api/sns/v1/search/topic", {
                        "keyword": tag_name,
                        "suggest_topic_request": {"title": "", "desc": ""},
                        "page": {"page_size": 20, "page": 1},
                    })
                    dtos = result.get("data", result).get("topic_info_dtos", result.get("topic_info_dtos", []))
                    topics.append(dtos[0] if dtos else {"id": "", "name": tag_name, "type": "topic"})
                except Exception:
                    topics.append({"id": "", "name": tag_name, "type": "topic"})

        # 3. Build description with hashtags
        full_desc = f"{content}\n\n" + " ".join(f"#{t}" for t in tags) if tags else content

        # 4. Post timing
        post_time_ms = None
        if post_time:
            from datetime import datetime
            post_time_ms = round(int(datetime.strptime(post_time, "%Y-%m-%d %H:%M:%S").timestamp()) * 1000)

        # 5. Create note
        note_data = {
            "common": {
                "type": "normal",
                "title": title,
                "note_id": "",
                "desc": full_desc,
                "source": '{"type":"web","ids":"","extraInfo":"{\\"subType\\":\\"official\\"}"}',
                "business_binds": json.dumps({
                    "version": 1, "noteId": 0,
                    "noteOrderBind": {},
                    "notePostTiming": {"postTime": post_time_ms},
                    "noteCollectionBind": {"id": ""},
                }, separators=(",", ":")),
                "ats": [],
                "hash_tag": topics,
                "post_loc": {},
                "privacy_info": {"op_type": 1, "type": int(is_private)},
            },
            "image_info": {"images": image_infos},
            "video_info": None,
        }

        result = _api_post("/web_api/sns/v2/note", note_data)

        if result.get("success") or result.get("code", -1) == 0:
            data = result.get("data", {})
            note_id = data.get("id", data.get("note_id", result.get("note_id", "")))
            share_link = result.get("share_link", "")
            url = share_link or (f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else "")
            return json.dumps({"success": True, "note_id": note_id, "url": url}, ensure_ascii=False)
        else:
            return _err(result.get("msg", str(result)))

    except Exception as e:
        return _err(str(e))


# ──────────────────── Browse Tools ────────────────────

@mcp.tool
def search_feeds(keyword: str, sort: str = "general", note_type: int = 0) -> str:
    """Search Xiaohongshu notes (搜索小红书内容)

    Args:
        keyword: Search keyword
        sort: Sort order: general, time_descending, popularity_descending
        note_type: Note type: 0=all, 1=video, 2=image
    """
    try:
        from xhs.help import get_search_id
        result = _api_post("/api/sns/web/v1/search/notes", {
            "keyword": keyword,
            "page": 1,
            "page_size": 20,
            "search_id": get_search_id(),
            "sort": sort,
            "note_type": note_type,
        })
        items = result.get("data", {}).get("items", [])
        feeds = []
        for item in items:
            nc = item.get("note_card", {})
            feeds.append({
                "id": item.get("id", ""),
                "title": nc.get("display_title", ""),
                "user": nc.get("user", {}).get("nickname", ""),
                "user_id": nc.get("user", {}).get("user_id", ""),
                "likes": nc.get("interact_info", {}).get("liked_count", "0"),
                "xsec_token": item.get("xsec_token", ""),
            })
        return json.dumps({"feeds": feeds, "count": len(feeds)}, ensure_ascii=False)
    except Exception as e:
        return f"Search failed: {e}"


@mcp.tool
def get_feed_detail(note_id: str, xsec_token: str = "") -> str:
    """Get note details (获取笔记详情)

    Args:
        note_id: Note ID
        xsec_token: Access token from search results
    """
    try:
        result = _api_post("/api/sns/web/v1/feed", {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_token": xsec_token,
        })
        items = result.get("data", {}).get("items", [])
        if not items:
            return "Note not found"
        note = items[0].get("note_card", {})
        interact = note.get("interact_info", {})
        return json.dumps({
            "title": note.get("title", ""),
            "desc": note.get("desc", ""),
            "user": note.get("user", {}).get("nickname", ""),
            "likes": interact.get("liked_count", "0"),
            "comments": interact.get("comment_count", "0"),
            "collects": interact.get("collected_count", "0"),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Failed: {e}"


@mcp.tool
def user_profile(user_id: str) -> str:
    """Get user profile info (获取用户主页信息)

    Args:
        user_id: Xiaohongshu user ID
    """
    try:
        result = _api_get("/api/sns/web/v1/user/otherinfo", {"target_user_id": user_id})
        data = result.get("data", result)
        basic = data.get("basic_info", {})
        interactions = data.get("interactions", [])
        return json.dumps({
            "nickname": basic.get("nickname", ""),
            "desc": basic.get("desc", ""),
            "ip_location": basic.get("ip_location", ""),
            "interactions": {i.get("name", ""): i.get("count", "0") for i in interactions},
        }, ensure_ascii=False)
    except Exception as e:
        return f"Failed: {e}"


def _err(msg: str) -> str:
    return json.dumps({"success": False, "error": msg}, ensure_ascii=False)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Xiaohongshu MCP Server")
    parser.add_argument("--port", type=int, default=18060, help="HTTP port (default: 18060)")
    parser.add_argument("--transport", choices=["http", "stdio"], default="http", help="MCP transport")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="http", port=args.port, stateless_http=True)


if __name__ == "__main__":
    main()
