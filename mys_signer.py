#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
米游社签到核心模块
- 账号管理（多账号持久化）
- 签到逻辑
- 凭证刷新
"""

import json
import time
import hashlib
import random
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from typing import List, Dict, Optional, Callable

import requests
import qrcode

# ──────────────────────────────────────────────
# 数据目录
# ──────────────────────────────────────────────

# PyInstaller 打包后，__file__ 指向临时目录，数据应保存在 exe 所在目录
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent

DATA_DIR = _BASE_DIR / "data"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"

# 确保数据目录存在
DATA_DIR.mkdir(exist_ok=True)


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def gen_device_id() -> str:
    h = ''.join(random.choices('0123456789abcdef', k=32))
    return f"{h[:8]}-{h[8:12]}-4{h[12:16]}-{h[16:20]}-{h[20:]}"


# DS 签名 salt（米游社 2.11.1 版本）
SALT_BBS = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"

def ds_gen(body: str = "", query: str = "") -> str:
    t = str(int(time.time()))
    r = str(random.randint(100001, 200000))
    raw = f"salt={SALT_BBS}&t={t}&r={r}&b={body}&q={query}"
    return f"{t},{r},{md5(raw)}"


# ──────────────────────────────────────────────
# 请求头工厂
# ──────────────────────────────────────────────

APP_ID  = "bll8iq97cem8"
APP_VER = "2.67.1"
BBS_VER = "2.11.1"


def app_headers(device_id: str, cookie: str = "") -> dict:
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
    h = {
        "Accept":            "application/json, text/plain, */*",
        "Accept-Language":   "zh-CN,en-US;q=0.8",
        "Accept-Encoding":   "gzip, deflate",
        "x-rpc-app_id":     APP_ID,
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

URL_QR_FETCH  = "https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/fetch"
URL_QR_QUERY  = "https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/query"

URL_GET_STOKEN_BY_GAME_TOKEN = "https://api-takumi.mihoyo.com/account/ma-cn-session/app/getTokenByGameToken"
URL_GET_LTOKEN_BY_STOKEN     = "https://passport-api.mihoyo.com/account/auth/api/getLTokenBySToken"
URL_GET_COOKIE_TOKEN          = "https://api-takumi.mihoyo.com/auth/api/getCookieAccountInfoBySToken"

# 手机号验证码登录（参考 MHY_Scanner 项目接口）
URL_CREATE_LOGIN_CAPTCHA = "https://passport-api.mihoyo.com/account/ma-cn-verifier/verifier/createLoginCaptcha"
URL_LOGIN_BY_MOBILE_CAPTCHA = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/loginByMobileCaptcha"

URL_GAME_ROLES_BY_COOKIE = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"

# 签到接口
URL_SIGN_INFO = "https://api-takumi.mihoyo.com/event/luna/info"
URL_SIGN_DO   = "https://api-takumi.mihoyo.com/event/luna/sign"
URL_YS_INFO   = "https://act-nap-api.mihoyo.com/event/luna/hk4e/info"
URL_YS_SIGN   = "https://act-nap-api.mihoyo.com/event/luna/hk4e/sign"
URL_ZZZ_INFO  = "https://act-nap-api.mihoyo.com/event/luna/zzz/info"
URL_ZZZ_SIGN  = "https://act-nap-api.mihoyo.com/event/luna/zzz/sign"

# 游戏列表
GAMES = {
    "bh2_cn":   ("崩坏学园2",      "e202203291431091", URL_SIGN_INFO, URL_SIGN_DO),
    "bh3_cn":   ("崩坏3",          "e202306201626331", URL_SIGN_INFO, URL_SIGN_DO),
    "nxx_cn":   ("未定事件簿",     "e202202251749321", URL_SIGN_INFO, URL_SIGN_DO),
    "hk4e_cn":  ("原神",           "e202311201442471", URL_YS_INFO,   URL_YS_SIGN),
    "hkrpg_cn": ("崩坏：星穹铁道", "e202304121516551", URL_SIGN_INFO, URL_SIGN_DO),
    "nap_cn":   ("绝区零",         "e202406242138391", URL_ZZZ_INFO,  URL_ZZZ_SIGN),
}


# ──────────────────────────────────────────────
# 日志回调
# ──────────────────────────────────────────────

_log_callback: Optional[Callable[[str], None]] = None

def set_log_callback(cb: Callable[[str], None]):
    global _log_callback
    _log_callback = cb

def log(msg: str):
    print(msg, flush=True)
    if _log_callback:
        try:
            _log_callback(msg)
        except Exception:
            pass


# ──────────────────────────────────────────────
# 账号数据模型
# ──────────────────────────────────────────────

class AccountData:
    """一个已登录账号的持久化数据"""

    def __init__(self, uid: str = "", nickname: str = "", mid: str = "",
                 stoken: str = "", cookie_token: str = "",
                 ltoken_v2: str = "", device_id: str = ""):
        self.uid = uid
        self.nickname = nickname
        self.mid = mid
        self.stoken = stoken
        self.cookie_token = cookie_token
        self.ltoken_v2 = ltoken_v2
        self.device_id = device_id or gen_device_id()
        self.session = requests.Session()

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "nickname": self.nickname,
            "mid": self.mid,
            "stoken": self.stoken,
            "cookie_token": self.cookie_token,
            "ltoken_v2": self.ltoken_v2,
            "device_id": self.device_id,
            "save_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AccountData":
        acc = cls()
        acc.uid = d.get("uid", "")
        acc.nickname = d.get("nickname", "")
        acc.mid = d.get("mid", "")
        acc.stoken = d.get("stoken", "")
        acc.cookie_token = d.get("cookie_token", "")
        acc.ltoken_v2 = d.get("ltoken_v2", "")
        acc.device_id = d.get("device_id", "") or gen_device_id()
        return acc

    def roles_cookie(self) -> str:
        if self.cookie_token:
            return f"cookie_token={self.cookie_token};account_id={self.uid}"
        return ""

    def sign_cookie(self) -> str:
        return self.roles_cookie()


# ──────────────────────────────────────────────
# 账号管理器（多账号持久化）
# ──────────────────────────────────────────────

class AccountManager:
    """管理多个账号的添加、删除、持久化"""

    def __init__(self):
        self.accounts: Dict[str, AccountData] = {}  # uid -> AccountData
        self._load()

    def _load(self):
        if ACCOUNTS_FILE.exists():
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for uid, acc_dict in data.get("accounts", {}).items():
                    self.accounts[uid] = AccountData.from_dict(acc_dict)
            except Exception as e:
                log(f"[WARNING] 加载账号数据失败: {e}")

    def _save(self):
        try:
            data = {"accounts": {uid: acc.to_dict() for uid, acc in self.accounts.items()}}
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log(f"[WARNING] 保存账号数据失败: {e}")

    def add_account(self, acc: AccountData):
        self.accounts[acc.uid] = acc
        self._save()
        log(f"[账号] 已添加账号: {acc.nickname or acc.uid}")

    def remove_account(self, uid: str):
        if uid in self.accounts:
            del self.accounts[uid]
            self._save()
            log(f"[账号] 已删除账号: {uid}")

    def get_account(self, uid: str) -> Optional[AccountData]:
        return self.accounts.get(uid)

    def list_accounts(self) -> List[AccountData]:
        return list(self.accounts.values())


# ──────────────────────────────────────────────
# 二维码登录
# ──────────────────────────────────────────────

def qrcode_login(device_id: str = None, log_cb: Callable = None) -> Optional[AccountData]:
    """
    扫码登录，返回 AccountData（登录成功后需手动添加到 AccountManager）
    log_cb: 可选的实时日志回调
    注意：app_id 必须为 2（未定事件簿），参考 MHY_Scanner 项目。
          使用 app_id=4（原神）获取的 game_token 在换取 stoken 时会返回"登录状态失效"。
    """
    if device_id is None:
        device_id = gen_device_id()

    session = requests.Session()
    # app_id=2 对应未定事件簿，与 MHY_Scanner 默认 loginType 一致
    qr_app_id = 2

    # 1. 获取二维码（参考 MHY_Scanner: 不设额外请求头，libcurl 默认无 Content-Type）
    body = json.dumps({"app_id": qr_app_id, "device": device_id})
    resp = session.post(URL_QR_FETCH, data=body, timeout=10)
    data = resp.json()
    if data.get("retcode") != 0:
        if log_cb:
            log_cb(f"获取二维码失败: {data.get('message')}")
        return None

    qr_url = data["data"]["url"]
    ticket = parse_qs(urlparse(qr_url).query).get("ticket", [None])[0]

    # 2. 生成二维码图片（返回 URL 给 GUI 显示）
    if log_cb:
        log_cb(f"QR_URL:{qr_url}")

    # 3. 轮询扫码状态
    query_body = json.dumps({"app_id": qr_app_id, "device": device_id, "ticket": ticket})
    while True:
        time.sleep(1.5)
        resp = session.post(URL_QR_QUERY, data=query_body, timeout=10)
        result = resp.json()

        if result.get("retcode") != 0:
            if log_cb:
                log_cb("二维码已过期，请重试")
            return None

        stat = result["data"]["stat"]
        if stat == "Scanned":
            if log_cb:
                log_cb("已扫码，请在 App 上点击「确认登录」...")
        elif stat == "Confirmed":
            return _handle_confirmed(session, device_id, result["data"], log_cb)
        elif stat == "Expired":
            if log_cb:
                log_cb("二维码已过期，请重试")
            return None


def _handle_confirmed(session, device_id: str, qr_data: dict,
                       log_cb: Callable = None) -> Optional[AccountData]:
    """处理扫码确认，换取凭证"""
    def _log(msg):
        log(msg)
        if log_cb:
            log_cb(msg)

    try:
        raw = unquote(qr_data.get("payload", {}).get("raw", ""))
        payload = json.loads(raw)
    except Exception as e:
        _log(f"解析扫码数据失败: {e}")
        return None

    uid = str(payload["uid"])
    game_token = payload["token"]
    mid = payload.get("mid", "")

    _log(f"[DEBUG] 扫码成功 uid={uid}, mid={mid}")

    # 用 game_token 换取 stoken
    # 参考 MHY_Scanner 项目，请求头必须精简，否则会失败
    acc = AccountData(uid=uid, mid=mid, device_id=device_id)

    body1 = {"account_id": int(uid), "game_token": game_token}
    # 精简请求头——只发送必要字段，与 MHY_Scanner 保持一致
    headers1 = {
        "x-rpc-app_id": APP_ID,
        "Referer": "https://app.mihoyo.com",
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; LIO-AN00 Build/TKQ1.220829.002; wv) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/103.0.5060.129 "
                       "Mobile Safari/537.36 miHoYoBBS/2.67.1",
    }
    resp1 = session.post(URL_GET_STOKEN_BY_GAME_TOKEN, json=body1,
                         headers=headers1, timeout=10)
    data1 = resp1.json()

    data = None
    if data1.get("retcode") == 0:
        data = data1
    else:
        _log(f"[DEBUG] stoken 换取失败: {data1.get('message', data1.get('retcode'))}")

    if not data:
        _log(f"[ERROR] stoken 换取失败，请尝试使用手机号登录")
        return None

    acc.mid = data["data"]["user_info"].get("mid", mid)
    acc.stoken = data["data"]["token"]["token"]
    acc.nickname = data["data"]["user_info"].get("nickname", "")

    # 换取 cookie_token
    if _fetch_cookie_token(acc, session):
        _log(f"[DEBUG] cookie_token 获取成功")

    # 换取 ltoken_v2
    if acc.stoken.startswith("v2_") and acc.mid:
        _fetch_ltoken(acc, session)

    _log(f"[OK] 登录成功！{acc.nickname or acc.uid}")
    return acc


def _fetch_cookie_token(acc: AccountData, session: requests.Session) -> bool:
    cookie = f"stoken={acc.stoken};stuid={acc.uid}"
    if acc.mid:
        cookie += f";mid={acc.mid}"

    resp = session.get(URL_GET_COOKIE_TOKEN, headers=app_headers(acc.device_id, cookie), timeout=10)
    data = resp.json()
    if data.get("retcode") == 0:
        acc.cookie_token = data["data"]["cookie_token"]
        return True
    return False


def _fetch_ltoken(acc: AccountData, session: requests.Session) -> bool:
    cookie = f"stoken={acc.stoken};stuid={acc.uid};mid={acc.mid}"
    resp = session.get(URL_GET_LTOKEN_BY_STOKEN, headers=app_headers(acc.device_id, cookie), timeout=10)
    data = resp.json()
    if data.get("retcode") == 0:
        acc.ltoken_v2 = data["data"]["ltoken"]
        return True
    return False


# ──────────────────────────────────────────────
# 手机号验证码登录
# ──────────────────────────────────────────────

RSA_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDDvekdPMHN3AYhm/vktJT+YJr7"
    "cI5DcsNKqdsx5DZX0gDuWFuIjzdwButrIYPNmRJ1G8ybDIF7oDW2eEpm5sMbL9zs"
    "9ExXCdvqrn51qELbqj0XxtMTIpaCHFSI50PfPpTFV9Xt/hmyVwokoOXFlAEgCn+Q"
    "CgGs52bFoYMtyi+xEQIDAQAB\n"
    "-----END PUBLIC KEY-----"
)


def _rsa_encrypt(text: str) -> str:
    """RSA 加密（参考 MHY_Scanner 的 CryptoKit）"""
    try:
        from Crypto.PublicKey import RSA
        from Crypto.Cipher import PKCS1_v1_5
        import base64
        key = RSA.import_key(RSA_PUBLIC_KEY)
        cipher = PKCS1_v1_5.new(key)
        encrypted = cipher.encrypt(text.encode('utf-8'))
        return base64.b64encode(encrypted).decode('utf-8')
    except ImportError:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend
            import base64
            key = load_pem_public_key(RSA_PUBLIC_KEY.encode(), backend=default_backend())
            encrypted = key.encrypt(text.encode('utf-8'), padding.PKCS1v15())
            return base64.b64encode(encrypted).decode('utf-8')
        except ImportError:
            return ""


def send_sms_code(phone: str, device_id: str = None, log_cb: Callable = None) -> tuple:
    """
    发送短信验证码。
    返回 (success: bool, action_type: str)
    如果需要极验验证则 action_type 为空，需要用户完成极验后重新调用。
    """
    def _log(msg):
        log(msg)
        if log_cb:
            log_cb(msg)

    if device_id is None:
        device_id = gen_device_id()

    session = requests.Session()

    # 参考 MHY_Scanner 的 CreateLoginCaptcha
    # 手机号需要 RSA 加密
    encrypted_phone = _rsa_encrypt(phone)
    if not encrypted_phone:
        _log("[ERROR] 缺少加密库，请安装 pycryptodome: pip install pycryptodome")
        return False, ""

    try:
        body = json.dumps({
            "area_code": _rsa_encrypt("+86"),
            "mobile": encrypted_phone
        })

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-rpc-app_id": APP_ID,
            "x-rpc-app_version": "2.76.1",
            "x-rpc-client_type": "2",
            "x-rpc-device_id": device_id,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) miHoYoBBS/2.76.1",
        }

        # DS 签名
        headers["DS"] = ds_gen(body, "")

        resp = session.post(
            URL_CREATE_LOGIN_CAPTCHA,
            data=body, headers=headers, timeout=10
        )

        retcode = resp.json().get("retcode", -1)
        resp_data = resp.json()

        if retcode == 0:
            # 不需要极验验证，直接发送成功
            action_type = resp_data.get("data", {}).get("action_type", "")
            _log("[OK] 验证码已发送")
            return True, action_type
        elif retcode == -3006:
            _log("[ERROR] 请求过于频繁，请稍后再试")
            return False, ""
        elif retcode == -3008:
            _log("[ERROR] 手机号格式错误")
            return False, ""
        else:
            # 可能需要极验验证（retcode == -3101），暂时返回错误
            msg = resp_data.get("message", f"错误码 {retcode}")
            _log(f"[ERROR] 发送验证码失败: {msg}")
            return False, ""
    except Exception as e:
        _log(f"[ERROR] 发送验证码异常: {e}")
        return False, ""


def phone_login(phone: str, code: str, action_type: str = "login",
                device_id: str = None,
                log_cb: Callable = None) -> Optional[AccountData]:
    """手机号+验证码登录，返回 AccountData"""
    def _log(msg):
        log(msg)
        if log_cb:
            log_cb(msg)

    if device_id is None:
        device_id = gen_device_id()

    session = requests.Session()

    try:
        encrypted_phone = _rsa_encrypt(phone)
        encrypted_area = _rsa_encrypt("+86")

        if not encrypted_phone:
            _log("[ERROR] 缺少加密库")
            return None

        body = json.dumps({
            "area_code": encrypted_area,
            "action_type": action_type,
            "captcha": code,
            "mobile": encrypted_phone
        })

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-rpc-app_id": APP_ID,
            "x-rpc-app_version": "2.76.1",
            "x-rpc-client_type": "2",
            "x-rpc-device_id": device_id,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) miHoYoBBS/2.76.1",
        }
        headers["DS"] = ds_gen(body, "")

        resp = session.post(
            URL_LOGIN_BY_MOBILE_CAPTCHA,
            data=body, headers=headers, timeout=10
        )
        data = resp.json()

        if data.get("retcode") == -3205:
            _log("[ERROR] 验证码错误")
            return None
        elif data.get("retcode") != 0:
            msg = data.get("message", f"错误码 {data.get('retcode')}")
            _log(f"[ERROR] 登录失败: {msg}")
            return None

        # 提取凭证
        stoken = data["data"]["token"]["token"]
        uid = str(data["data"]["user_info"].get("aid", ""))
        mid = data["data"]["user_info"].get("mid", "")

        _log(f"[DEBUG] 手机登录成功 uid={uid}, mid={mid}")

        acc = AccountData(uid=uid, mid=mid, device_id=device_id, stoken=stoken)

        # 获取昵称
        try:
            nickname_resp = session.get(
                f"https://bbs-api.miyoushe.com/user/api/getUserFullInfo?uid={uid}",
                headers={
                    "x-rpc-app_id": APP_ID,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) miHoYoBBS/2.76.1",
                },
                timeout=10
            )
            nickname_data = nickname_resp.json()
            if nickname_data.get("retcode") == 0:
                acc.nickname = nickname_data["data"]["user_info"].get("nickname", "")
        except Exception:
            pass

        # 换取 cookie_token
        if _fetch_cookie_token(acc, session):
            _log("[DEBUG] cookie_token 获取成功")

        # 换取 ltoken_v2
        if acc.stoken.startswith("v2_") and acc.mid:
            _fetch_ltoken(acc, session)

        _log(f"[OK] 登录成功！{acc.nickname or acc.uid}")
        return acc

    except Exception as e:
        _log(f"[ERROR] 手机登录异常: {e}")
        return None


# ──────────────────────────────────────────────
# 凭证刷新（签到前调用，确保 cookie_token 有效）
# ──────────────────────────────────────────────

def refresh_credentials(acc: AccountData) -> bool:
    """用 stoken 刷新 cookie_token，如果失败返回 False"""
    if not acc.stoken:
        return bool(acc.cookie_token)

    session = requests.Session()
    if _fetch_cookie_token(acc, session):
        if acc.stoken.startswith("v2_") and acc.mid:
            _fetch_ltoken(acc, session)
        # 补充获取昵称（如果为空）
        if not acc.nickname:
            _fetch_nickname(acc, session)
        return True

    return bool(acc.cookie_token)


def _fetch_nickname(acc: AccountData, session: requests.Session) -> bool:
    """通过用户信息接口获取昵称"""
    URL_USER_INFO = "https://bbs-api.miyoushe.com/user/api/getUserFullInfo"
    cookie = f"stoken={acc.stoken};stuid={acc.uid}"
    if acc.mid:
        cookie += f";mid={acc.mid}"

    try:
        resp = session.get(URL_USER_INFO, headers=app_headers(acc.device_id, cookie), timeout=10)
        data = resp.json()
        if data.get("retcode") == 0:
            info = data.get("data", {}).get("user_info", {})
            nickname = info.get("nickname", "")
            if nickname:
                acc.nickname = nickname
                return True
    except Exception:
        pass
    return False


# ──────────────────────────────────────────────
# 签到逻辑
# ──────────────────────────────────────────────

def get_signgame(game_biz: str) -> str:
    if game_biz == "hk4e_cn":
        return "hk4e"
    elif game_biz == "nap_cn":
        return "zzz"
    return ""


def get_roles(acc: AccountData, game_biz: str) -> List[dict]:
    """获取游戏绑定的角色列表"""
    if not acc.cookie_token:
        log("[WARNING] 无 cookie_token，无法获取角色")
        return []

    url = f"{URL_GAME_ROLES_BY_COOKIE}?game_biz={game_biz}"
    cookie = acc.roles_cookie()
    headers = bbs_headers(acc.device_id, cookie)
    headers["DS"] = ds_gen("", f"game_biz={game_biz}")

    try:
        resp = acc.session.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("retcode") == 0:
            return [
                {"nickname": item.get("nickname", ""), "game_uid": item.get("game_uid", ""),
                 "region": item.get("region", "")}
                for item in data.get("data", {}).get("list", [])
            ]
        else:
            log(f"[DEBUG] get_roles 失败: {data.get('message')}")
    except Exception as e:
        log(f"[ERROR] get_roles 异常: {e}")
    return []


def is_signed(acc: AccountData, game_biz: str, act_id: str, info_url: str,
              region: str, uid: str) -> bool:
    """检查今日是否已签到"""
    query = f"act_id={act_id}&region={region}&uid={uid}"
    url = f"{info_url}?lang=zh-cn&{query}"
    cookie = acc.sign_cookie()
    signgame = get_signgame(game_biz)

    headers = bbs_headers(acc.device_id, cookie, signgame)
    headers["DS"] = ds_gen("", query)

    try:
        resp = acc.session.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("retcode") == 0 and data.get("data"):
            return data["data"].get("is_sign", False)
    except Exception as e:
        log(f"[ERROR] is_signed 异常: {e}")
    return False


def do_sign(acc: AccountData, game_biz: str, act_id: str, sign_url: str,
            region: str, uid: str) -> dict:
    """执行签到"""
    body = json.dumps({"act_id": act_id, "region": region, "uid": uid})
    cookie = acc.sign_cookie()
    signgame = get_signgame(game_biz)

    headers = bbs_headers(acc.device_id, cookie, signgame)
    headers["Content-Type"] = "application/json"
    headers["DS"] = ds_gen(body, "")

    try:
        resp = acc.session.post(sign_url, data=body, headers=headers, timeout=10)
        return resp.json()
    except Exception as e:
        return {"retcode": -1, "message": str(e)}


def sign_account(acc: AccountData) -> List[dict]:
    """对一个账号执行所有游戏的签到"""
    results = []
    nickname_label = acc.nickname or acc.uid

    # 先刷新凭证
    log(f"[认证] 刷新 {nickname_label} 的凭证...")
    if not refresh_credentials(acc):
        log(f"[WARNING] {nickname_label} 凭证刷新失败，尝试用旧凭证签到")

    for game_biz, (name, act_id, info_url, sign_url) in GAMES.items():
        roles = get_roles(acc, game_biz)
        if not roles:
            results.append({"game": name, "status": "no_account"})
            continue

        for role in roles:
            rn = role["nickname"] or "未知"
            ruid = role["game_uid"]
            rregion = role["region"]
            log(f"[{nickname_label}] {name} - {rn}({ruid})")

            try:
                if is_signed(acc, game_biz, act_id, info_url, rregion, ruid):
                    log(f"[{nickname_label}] {name} - {rn} → 今日已签到")
                    results.append({"game": name, "nickname": rn, "status": "already_signed"})
                    continue

                res = do_sign(acc, game_biz, act_id, sign_url, rregion, ruid)
                if res.get("retcode") == 0:
                    log(f"[{nickname_label}] {name} - {rn} → 签到成功")
                    results.append({"game": name, "nickname": rn, "status": "success"})
                else:
                    msg = res.get("message", "未知错误")
                    log(f"[{nickname_label}] {name} - {rn} → 签到失败: {msg}")
                    results.append({"game": name, "nickname": rn, "status": "failed", "msg": msg})
            except Exception as e:
                log(f"[{nickname_label}] {name} - {rn} → 异常: {e}")
                results.append({"game": name, "nickname": rn, "status": "error", "msg": str(e)})

    return results


def sign_all_accounts(manager: AccountManager) -> Dict[str, List[dict]]:
    """对所有已保存的账号执行签到"""
    all_results = {}
    for uid, acc in manager.accounts.items():
        log(f"\n{'='*40}")
        log(f"开始签到: {acc.nickname or acc.uid}")
        log(f"{'='*40}")
        all_results[uid] = sign_account(acc)
    return all_results


def query_sign_detail(acc: AccountData, game_biz: str, act_id: str, info_url: str,
                      region: str, uid: str) -> dict:
    """
    查询签到详情（不执行签到），返回：
    is_sign, total_sign_day, award_name 等
    """
    query = f"act_id={act_id}&region={region}&uid={uid}"
    url = f"{info_url}?lang=zh-cn&{query}"
    cookie = acc.sign_cookie()
    signgame = get_signgame(game_biz)

    headers = bbs_headers(acc.device_id, cookie, signgame)
    headers["DS"] = ds_gen("", query)

    try:
        resp = acc.session.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("retcode") == 0 and data.get("data"):
            info = data["data"]
            result = {
                "is_sign": info.get("is_sign", False),
                "total_sign_day": info.get("total_sign_day", 0),
                "sign_count_missed": info.get("sign_count_missed", 0),
                "award_name": "",
            }
            awards = info.get("awards", [])
            today_idx = min(info.get("total_sign_day", 0), len(awards)) - 1
            if today_idx >= 0 and awards:
                result["award_name"] = awards[today_idx].get("name", "")
            return result
    except Exception as e:
        log(f"[ERROR] query_sign_detail 异常: {e}")

    return {"is_sign": False, "total_sign_day": 0, "award_name": "", "error": True}


def query_all_games_status(acc: AccountData, game_biz_list: List[str] = None) -> List[dict]:
    """
    查询指定游戏的签到状态（不执行签到）
    game_biz_list: 要查询的游戏列表，None 表示全部
    """
    results = []
    games = game_biz_list if game_biz_list else list(GAMES.keys())

    for game_biz in games:
        if game_biz not in GAMES:
            continue
        name, act_id, info_url, _ = GAMES[game_biz]
        roles = get_roles(acc, game_biz)

        if not roles:
            results.append({
                "game": name, "game_biz": game_biz,
                "status": "no_account", "nickname": "", "uid": "",
                "is_sign": False, "total_days": 0, "award": "",
            })
            continue

        for role in roles:
            rn = role["nickname"] or "未知"
            ruid = role["game_uid"]
            rregion = role["region"]

            detail = query_sign_detail(acc, game_biz, act_id, info_url, rregion, ruid)
            results.append({
                "game": name, "game_biz": game_biz,
                "nickname": rn, "uid": ruid,
                "status": "ok",
                "is_sign": detail.get("is_sign", False),
                "total_days": detail.get("total_sign_day", 0),
                "award": detail.get("award_name", ""),
                "error": detail.get("error", False),
            })

    return results


def sign_account_selected(acc: AccountData, game_biz_list: List[str]) -> List[dict]:
    """只对指定游戏执行签到"""
    results = []
    nickname_label = acc.nickname or acc.uid

    log(f"[认证] 刷新 {nickname_label} 的凭证...")
    if not refresh_credentials(acc):
        log(f"[WARNING] {nickname_label} 凭证刷新失败，尝试用旧凭证签到")

    for game_biz in game_biz_list:
        if game_biz not in GAMES:
            continue
        name, act_id, info_url, sign_url = GAMES[game_biz]
        roles = get_roles(acc, game_biz)

        if not roles:
            results.append({"game": name, "status": "no_account"})
            continue

        for role in roles:
            rn = role["nickname"] or "未知"
            ruid = role["game_uid"]
            rregion = role["region"]
            log(f"[{nickname_label}] {name} - {rn}({ruid})")

            try:
                if is_signed(acc, game_biz, act_id, info_url, rregion, ruid):
                    log(f"[{nickname_label}] {name} - {rn} → 今日已签到")
                    results.append({"game": name, "nickname": rn, "status": "already_signed"})
                    continue

                res = do_sign(acc, game_biz, act_id, sign_url, rregion, ruid)
                if res.get("retcode") == 0:
                    log(f"[{nickname_label}] {name} - {rn} → 签到成功")
                    results.append({"game": name, "nickname": rn, "status": "success"})
                else:
                    msg = res.get("message", "未知错误")
                    log(f"[{nickname_label}] {name} - {rn} → 签到失败: {msg}")
                    results.append({"game": name, "nickname": rn, "status": "failed", "msg": msg})
            except Exception as e:
                log(f"[{nickname_label}] {name} - {rn} → 异常: {e}")
                results.append({"game": name, "nickname": rn, "status": "error", "msg": str(e)})

    return results
