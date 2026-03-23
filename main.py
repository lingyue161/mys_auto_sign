#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
米游社自动签到工具 v3.0
- 每次运行扫码登录，自动获取最新 stoken
- 正确处理 v2 stoken -> ltoken_v2 -> 游戏角色 -> 签到 的完整流程
- 增加 game_token 备用方案，解决 mid 为空的问题
"""

import sys
import json
import time
import hashlib
import random
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from typing import List, Dict

import requests
import qrcode


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def log(msg: str):
    print(msg, flush=True)


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def gen_device_id() -> str:
    h = ''.join(random.choices('0123456789abcdef', k=32))
    return f"{h[:8]}-{h[8:12]}-4{h[12:16]}-{h[16:20]}-{h[20:]}"


# DS 签名 salt
# 参考: https://blog.oldwu.top/index.php/archives/25/
# 米游社 2.11.1 版本的 salt
SALT_BBS = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"

def ds_gen(body: str = "", query: str = "") -> str:
    """生成 DS 签名（BBS 签到接口使用）"""
    t = str(int(time.time()))
    r = str(random.randint(100001, 200000))
    # 使用 BBS salt（适用于米游社 BBS 签到接口）
    raw = f"salt={SALT_BBS}&t={t}&r={r}&b={body}&q={query}"
    return f"{t},{r},{md5(raw)}"


# ──────────────────────────────────────────────
# 请求头工厂
# ──────────────────────────────────────────────

APP_ID      = "bll8iq97cem8"
APP_VER     = "2.67.1"
BBS_VER     = "2.11.1"  # 使用 oldwu 博客中的版本

def app_headers(device_id: str, cookie: str = "") -> dict:
    """米游社 App 专用请求头（含 x-rpc-app_id）"""
    h = {
        "Accept":           "application/json",
        "Accept-Language":  "zh-CN,zh;q=0.9",
        "Content-Type":     "application/json",
        "x-rpc-app_id":     APP_ID,
        "x-rpc-app_version": APP_VER,
        "x-rpc-client_type": "2",
        "x-rpc-device_id":  device_id,
        "User-Agent":       f"Mozilla/5.0 (Linux; Android 12; LIO-AN00) AppleWebKit/537.36 "
                            f"(KHTML, like Gecko) Version/4.0 Chrome/103.0.5060.129 "
                            f"Mobile Safari/537.36 miHoYoBBS/{APP_VER}",
        "Referer":          "https://app.mihoyo.com",
    }
    if cookie:
        h["Cookie"] = cookie
    return h


def bbs_headers(device_id: str, cookie: str = "", signgame: str = "") -> dict:
    """米游社 BBS / 签到接口通用请求头"""
    h = {
        "Accept":            "application/json, text/plain, */*",
        "Accept-Language":   "zh-CN,en-US;q=0.8",
        "Accept-Encoding":   "gzip, deflate",
        "x-rpc-app_id":     APP_ID,  # *** 关键：添加 x-rpc-app_id ***
        "x-rpc-app_version": BBS_VER,
        "x-rpc-client_type": "5",
        "x-rpc-channel":     "miyousheluodi",
        "x-rpc-device_id":   device_id,
        "User-Agent":        f"Mozilla/5.0 (Linux; Android 12; Unspecified Device) "
                             f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                             f"Chrome/103.0.5060.129 Mobile Safari/537.36 miHoYoBBS/{BBS_VER}",
        "X-Requested-With":  "com.mihoyo.hyperion",
        "Origin":           "https://act.mihoyo.com",
        "Referer":          "https://act.mihoyo.com/",
    }
    if cookie:
        h["Cookie"] = cookie
    if signgame:
        h["x-rpc-signgame"] = signgame
    return h


# ──────────────────────────────────────────────
# API 地址
# ──────────────────────────────────────────────

# 扫码登录
URL_QR_FETCH  = "https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/fetch"
URL_QR_QUERY  = "https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/query"

# stoken 系列
URL_GET_STOKEN_BY_GAME_TOKEN = "https://api-takumi.mihoyo.com/account/ma-cn-session/app/getTokenByGameToken"
URL_GET_LTOKEN_BY_STOKEN     = "https://passport-api.mihoyo.com/account/auth/api/getLTokenBySToken"
URL_GET_COOKIE_TOKEN          = "https://api-takumi.mihoyo.com/auth/api/getCookieAccountInfoBySToken"

# 用户信息
URL_USER_INFO = "https://bbs-api.miyoushe.com/user/api/getUserFullInfo"

# 游戏角色 - 有两个接口
# 方式1: 通过 SToken（推荐，因为我们有 v2 stoken）
URL_GAME_ROLES_BY_STOKEN = "https://api-takumi.miyoushe.com/binding/api/getUserGameRolesByStoken"
# 方式2: 通过 Cookie LToken（备用方案）
URL_GAME_ROLES_BY_COOKIE = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"

# 签到（通用：崩坏2/3/未定/星穹铁道）
URL_SIGN_INFO   = "https://api-takumi.mihoyo.com/event/luna/info"
URL_SIGN_DO     = "https://api-takumi.mihoyo.com/event/luna/sign"

# 签到（原神专用 - 使用 act-nap-api 域名 + hk4e 子路径）
URL_YS_INFO     = "https://act-nap-api.mihoyo.com/event/luna/hk4e/info"
URL_YS_SIGN      = "https://act-nap-api.mihoyo.com/event/luna/hk4e/sign"

# 签到（绝区零专用 - 使用 act-nap-api 域名 + zzz 子路径）
URL_ZZZ_INFO    = "https://act-nap-api.mihoyo.com/event/luna/zzz/info"
URL_ZZZ_SIGN    = "https://act-nap-api.mihoyo.com/event/luna/zzz/sign"


# ──────────────────────────────────────────────
# 游戏列表
# ──────────────────────────────────────────────

GAMES = {
    # game_biz: (显示名, act_id, info_url, sign_url)
    "bh2_cn":   ("崩坏学园2",      "e202203291431091", URL_SIGN_INFO, URL_SIGN_DO),
    "bh3_cn":   ("崩坏3",          "e202306201626331", URL_SIGN_INFO, URL_SIGN_DO),
    "nxx_cn":   ("未定事件簿",     "e202202251749321", URL_SIGN_INFO, URL_SIGN_DO),
    # 原神 - 使用 hk4e 子路径（从抓包获取的接口）
    "hk4e_cn":  ("原神",           "e202311201442471", URL_YS_INFO, URL_YS_SIGN),
    "hkrpg_cn": ("崩坏：星穹铁道", "e202304121516551", URL_SIGN_INFO, URL_SIGN_DO),
    # 绝区零 - 使用 zzz 子路径
    "nap_cn":   ("绝区零",         "e202406242138391", URL_ZZZ_INFO, URL_ZZZ_SIGN),
}


# ──────────────────────────────────────────────
# 账号凭证
# ──────────────────────────────────────────────

class Account:
    """保存一个已登录账号的所有凭证"""

    def __init__(self):
        self.session   = requests.Session()
        self.device_id = gen_device_id()
        self.uid       = ""
        self.mid       = ""
        self.nickname  = ""
        # 登录后获得
        self.stoken    = ""   # v2 格式：v2_xxx
        self.game_token = ""  # game_token（备用凭证）
        # 通过 stoken 换取
        self.ltoken_v2 = ""
        self.ltuid_v2  = ""
        self.cookie_token = ""  # cookie_token（用于 getUserGameRolesByCookie）

    # ── 扫码登录 ────────────────────────────────

    def qrcode_login(self) -> bool:
        """扫码登录：获取二维码 → 等待扫码 → 换取 stoken"""
        print("\n=== 扫码登录 ===")
        print("正在获取二维码...")

        # 1. 获取二维码 URL
        body = json.dumps({"app_id": 4, "device": self.device_id})
        resp = self.session.post(
            URL_QR_FETCH,
            data=body,
            headers=app_headers(self.device_id),
            timeout=10,
        )
        data = resp.json()
        if data.get("retcode") != 0:
            print(f"获取二维码失败: {data.get('message')}")
            return False

        qr_url = data["data"]["url"]
        ticket = parse_qs(urlparse(qr_url).query).get("ticket", [None])[0]

        # 2. 展示二维码
        print("\n请用米游社 App 扫描以下二维码：")
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(qr_url)
        qr.make(fit=True)
        qr.print_ascii(tty=True)
        print("\n等待扫码... (Ctrl+C 取消)\n")

        # 3. 轮询扫码状态（减少轮询间隔，加快响应）
        query_body = json.dumps({"app_id": 4, "device": self.device_id, "ticket": ticket})
        while True:
            time.sleep(1.5)  # 从 2 秒减少到 1.5 秒
            resp = self.session.post(
                URL_QR_QUERY,
                data=query_body,
                headers=app_headers(self.device_id),
                timeout=10,
            )
            result = resp.json()

            if result.get("retcode") != 0:
                print("二维码已过期，请重试")
                return False

            stat = result["data"]["stat"]
            if stat == "Scanned":
                print("已扫码，请在 App 上点击「确认登录」...")
            elif stat == "Confirmed":
                return self._handle_qr_confirmed(result["data"])
            elif stat == "Expired":
                print("二维码已过期，请重试")
                return False

    def _handle_qr_confirmed(self, qr_data: dict) -> bool:
        """处理扫码确认后的数据，换取 stoken"""
        try:
            raw = unquote(qr_data.get("payload", {}).get("raw", ""))
            payload = json.loads(raw)
        except Exception as e:
            print(f"解析扫码数据失败: {e}")
            return False

        # 打印完整的 payload
        log(f"[DEBUG] 完整 payload: {json.dumps(payload, ensure_ascii=False)}")

        uid        = str(payload["uid"])
        game_token = payload["token"]
        mid        = payload.get("mid", "")

        log(f"[DEBUG] 扫码成功 uid={uid}, mid={mid}")
        log(f"[DEBUG] game_token: {game_token[:20]}...")
        log(f"[DEBUG] game_token 完整值: {game_token}")

        # 保存 game_token
        self.game_token = game_token
        self.uid = uid
        self.mid = mid
        self.nickname = ""

        # *** 关键：立即用 game_token 换取 stoken，不要等 ***
        # game_token 有效期极短，必须立即使用
        log(f"[DEBUG] 立即尝试用 game_token 换取 stoken（game_token 有效期极短）...")

        stoken_success = False
        data = None

        # 方式1: 标准 JSON 格式（account_id 必须是数字类型）
        body1 = {"account_id": int(uid), "game_token": game_token}
        headers1 = app_headers(self.device_id)

        log(f"[DEBUG] 请求URL: {URL_GET_STOKEN_BY_GAME_TOKEN}")
        log(f"[DEBUG] 请求body: {body1}")
        log(f"[DEBUG] 请求headers: {headers1}")

        resp1 = self.session.post(URL_GET_STOKEN_BY_GAME_TOKEN, json=body1, headers=headers1, timeout=10)
        log(f"[DEBUG] getTokenByGameToken 方式1 响应: {resp1.text[:500]}")
        data1 = resp1.json()

        if data1.get("retcode") == 0:
            data = data1
            stoken_success = True
            log(f"[DEBUG] 方式1 成功！")
        else:
            # 方式2: 尝试 urlencoded 格式
            headers2 = app_headers(self.device_id)
            headers2["Content-Type"] = "application/x-www-form-urlencoded"
            body_str = f"account_id={uid}&game_token={game_token}"
            resp2 = self.session.post(URL_GET_STOKEN_BY_GAME_TOKEN, data=body_str, headers=headers2, timeout=10)
            log(f"[DEBUG] getTokenByGameToken 方式2 响应: {resp2.text[:500]}")
            data2 = resp2.json()

            if data2.get("retcode") == 0:
                data = data2
                stoken_success = True
                log(f"[DEBUG] 方式2 成功！")

        if stoken_success:
            self.mid     = data["data"]["user_info"].get("mid", mid)
            self.stoken  = data["data"]["token"]["token"]   # 可能是 v1 或 v2
            self.nickname = data["data"]["user_info"].get("nickname", "")
            log(f"[DEBUG] stoken 获取成功: {self.stoken[:20]}...")
            log(f"[DEBUG] stoken 类型: {'v2' if self.stoken.startswith('v2_') else 'v1'}")
            log(f"[DEBUG] mid 值: {self.mid}")

            # 立即尝试用 stoken 换取 cookie_token（用于 getUserGameRolesByCookie）
            log(f"[DEBUG] 尝试换取 cookie_token...")
            if self.fetch_cookie_token():
                log(f"[DEBUG] cookie_token 换取成功！")

                # 保存登录数据到文件（方便后续测试）
                try:
                    login_data = {
                        "uid": self.uid,
                        "mid": self.mid,
                        "nickname": self.nickname,
                        "stoken": self.stoken,
                        "cookie_token": self.cookie_token,
                        "device_id": self.device_id,
                        "save_time": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    with open("login_data.json", "w", encoding="utf-8") as f:
                        json.dump(login_data, f, ensure_ascii=False, indent=2)
                    log(f"[DEBUG] 登录数据已保存到 login_data.json")
                except Exception as e:
                    log(f"[WARNING] 保存登录数据失败: {e}")
            else:
                log(f"[DEBUG] cookie_token 换取失败，继续尝试 ltoken_v2...")

            # 尝试换取 ltoken_v2（备用方案）
            if self.stoken.startswith("v2_"):
                log(f"[DEBUG] stoken 是 v2 格式，尝试换取 ltoken_v2...")
                if not self.mid:
                    log(f"[WARNING] mid 为空，无法换取 ltoken_v2")
                else:
                    if self.fetch_ltoken():
                        log(f"[DEBUG] ltoken_v2 换取成功！")
            else:
                log(f"[DEBUG] stoken 是 v1 格式")
        else:
            log(f"[DEBUG] stoken 换取失败（所有方式都失败）")
            log(f"[DEBUG] 最后一次错误: {data1.get('message') if not data else data.get('message')}")
            log(f"[DEBUG] game_token 可能已过期或账号状态异常")
            log(f"[DEBUG] 完整错误响应: {resp1.text}")

        print(f"\n✓ 登录成功！欢迎 {self.nickname or uid}")
        return True

    # ── v2 stoken → ltoken_v2 ───────────────────

    def fetch_ltoken(self) -> bool:
        """
        用 v2 stoken 换取 ltoken_v2。

        关键点：
          - 请求方法：GET（不是 POST！）
          - 请求头必须有 x-rpc-app_id
          - Cookie: stoken=v2_xxx; stuid=uid; mid=xxx
          - 无请求体
        """
        if not self.stoken.startswith("v2_"):
            log("[DEBUG] stoken 不是 v2 格式，跳过 ltoken_v2 换取")
            return False

        # v2 stoken 必须有 mid，否则会返回 -100
        if not self.mid:
            log("[WARNING] v2 stoken 缺少 mid 参数，无法换取 ltoken_v2")
            return False

        cookie = f"stoken={self.stoken};stuid={self.uid};mid={self.mid}"

        log(f"[DEBUG] fetch_ltoken Cookie: {cookie[:60]}...")
        log(f"[DEBUG] fetch_ltoken URL: {URL_GET_LTOKEN_BY_STOKEN}")

        resp = self.session.get(
            URL_GET_LTOKEN_BY_STOKEN,
            headers=app_headers(self.device_id, cookie),
            timeout=10,
        )
        log(f"[DEBUG] fetch_ltoken 响应: {resp.text[:500]}")

        if resp.status_code != 200:
            log(f"[DEBUG] fetch_ltoken 请求失败，状态码: {resp.status_code}")
            return False

        data = resp.json()

        if data.get("retcode") != 0:
            retcode = data.get("retcode")
            msg = data.get("message", "")
            log(f"[DEBUG] fetch_ltoken 失败: retcode={retcode}, msg={msg}")
            return False

        # 响应格式：{"retcode": 0, "data": {"ltoken": "xxx"}}
        self.ltoken_v2 = data["data"]["ltoken"]
        self.ltuid_v2  = self.uid

        log(f"[DEBUG] ltoken_v2 获取成功: {self.ltoken_v2[:20]}...")
        return True

    def fetch_cookie_token(self) -> bool:
        """
        用 stoken 换取 cookie_token。
        这是调用 getUserGameRolesByCookie 接口的必要凭证。

        关键点：
          - 请求方法：GET
          - 请求头必须有 x-rpc-app_id
          - Cookie: stoken=v2_xxx; stuid=uid; mid=xxx
        """
        if not self.stoken:
            log("[WARNING] 没有 stoken，无法换取 cookie_token")
            return False

        cookie = f"stoken={self.stoken};stuid={self.uid}"
        if self.mid:
            cookie += f";mid={self.mid}"

        log(f"[DEBUG] fetch_cookie_token Cookie: {cookie[:60]}...")

        resp = self.session.get(
            URL_GET_COOKIE_TOKEN,
            headers=app_headers(self.device_id, cookie),
            timeout=10,
        )
        log(f"[DEBUG] fetch_cookie_token 响应: {resp.text[:500]}")

        if resp.status_code != 200:
            log(f"[DEBUG] fetch_cookie_token 请求失败，状态码: {resp.status_code}")
            return False

        data = resp.json()

        if data.get("retcode") != 0:
            retcode = data.get("retcode")
            msg = data.get("message", "")
            log(f"[DEBUG] fetch_cookie_token 失败: retcode={retcode}, msg={msg}")
            return False

        # 响应格式：{"retcode": 0, "data": {"uid": "xxx", "cookie_token": "xxx"}}
        self.cookie_token = data["data"]["cookie_token"]

        log(f"[DEBUG] cookie_token 获取成功: {self.cookie_token[:20]}...")
        return True

    # ── 构建各接口所需的 Cookie ──────────────────

    def roles_cookie(self, use_stoken: bool = False) -> str:
        """
        获取游戏角色所需的 Cookie

        Args:
            use_stoken: True=使用 stoken（用于 getUserGameRolesByStoken）
                       False=使用 cookie_token（用于 getUserGameRolesByCookie，默认）
        """
        if not use_stoken and self.cookie_token:
            # *** 关键：getUserGameRolesByCookie 需要 cookie_token + account_id ***
            cookie = f"cookie_token={self.cookie_token};account_id={self.uid}"
            return cookie

        if use_stoken and self.stoken and self.stoken.startswith("v2_"):
            # v2 stoken（用于 getUserGameRolesByStoken）
            cookie = f"stoken={self.stoken};stuid={self.uid}"
            if self.mid:
                cookie += f";mid={self.mid}"
            return cookie

        # 备用方案
        if self.cookie_token:
            cookie = f"cookie_token={self.cookie_token};account_id={self.uid}"
            return cookie

        return ""

    def sign_cookie(self) -> str:
        """签到接口所需的 Cookie（同游戏角色）"""
        return self.roles_cookie()


# ──────────────────────────────────────────────
# 签到逻辑
# ──────────────────────────────────────────────

class Signer:

    def __init__(self, account: Account):
        self.acc = account
        self.s   = account.session
        self.did = account.device_id

    def get_roles(self, game_biz: str) -> List[dict]:
        """获取该游戏绑定的角色列表"""
        # *** 关键修复：getUserGameRolesByCookie 需要使用 cookie_token ***

        if self.acc.cookie_token:
            url = f"{URL_GAME_ROLES_BY_COOKIE}?game_biz={game_biz}"
            cookie = self.acc.roles_cookie(use_stoken=False)
            headers = bbs_headers(self.did, cookie)
            headers["DS"] = ds_gen("", f"game_biz={game_biz}")

            log(f"[DEBUG] 使用 getUserGameRolesByCookie 获取角色...")
            log(f"[DEBUG] cookie_token: {self.acc.cookie_token[:20]}...")
            log(f"[DEBUG] Cookie: {cookie[:80]}...")

            resp = self.s.get(url, headers=headers, timeout=10)
            log(f"[DEBUG] 响应: {resp.text[:300]}")
            data = resp.json()

            if data.get("retcode") == 0:
                log(f"[DEBUG] get_roles 成功！")
                return [
                    {
                        "nickname": item.get("nickname", ""),
                        "game_uid": item.get("game_uid", ""),
                        "region":   item.get("region", ""),
                    }
                    for item in data.get("data", {}).get("list", [])
                ]
            else:
                log(f"[DEBUG] getUserGameRolesByCookie 失败: {data.get('message')}")

        log(f"[DEBUG] 没有可用的凭证，无法获取角色")
        return []

    def is_signed(self, game_biz: str, act_id: str, info_url: str,
                  region: str, uid: str) -> bool:
        """检查今日是否已签到"""
        query   = f"act_id={act_id}&region={region}&uid={uid}"
        url     = f"{info_url}?lang=zh-cn&{query}"

        cookie  = self.acc.sign_cookie()

        # 根据游戏 biz 添加 signgame 参数
        signgame = ""
        if game_biz == "hk4e_cn":
            signgame = "hk4e"
        elif game_biz == "nap_cn":
            signgame = "zzz"

        headers = bbs_headers(self.did, cookie, signgame)
        headers["DS"] = ds_gen("", query)

        resp = self.s.get(url, headers=headers, timeout=10)
        log(f"[DEBUG] is_signed 响应: {resp.text[:200]}")
        data = resp.json()

        if data.get("retcode") == 0 and data.get("data"):
            return data["data"].get("is_sign", False)
        return False

    def do_sign(self, game_biz: str, act_id: str, sign_url: str,
                region: str, uid: str) -> dict:
        """执行签到"""
        body_dict = {"act_id": act_id, "region": region, "uid": uid}
        body      = json.dumps(body_dict)

        cookie    = self.acc.sign_cookie()

        # 根据游戏 biz 添加 signgame 参数
        signgame = ""
        if game_biz == "hk4e_cn":
            signgame = "hk4e"
        elif game_biz == "nap_cn":
            signgame = "zzz"

        headers   = bbs_headers(self.did, cookie, signgame)
        headers["Content-Type"] = "application/json"
        headers["DS"] = ds_gen(body, "")

        log(f"[DEBUG] do_sign body: {body}")
        resp = self.s.post(sign_url, data=body, headers=headers, timeout=10)
        log(f"[DEBUG] do_sign 响应: {resp.text[:200]}")
        return resp.json()

    def run(self) -> List[dict]:
        """
        完整签到流程：
        1. 检查是否有可用的凭证（game_token 或 ltoken_v2）
        2. 遍历所有游戏，查询绑定角色
        3. 对每个角色执行签到
        """
        results = []

        # ── Step 1: 显示认证状态 ──
        print("\n[认证] 检查登录凭证...")
        if self.acc.game_token:
            print("[认证] ✓ game_token 可用（优先使用）")
        elif self.acc.ltoken_v2:
            print("[认证] ✓ ltoken_v2 可用")
        elif self.acc.stoken:
            print("[认证] ⚠ 仅 stoken 可用（可能不稳定）")
        else:
            print("[认证] ✗ 无可用凭证")
            return [{"game": "全部", "status": "auth_failed"}]

        # ── Step 2 & 3: 逐游戏签到 ──
        for game_biz, (name, act_id, info_url, sign_url) in GAMES.items():
            print(f"\n── {name} ──")

            roles = self.get_roles(game_biz)
            if not roles:
                print(f"  未绑定 {name} 账号，跳过")
                results.append({"game": name, "status": "no_account"})
                continue

            for role in roles:
                nickname = role["nickname"] or "未知"
                uid      = role["game_uid"]
                region   = role["region"]
                print(f"  角色: {nickname}  UID: {uid}")

                try:
                    if self.is_signed(game_biz, act_id, info_url, region, uid):
                        print(f"  → 今日已签到 ✓")
                        results.append({"game": name, "nickname": nickname,
                                        "status": "already_signed"})
                        continue

                    res = self.do_sign(game_biz, act_id, sign_url, region, uid)
                    if res.get("retcode") == 0:
                        print(f"  → 签到成功 ✓")
                        results.append({"game": name, "nickname": nickname, "status": "success"})
                    else:
                        msg = res.get("message", "未知错误")
                        print(f"  → 签到失败: {msg}")
                        results.append({"game": name, "nickname": nickname,
                                        "status": "failed", "msg": msg})
                except Exception as e:
                    print(f"  → 异常: {e}")
                    results.append({"game": name, "nickname": nickname,
                                    "status": "error", "msg": str(e)})

        return results


# ──────────────────────────────────────────────
# 主程序：扫码 → 签到
# ──────────────────────────────────────────────

def main():
    print("=" * 50)
    print("   米游社自动签到工具")
    print("=" * 50)

    acc = Account()

    # 扫码登录
    try:
        if not acc.qrcode_login():
            print("\n登录失败，程序退出")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(0)

    # 执行签到
    print("\n" + "=" * 50)
    print("开始签到...")
    print("=" * 50)

    signer  = Signer(acc)
    results = signer.run()

    # 打印汇总
    print("\n" + "=" * 50)
    print("签到汇总")
    print("=" * 50)
    status_label = {
        "success":        "✓ 签到成功",
        "already_signed": "✓ 今日已签",
        "failed":         "✗ 签到失败",
        "error":          "✗ 发生错误",
        "no_account":     "— 未绑定账号",
        "auth_failed":    "✗ 认证失败，请重新扫码",
    }
    for r in results:
        label = status_label.get(r["status"], r["status"])
        extra = f"  ({r.get('msg', '')})" if r.get("msg") else ""
        print(f"  {r['game']}: {label}{extra}")

    print("\n完成！")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="米游社自动签到工具 v5.0")
    parser.add_argument("--gui", action="store_true", help="启动图形界面（默认）")
    parser.add_argument("--cli", action="store_true", help="命令行模式（扫码签到）")
    parser.add_argument("--sign-all", action="store_true", help="对所有已保存的账号执行签到")
    args = parser.parse_args()

    if args.cli or (not args.gui and args.sign_all):
        # 命令行模式
        if args.sign_all:
            from mys_signer import AccountManager, sign_all_accounts, set_log_callback
            manager = AccountManager()
            if not manager.accounts:
                print("没有已保存的账号，请先通过 --gui 或扫码登录添加账号")
                sys.exit(1)
            print(f"共 {len(manager.accounts)} 个账号，开始签到...")
            results = sign_all_accounts(manager)
            for uid, res_list in results.items():
                acc = manager.get_account(uid)
                name = acc.nickname or uid
                for r in res_list:
                    label = {"success": "签到成功", "already_signed": "已签到",
                             "failed": "签到失败", "no_account": "未绑定"}.get(r["status"], r["status"])
                    print(f"  [{name}] {r['game']}: {label}")
        else:
            main()
    else:
        # 启动 GUI
        from mys_gui import main as gui_main
        gui_main()

