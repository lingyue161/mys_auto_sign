#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
米游社自动签到 - GUI 界面 v5.0
- 天空蓝主题
- 签到状态按钮查询（不自动查询）
- 游戏勾选签到
- 昵称补充获取
- 自定义图标（ico.jpg）
"""

import sys
import os
import json
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from PIL import Image, ImageTk

# 确保能导入 mys_signer
sys.path.insert(0, str(Path(__file__).parent))
from mys_signer import (
    AccountManager, AccountData, qrcode_login,
    send_sms_code, phone_login,
    sign_all_accounts, sign_account_selected, refresh_credentials,
    query_all_games_status,
    set_log_callback, log, GAMES,
    DATA_DIR, ACCOUNTS_FILE,
)


# ──────────────────────────────────────────────
# 天空蓝主题色
# ──────────────────────────────────────────────

class Theme:
    """天空蓝主题配色"""
    # 背景
    BG_PRIMARY    = "#E8F4FD"   # 浅天空蓝
    BG_SECONDARY  = "#F5FAFF"   # 更浅的面板
    BG_WHITE      = "#FFFFFF"
    # 主色
    ACCENT        = "#5BA3D9"   # 天空蓝
    ACCENT_DARK   = "#3A7FBF"   # 深天蓝
    ACCENT_LIGHT  = "#A8D8F0"   # 浅天蓝
    HOVER         = "#4A93C9"   # 悬浮
    SELECTED      = "#D4EFFC"   # 选中行
    # 文字
    TEXT          = "#2C3E50"
    TEXT_SECOND   = "#7F8C8D"
    # 状态
    OK            = "#27AE60"
    WARN          = "#F39C12"
    ERR           = "#E74C3C"
    # 边框
    BORDER        = "#D6EAF8"
    # 日志
    LOG_BG        = "#1E2A38"
    LOG_FG        = "#A8D8F0"


# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

APP_TITLE = "米游社自动签到"
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 700

ICON_FILE = Path(__file__).parent / "ico.jpg"
# PyInstaller 打包后，文件在 _MEIPASS 临时目录
if getattr(sys, 'frozen', False):
    ICON_FILE = Path(sys._MEIPASS) / "ico.jpg"
GAME_PREFS_FILE = DATA_DIR / "game_prefs.json"


# ──────────────────────────────────────────────
# 游戏勾选偏好持久化
# ──────────────────────────────────────────────

def load_game_prefs() -> dict:
    if GAME_PREFS_FILE.exists():
        try:
            with open(GAME_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"default": list(GAMES.keys())}


def save_game_prefs(uid: str, selected: list):
    prefs = load_game_prefs()
    prefs[uid] = selected
    with open(GAME_PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def load_auto_sign_pref() -> bool:
    """读取自动签到开关偏好"""
    prefs = load_game_prefs()
    return prefs.get("auto_sign", False)


def save_auto_sign_pref(enabled: bool):
    """保存自动签到开关偏好"""
    prefs = load_game_prefs()
    prefs["auto_sign"] = enabled
    with open(GAME_PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# 自动签到调度器
# ──────────────────────────────────────────────

class AutoSignScheduler:
    """每天零点自动签到的调度器"""

    def __init__(self, manager: AccountManager, callback=None):
        self.manager = manager
        self.callback = callback
        self.enabled = False
        self._thread = None
        self._stop_event = threading.Event()

    @property
    def next_run(self) -> str:
        now = datetime.now()
        target = now.replace(hour=0, minute=0, second=5, microsecond=0)
        if now > target:
            target = target.replace(day=now.day + 1)
        delta = target - now
        h, remainder = divmod(int(delta.total_seconds()), 3600)
        m, s = divmod(remainder, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def start(self):
        if self.enabled:
            return
        self.enabled = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log("[自动签到] 已启动，每天 00:00:05 自动执行")

    def stop(self):
        self.enabled = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log("[自动签到] 已停止")

    def _run_loop(self):
        while not self._stop_event.is_set():
            now = datetime.now()
            target = now.replace(hour=0, minute=0, second=5, microsecond=0)
            if now > target:
                target = target.replace(day=now.day + 1)
            wait_seconds = (target - now).total_seconds()

            if self._stop_event.wait(timeout=min(wait_seconds, 30)):
                break

            now = datetime.now()
            if now.hour == 0 and 0 <= now.second <= 10:
                if self.callback:
                    self.callback()
                time.sleep(15)


# ──────────────────────────────────────────────
# 二维码登录窗口
# ──────────────────────────────────────────────

class QRLoginDialog(tk.Toplevel):
    """扫码登录弹窗"""

    def __init__(self, parent, on_success=None):
        super().__init__(parent)
        self.on_success = on_success
        self.result_account = None
        self._login_thread = None

        self.title("扫码登录 - 米游社")
        self.geometry("400x500")
        self.configure(bg=Theme.BG_WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # 居中
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 500) // 2
        self.geometry(f"+{x}+{y}")

        # UI
        frame = tk.Frame(self, bg=Theme.BG_WHITE, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="请用米游社 App 扫描二维码",
                 font=("Microsoft YaHei", 12, "bold"),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT).pack(pady=(0, 5))

        tk.Label(frame, text="扫描后请点击「确认登录」",
                 font=("Microsoft YaHei", 9),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT_SECOND).pack(pady=(0, 15))

        self.qr_label = tk.Label(frame, text="正在生成二维码...",
                                  bg=Theme.BG_WHITE, fg=Theme.TEXT_SECOND)
        self.qr_label.pack(pady=10)

        self.status_label = tk.Label(frame, text="等待扫码...",
                                      font=("Microsoft YaHei", 10),
                                      bg=Theme.BG_WHITE, fg=Theme.TEXT_SECOND)
        self.status_label.pack(pady=10)

        tk.Button(frame, text="取消", command=self._cancel,
                  font=("Microsoft YaHei", 10), bg=Theme.ACCENT, fg="white",
                  bd=0, padx=20, pady=5, cursor="hand2").pack(pady=10)

        self._start_login()

    def _start_login(self):
        def login_task():
            def qr_callback(msg):
                if msg.startswith("QR_URL:"):
                    url = msg.replace("QR_URL:", "")
                    self.after(0, lambda: self._show_qr(url))
                else:
                    self.after(0, lambda m=msg: self._update_status(m))

            account = qrcode_login(log_cb=qr_callback)
            if account:
                self.result_account = account
                self.after(0, lambda: self._on_login_ok())
            else:
                self.after(0, lambda: self._update_status("登录失败，请重试"))

        self._login_thread = threading.Thread(target=login_task, daemon=True)
        self._login_thread.start()

    def _show_qr(self, url: str):
        try:
            import qrcode
            qr = qrcode.QRCode(box_size=8, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color=Theme.TEXT, back_color=Theme.BG_WHITE)
            img = img.resize((250, 250), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self.qr_label.configure(image=self._photo, text="")
        except Exception as e:
            self.qr_label.configure(text=f"二维码生成失败: {e}")

    def _update_status(self, msg: str):
        if "[OK]" in msg:
            self.status_label.configure(text=msg.replace("[OK] ", ""), fg=Theme.OK)
        elif "[ERROR]" in msg or "失败" in msg:
            self.status_label.configure(text=msg, fg=Theme.ERR)
        else:
            self.status_label.configure(text=msg.replace("[DEBUG] ", ""), fg=Theme.TEXT)

    def _on_login_ok(self):
        self.destroy()
        if self.on_success and self.result_account:
            self.on_success(self.result_account)

    def _cancel(self):
        self.destroy()


# ──────────────────────────────────────────────
# 手机号登录窗口
# ──────────────────────────────────────────────

class PhoneLoginDialog(tk.Toplevel):
    """手机号+验证码登录弹窗"""

    def __init__(self, parent, on_success=None):
        super().__init__(parent)
        self.on_success = on_success
        self.result_account = None
        self._device_id = None
        self._countdown = 0
        self._countdown_job = None
        self._action_type = ""  # 手机号登录的 action_type

        self.title("手机号登录 - 米游社")
        self.geometry("400x380")
        self.configure(bg=Theme.BG_WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # 居中
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 380) // 2
        self.geometry(f"+{x}+{y}")

        # UI
        frame = tk.Frame(self, bg=Theme.BG_WHITE, padx=25, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="手机号登录",
                 font=("Microsoft YaHei", 14, "bold"),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT).pack(pady=(0, 15))

        # 手机号输入
        phone_frame = tk.Frame(frame, bg=Theme.BG_WHITE)
        phone_frame.pack(fill="x", pady=(0, 10))
        tk.Label(phone_frame, text="手机号:", font=("Microsoft YaHei", 10),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT, width=6, anchor="e").pack(side="left")
        self.phone_entry = tk.Entry(phone_frame, font=("Microsoft YaHei", 11),
                                     width=20, bd=1, relief="solid")
        self.phone_entry.pack(side="left", padx=(8, 0), ipady=4)

        # 验证码输入
        code_frame = tk.Frame(frame, bg=Theme.BG_WHITE)
        code_frame.pack(fill="x", pady=(0, 10))
        tk.Label(code_frame, text="验证码:", font=("Microsoft YaHei", 10),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT, width=6, anchor="e").pack(side="left")
        self.code_entry = tk.Entry(code_frame, font=("Microsoft YaHei", 11),
                                    width=12, bd=1, relief="solid")
        self.code_entry.pack(side="left", padx=(8, 0), ipady=4)

        self.sms_btn = tk.Button(code_frame, text="发送验证码", command=self._send_sms,
                                  font=("Microsoft YaHei", 9), bg=Theme.ACCENT, fg="white",
                                  bd=0, padx=8, pady=4, cursor="hand2")
        self.sms_btn.pack(side="left", padx=(8, 0))

        # 登录按钮
        btn_frame = tk.Frame(frame, bg=Theme.BG_WHITE)
        btn_frame.pack(fill="x", pady=(15, 5))
        tk.Button(btn_frame, text="登录", command=self._do_login,
                  font=("Microsoft YaHei", 11, "bold"), bg=Theme.ACCENT, fg="white",
                  bd=0, padx=30, pady=6, cursor="hand2").pack(side="left", expand=True)
        tk.Button(btn_frame, text="取消", command=self._cancel,
                  font=("Microsoft YaHei", 10), bg=Theme.BG_SECONDARY, fg=Theme.TEXT,
                  bd=0, padx=20, pady=6, cursor="hand2").pack(side="left", padx=(10, 0))

        # 状态提示
        self.status_label = tk.Label(frame, text="",
                                      font=("Microsoft YaHei", 9),
                                      bg=Theme.BG_WHITE, fg=Theme.TEXT_SECOND)
        self.status_label.pack(pady=(10, 0))

    def _send_sms(self):
        phone = self.phone_entry.get().strip()
        if not phone:
            self.status_label.config(text="请输入手机号", fg=Theme.ERR)
            return
        if len(phone) != 11 or not phone.isdigit():
            self.status_label.config(text="请输入正确的11位手机号", fg=Theme.ERR)
            return

        self.sms_btn.config(state="disabled", text="发送中...")
        self.status_label.config(text="正在发送验证码...", fg=Theme.TEXT_SECOND)
        self.update()

        def sms_task():
            success, action_type = send_sms_code(phone, log_cb=lambda msg: self.after(
                0, lambda m=msg: self.status_label.config(text=m.replace("[OK] ", "").replace("[ERROR] ", "").replace("[DEBUG] ", ""),
                                                          fg=Theme.OK if "[OK]" in m else (Theme.ERR if "[ERROR]" in m else Theme.TEXT_SECOND))))
            self.after(0, lambda: self._on_sms_sent(success, action_type))

        threading.Thread(target=sms_task, daemon=True).start()

    def _on_sms_sent(self, success: bool, action_type: str):
        if success:
            self._action_type = action_type
            self.status_label.config(text="验证码已发送，请查收短信", fg=Theme.OK)
            self._countdown = 60
            self._tick_countdown()
        else:
            self.sms_btn.config(state="normal", text="发送验证码")
            if not ("失败" in self.status_label.cget("text") or "错误" in self.status_label.cget("text")):
                self.status_label.config(text="发送失败，请稍后重试", fg=Theme.ERR)

    def _tick_countdown(self):
        if self._countdown > 0:
            self.sms_btn.config(state="disabled", text=f"{self._countdown}s")
            self._countdown -= 1
            self._countdown_job = self.after(1000, self._tick_countdown)
        else:
            self.sms_btn.config(state="normal", text="重新发送")

    def _do_login(self):
        phone = self.phone_entry.get().strip()
        code = self.code_entry.get().strip()

        if not phone or len(phone) != 11:
            self.status_label.config(text="请输入正确的手机号", fg=Theme.ERR)
            return
        if not code:
            self.status_label.config(text="请输入验证码", fg=Theme.ERR)
            return

        self.status_label.config(text="正在登录...", fg=Theme.TEXT_SECOND)
        self.update()

        def login_task():
            account = phone_login(phone, code, action_type=self._action_type, log_cb=lambda msg: self.after(
                0, lambda m=msg: self.status_label.config(
                    text=m.replace("[OK] ", "").replace("[ERROR] ", "").replace("[DEBUG] ", ""),
                    fg=Theme.OK if "[OK]" in m else (Theme.ERR if "[ERROR]" in m else Theme.TEXT_SECOND))))
            self.after(0, lambda: self._on_login_done(account))

        threading.Thread(target=login_task, daemon=True).start()

    def _on_login_done(self, account):
        if account:
            self.result_account = account
            self.destroy()
            if self.on_success:
                self.on_success(account)
        else:
            self.status_label.config(text="登录失败，请检查验证码后重试", fg=Theme.ERR)

    def _cancel(self):
        if self._countdown_job:
            self.after_cancel(self._countdown_job)
        self.destroy()


# ──────────────────────────────────────────────
# 主界面
# ──────────────────────────────────────────────

class MiYoSheSignerApp:
    """米游社自动签到主界面"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(720, 600)
        self.root.configure(bg=Theme.BG_PRIMARY)

        # 设置 ttk 主题
        self._setup_styles()

        # 账号管理器
        self.manager = AccountManager()

        # 游戏偏好
        self.game_prefs = load_game_prefs()

        # 自动签到调度器
        self.scheduler = AutoSignScheduler(self.manager, callback=self._auto_sign_task)

        # 签到中标志
        self._signing = False

        # 构建界面
        self._build_ui()

        # 设置日志回调
        set_log_callback(self._append_log)

        # 加载账号列表
        self._refresh_account_list()

        # 关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        """配置 ttk 样式为天空蓝主题"""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # 通用 Treeview
        style.configure("Sky.Treeview",
                        background=Theme.BG_WHITE, foreground=Theme.TEXT,
                        fieldbackground=Theme.BG_WHITE, borderwidth=0,
                        font=("Microsoft YaHei UI", 10), rowheight=36)
        style.configure("Sky.Treeview.Heading",
                        background=Theme.ACCENT, foreground="white",
                        font=("Microsoft YaHei UI", 10, "bold"), borderwidth=0,
                        padding=4)
        style.map("Sky.Treeview",
                  background=[("selected", Theme.SELECTED)],
                  foreground=[("selected", Theme.ACCENT_DARK)])

        # 账号列表专用样式 — 选中行更醒目
        style.configure("Account.Treeview",
                        background=Theme.BG_WHITE, foreground=Theme.TEXT,
                        fieldbackground=Theme.BG_WHITE, borderwidth=0,
                        font=("Microsoft YaHei UI", 10), rowheight=40)
        style.configure("Account.Treeview.Heading",
                        background=Theme.ACCENT, foreground="white",
                        font=("Microsoft YaHei UI", 10, "bold"), borderwidth=0,
                        padding=4)
        style.map("Account.Treeview",
                  background=[("selected", "#B8E2F8")],
                  foreground=[("selected", "#1A5276")])

    # ──────────────────────────────────────────
    # 构建 UI
    # ──────────────────────────────────────────

    def _build_ui(self):
        """构建完整界面"""
        # ─── 顶部标题栏 ───
        self._build_header()

        # ─── 主内容区 ───
        main_frame = tk.Frame(self.root, bg=Theme.BG_PRIMARY)
        main_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # 左右分栏
        left_frame = tk.Frame(main_frame, bg=Theme.BG_PRIMARY)
        left_frame.pack(side="left", fill="both", expand=True)

        right_frame = tk.Frame(main_frame, bg=Theme.BG_PRIMARY, width=230)
        right_frame.pack(side="right", fill="y", padx=(12, 0))
        right_frame.pack_propagate(False)

        # 左侧区域
        self._build_account_section(left_frame)
        self._build_sign_detail_section(left_frame)

        # 右侧控制面板
        self._build_control_panel(right_frame)

        # ─── 底部日志 ───
        self._build_log_section()

    def _build_header(self):
        """顶部标题栏"""
        header = tk.Frame(self.root, bg=Theme.ACCENT, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_frame = tk.Frame(header, bg=Theme.ACCENT)
        title_frame.pack(side="left", padx=16)

        tk.Label(title_frame, text="米游社自动签到",
                 font=("Microsoft YaHei UI", 16, "bold"),
                 bg=Theme.ACCENT, fg="white").pack(side="left", pady=12)

        tk.Label(title_frame, text="v5.1",
                 font=("Microsoft YaHei UI", 9),
                 bg=Theme.ACCENT, fg=Theme.ACCENT_LIGHT).pack(side="left", padx=(8, 0), pady=12)

        self.time_label = tk.Label(header, text="",
                                    font=("Microsoft YaHei UI", 9),
                                    bg=Theme.ACCENT, fg=Theme.ACCENT_LIGHT)
        self.time_label.pack(side="right", padx=16, pady=12)
        self._tick_time()

    def _build_account_section(self, parent):
        """账号列表区域"""
        section = tk.LabelFrame(parent, text="  账号管理  ",
                                 font=("Microsoft YaHei UI", 11, "bold"),
                                 bg=Theme.BG_WHITE, fg=Theme.TEXT, bd=1, relief="solid")
        section.pack(fill="x", pady=(0, 8))

        # 按钮行
        btn_frame = tk.Frame(section, bg=Theme.BG_WHITE)
        btn_frame.pack(fill="x", padx=8, pady=(8, 4))

        self._make_btn(btn_frame, "扫码添加", self._add_account, Theme.ACCENT).pack(side="left", padx=(0, 6))
        self._make_btn(btn_frame, "手机号登录", self._phone_login, "#5BA3D9").pack(side="left", padx=(0, 6))
        self._make_btn(btn_frame, "删除账号", self._remove_account, Theme.ERR).pack(side="left")

        # Treeview
        tree_frame = tk.Frame(section, bg=Theme.BG_WHITE)
        tree_frame.pack(fill="x", padx=8, pady=(0, 8))

        self.account_tree = ttk.Treeview(tree_frame, columns=("uid", "nickname", "status"),
                                          show="tree headings", style="Account.Treeview", height=4,
                                          selectmode="browse")

        self.account_tree.heading("#0", text="", anchor="center")
        self.account_tree.heading("uid", text="UID")
        self.account_tree.heading("nickname", text="昵称")
        self.account_tree.heading("status", text="状态")

        self.account_tree.column("#0", width=30, minwidth=30, stretch=False, anchor="center")
        self.account_tree.column("uid", width=120, minwidth=100, stretch=True, anchor="center")
        self.account_tree.column("nickname", width=150, minwidth=100, stretch=True, anchor="center")
        self.account_tree.column("status", width=90, minwidth=70, stretch=True, anchor="center")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.account_tree.yview)
        self.account_tree.configure(yscrollcommand=scrollbar.set)

        self.account_tree.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.account_tree.bind("<<TreeviewSelect>>", self._on_account_select)

    def _build_sign_detail_section(self, parent):
        """签到详情区域"""
        section = tk.LabelFrame(parent, text="  签到状态  ",
                                 font=("Microsoft YaHei UI", 11, "bold"),
                                 bg=Theme.BG_WHITE, fg=Theme.TEXT, bd=1, relief="solid")
        section.pack(fill="both", expand=True)

        self.sign_hint = tk.Label(section,
                                   text="请先选择一个账号，然后点击右侧「查询签到状态」",
                                   font=("Microsoft YaHei UI", 9),
                                   bg=Theme.BG_WHITE, fg=Theme.TEXT_SECOND)
        self.sign_hint.pack(padx=8, pady=4)

        # Treeview
        tree_frame = tk.Frame(section, bg=Theme.BG_WHITE)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.sign_tree = ttk.Treeview(tree_frame,
                                       columns=("game", "nickname", "status", "detail"),
                                       show="headings", style="Sky.Treeview", height=6)

        self.sign_tree.heading("game", text="游戏", anchor="w")
        self.sign_tree.heading("nickname", text="角色", anchor="w")
        self.sign_tree.heading("status", text="签到状态", anchor="w")
        self.sign_tree.heading("detail", text="详情", anchor="w")

        self.sign_tree.column("game", width=110, minwidth=80, stretch=True, anchor="w")
        self.sign_tree.column("nickname", width=110, minwidth=80, stretch=True, anchor="w")
        self.sign_tree.column("status", width=80, minwidth=60, stretch=True, anchor="w")
        self.sign_tree.column("detail", width=180, minwidth=120, stretch=True, anchor="w")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.sign_tree.yview)
        self.sign_tree.configure(yscrollcommand=scrollbar.set)

        self.sign_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 配置行颜色标签
        self.sign_tree.tag_configure("signed", foreground=Theme.OK)
        self.sign_tree.tag_configure("unsigned", foreground=Theme.WARN)
        self.sign_tree.tag_configure("no", foreground=Theme.TEXT_SECOND)
        self.sign_tree.tag_configure("error", foreground=Theme.ERR)

    def _build_control_panel(self, parent):
        """右侧控制面板"""
        # ── 游戏勾选区 ──
        game_section = tk.LabelFrame(parent, text="  签到游戏  ",
                                      font=("Microsoft YaHei UI", 11, "bold"),
                                      bg=Theme.BG_WHITE, fg=Theme.TEXT, bd=1, relief="solid")
        game_section.pack(fill="x", pady=(0, 8))

        self.game_vars = {}
        self._loading_prefs = False
        for game_biz, (name, *_) in GAMES.items():
            var = tk.BooleanVar(value=True)
            self.game_vars[game_biz] = var
            tk.Checkbutton(game_section, text=name, variable=var,
                           font=("Microsoft YaHei UI", 10),
                           bg=Theme.BG_WHITE, fg=Theme.TEXT,
                           selectcolor=Theme.BG_SECONDARY,
                           activebackground=Theme.BG_WHITE,
                           activeforeground=Theme.ACCENT_DARK,
                           cursor="hand2",
                           command=self._on_game_check_changed).pack(anchor="w", padx=12, pady=2)

        # 全选/取消
        sel_frame = tk.Frame(game_section, bg=Theme.BG_WHITE)
        sel_frame.pack(fill="x", padx=8, pady=(4, 8))

        tk.Button(sel_frame, text="全选", font=("Microsoft YaHei UI", 9),
                  bg=Theme.BG_SECONDARY, fg=Theme.ACCENT_DARK,
                  bd=0, padx=8, pady=2, cursor="hand2",
                  command=lambda: [v.set(True) for v in self.game_vars.values()]).pack(side="left", padx=(0, 4))
        tk.Button(sel_frame, text="取消", font=("Microsoft YaHei UI", 9),
                  bg=Theme.BG_SECONDARY, fg=Theme.ACCENT_DARK,
                  bd=0, padx=8, pady=2, cursor="hand2",
                  command=lambda: [v.set(False) for v in self.game_vars.values()]).pack(side="left")

        # ── 操作按钮区 ──
        action_section = tk.LabelFrame(parent, text="  操作  ",
                                        font=("Microsoft YaHei UI", 11, "bold"),
                                        bg=Theme.BG_WHITE, fg=Theme.TEXT, bd=1, relief="solid")
        action_section.pack(fill="x", pady=(0, 8))

        btn_inner = tk.Frame(action_section, bg=Theme.BG_WHITE)
        btn_inner.pack(fill="x", padx=8, pady=8)

        self._make_btn(btn_inner, "查询签到状态", self._query_status,
                       Theme.ACCENT, width=18).pack(fill="x", pady=3)
        self._make_btn(btn_inner, "一键签到", self._manual_sign,
                       Theme.OK, width=18).pack(fill="x", pady=3)
        self._make_btn(btn_inner, "签到所有账号", self._sign_all_accounts,
                       Theme.ACCENT_DARK, width=18).pack(fill="x", pady=3)

        # 自动签到开关（从配置文件恢复上次状态）
        self.auto_var = tk.BooleanVar(value=load_auto_sign_pref())
        tk.Checkbutton(action_section, text="每天自动签到 (需保持运行)",
                       variable=self.auto_var,
                       font=("Microsoft YaHei UI", 9),
                       bg=Theme.BG_WHITE, fg=Theme.TEXT,
                       selectcolor=Theme.BG_SECONDARY,
                       activebackground=Theme.BG_WHITE,
                       cursor="hand2",
                       command=self._toggle_auto_sign).pack(anchor="w", padx=12, pady=(0, 8))

        # ── 自动签到倒计时 ──
        timer_section = tk.LabelFrame(parent, text="  自动签到  ",
                                       font=("Microsoft YaHei UI", 11, "bold"),
                                       bg=Theme.BG_WHITE, fg=Theme.TEXT, bd=1, relief="solid")
        timer_section.pack(fill="x")

        self.timer_label = tk.Label(timer_section, text="自动签到未开启",
                                     font=("Microsoft YaHei UI", 10),
                                     bg=Theme.BG_WHITE, fg=Theme.TEXT_SECOND)
        self.timer_label.pack(padx=12, pady=8)

    def _build_log_section(self):
        """底部日志区域"""
        log_frame = tk.LabelFrame(self.root, text="  运行日志  ",
                                   font=("Microsoft YaHei UI", 10, "bold"),
                                   bg=Theme.LOG_BG, fg=Theme.LOG_FG, bd=1, relief="solid")
        log_frame.pack(fill="x", padx=12, pady=(0, 12))

        self.log_text = tk.Text(log_frame, height=6,
                                bg=Theme.LOG_BG, fg=Theme.LOG_FG,
                                font=("Consolas", 9), bd=0, wrap="word",
                                insertbackground=Theme.LOG_FG,
                                selectbackground=Theme.ACCENT)
        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.pack(side="left", fill="x", expand=True, padx=(4, 0), pady=4)
        scrollbar.pack(side="right", fill="y", padx=(0, 4), pady=4)

        self.log_text.configure(state="disabled")

        # 日志颜色标签
        self.log_text.tag_configure("info", foreground=Theme.LOG_FG)
        self.log_text.tag_configure("success", foreground="#4ec9b0")
        self.log_text.tag_configure("warning", foreground="#dcdcaa")
        self.log_text.tag_configure("error", foreground="#f48771")
        self.log_text.tag_configure("debug", foreground="#808080")

    # ──────────────────────────────────────────
    # UI 工具
    # ──────────────────────────────────────────

    def _make_btn(self, parent, text, command, color, width=None):
        """创建统一风格按钮"""
        btn = tk.Button(parent, text=text, command=command,
                        font=("Microsoft YaHei UI", 10, "bold"),
                        bg=color, fg="white", bd=0, padx=12, pady=6, cursor="hand2")
        if width:
            btn.configure(width=width)
        btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=Theme.HOVER))
        btn.bind("<Leave>", lambda e, b=btn, c=color: b.configure(bg=c))
        return btn

    def _tick_time(self):
        self.time_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.root.after(1000, self._tick_time)

    def _get_selected_games(self) -> list:
        return [g for g, v in self.game_vars.items() if v.get()]

    def _get_selected_account(self):
        sel = self.account_tree.selection()
        if not sel:
            return None
        uid = str(self.account_tree.item(sel[0])["values"][0])
        return self.manager.get_account(uid)

    # ──────────────────────────────────────────
    # 账号管理
    # ──────────────────────────────────────────

    def _refresh_account_list(self):
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)

        for acc in self.manager.list_accounts():
            uid = acc.uid
            nickname = acc.nickname or "未获取"
            status = "已保存" if acc.stoken else "凭证失效"
            tag = "ok" if acc.stoken else "warn"
            self.account_tree.insert("", tk.END, iid=uid,
                                     text="",  # 选中标记列
                                     values=(uid, nickname, status), tags=(tag,))

        self.account_tree.tag_configure("ok", foreground=Theme.TEXT)
        self.account_tree.tag_configure("warn", foreground=Theme.ERR)

        # 自动选中第一个
        children = self.account_tree.get_children()
        if children:
            self.account_tree.selection_set(children[0])
            # 手动触发选中事件
            self._update_account_mark(children[0])
            acc = self._get_selected_account()
            if acc:
                uid = acc.uid
                prefs = self.game_prefs.get(uid, self.game_prefs.get("default", list(GAMES.keys())))
                self._loading_prefs = True
                for game_biz, var in self.game_vars.items():
                    var.set(game_biz in prefs)
                self._loading_prefs = False

        # 保存管理器（凭证可能已更新）
        self.manager._save()

    def _add_account(self):
        def on_login_ok(account: AccountData):
            # 补充获取昵称
            if not account.nickname:
                refresh_credentials(account)
            self.manager.add_account(account)
            self._refresh_account_list()
            messagebox.showinfo("添加成功", f"已添加账号: {account.nickname or account.uid}")

        QRLoginDialog(self.root, on_success=on_login_ok)

    def _phone_login(self):
        def on_login_ok(account: AccountData):
            if not account.nickname:
                refresh_credentials(account)
            self.manager.add_account(account)
            self._refresh_account_list()
            messagebox.showinfo("添加成功", f"已添加账号: {account.nickname or account.uid}")

        PhoneLoginDialog(self.root, on_success=on_login_ok)

    def _remove_account(self):
        selected = self.account_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择要删除的账号")
            return

        uid = selected[0]
        acc = self.manager.get_account(uid)
        name = (acc.nickname if acc else "未知") or uid

        if messagebox.askyesno("确认删除", f"确定要删除账号 {name}({uid}) 吗？"):
            self.manager.remove_account(uid)
            self._refresh_account_list()
            self.sign_tree.delete(*self.sign_tree.get_children())
            self.sign_hint.config(text="请先选择一个账号，然后点击右侧「查询签到状态」",
                                   fg=Theme.TEXT_SECOND)

    def _on_account_select(self, event):
        """选中账号时加载游戏勾选偏好"""
        sel = self.account_tree.selection()
        if not sel:
            return

        # 更新选中标记
        self._update_account_mark(sel[0])

        acc = self._get_selected_account()
        if not acc:
            return

        uid = acc.uid
        prefs = self.game_prefs.get(uid, self.game_prefs.get("default", list(GAMES.keys())))

        # 暂时禁止保存，防止恢复勾选时触发 command 回调覆盖
        self._loading_prefs = True
        for game_biz, var in self.game_vars.items():
            var.set(game_biz in prefs)
        self._loading_prefs = False

        # 更新签到状态区域提示 — 显示当前账号
        name = acc.nickname or acc.uid
        self.sign_hint.config(text=f"当前账号: {name}", fg=Theme.ACCENT_DARK)

    def _on_game_check_changed(self):
        """游戏勾选变化时自动保存偏好"""
        if getattr(self, '_loading_prefs', False):
            return
        acc = self._get_selected_account()
        if not acc:
            return
        selected = self._get_selected_games()
        save_game_prefs(acc.uid, selected)
        # 同步更新内存缓存
        self.game_prefs[acc.uid] = selected

    def _update_account_mark(self, selected_iid):
        """更新账号列表的选中标记（只给选中行显示 ▶）"""
        for item in self.account_tree.get_children():
            if item == selected_iid:
                self.account_tree.item(item, text="▶")
            else:
                self.account_tree.item(item, text="")

    # ──────────────────────────────────────────
    # 查询 & 签到
    # ──────────────────────────────────────────

    def _query_status(self):
        """查询选中账号的签到状态"""
        acc = self._get_selected_account()
        if not acc:
            messagebox.showinfo("提示", "请先选择一个账号")
            return

        selected_games = self._get_selected_games()
        if not selected_games:
            messagebox.showinfo("提示", "请至少选择一个游戏")
            return

        # 保存偏好
        save_game_prefs(acc.uid, selected_games)

        name = acc.nickname or acc.uid
        self._append_log(f"正在查询 {name} 的签到状态...")
        self.sign_hint.config(text="正在查询中...", fg=Theme.ACCENT_DARK)
        self._signing = True

        threading.Thread(target=self._do_query_status,
                         args=(acc, selected_games), daemon=True).start()

    def _do_query_status(self, acc: AccountData, selected_games: list):
        """后台线程：查询签到状态"""
        try:
            # 刷新凭证 + 补充昵称
            self._append_log(f"[DEBUG] 刷新 {acc.nickname or acc.uid} 的凭证...")
            refresh_credentials(acc)

            self._append_log(f"[DEBUG] 开始查询 {len(selected_games)} 个游戏的签到状态...")
            results = query_all_games_status(acc, selected_games)

            self._append_log(f"[DEBUG] 查询完成，返回 {len(results)} 条结果")
            for r in results:
                self._append_log(f"[DEBUG]   {r.get('game','')}: status={r.get('status','')}, is_sign={r.get('is_sign','')}")

            # 更新账号列表中的昵称（如果之前是"未获取"）
            if acc.nickname:
                self.root.after(0, self._update_account_nickname, acc)

            self.root.after(0, lambda: self._show_sign_results(results, is_query=True))
        except Exception as e:
            err_msg = str(e)
            self._append_log(f"[ERROR] 查询签到状态失败: {err_msg}")
            self.root.after(0, lambda m=err_msg: self.sign_hint.config(
                text=f"查询失败: {m}", fg=Theme.ERR))
        finally:
            self._signing = False

    def _update_account_nickname(self, acc: AccountData):
        """更新账号列表中显示的昵称"""
        try:
            children = self.account_tree.get_children()
            for item in children:
                vals = self.account_tree.item(item)["values"]
                if vals and str(vals[0]) == acc.uid:
                    nickname = acc.nickname or "未获取"
                    self.account_tree.item(item, values=(acc.uid, nickname, vals[2] if len(vals) > 2 else ""))
                    break
        except Exception:
            pass

    def _manual_sign(self):
        """签到选中账号（只签勾选的游戏）"""
        acc = self._get_selected_account()
        if not acc:
            messagebox.showinfo("提示", "请先选择一个账号")
            return

        selected_games = self._get_selected_games()
        if not selected_games:
            messagebox.showinfo("提示", "请至少选择一个游戏")
            return

        save_game_prefs(acc.uid, selected_games)

        name = acc.nickname or acc.uid
        self._append_log(f"正在为 {name} 签到...")
        self.sign_hint.config(text="正在签到中...", fg=Theme.ACCENT_DARK)
        self._signing = True

        def task():
            results = sign_account_selected(acc, selected_games)
            self.manager._save()  # 保存更新后的凭证
            self.root.after(0, lambda: self._show_sign_results(results, is_query=False))
            self._signing = False

        threading.Thread(target=task, daemon=True).start()

    def _sign_all_accounts(self):
        """签到所有账号"""
        if not self.manager.accounts:
            messagebox.showinfo("提示", "没有已保存的账号")
            return

        selected_games = self._get_selected_games()
        if not selected_games:
            messagebox.showinfo("提示", "请至少选择一个游戏")
            return

        self._append_log(f"正在签到 {len(self.manager.accounts)} 个账号...")
        self._signing = True

        def task():
            all_results = {}
            for uid, acc in self.manager.accounts.items():
                name = acc.nickname or uid
                self._append_log(f"签到 {name}...")
                results = sign_account_selected(acc, selected_games)
                all_results[uid] = results

                for r in results:
                    st = r.get("status", "")
                    if st == "success":
                        self._append_log(f"  {r['game']}: 签到成功")
                    elif st == "already_signed":
                        self._append_log(f"  {r['game']}: 今日已签")
                    elif st == "no_account":
                        self._append_log(f"  {r['game']}: 未绑定")
                    else:
                        self._append_log(f"  {r['game']}: {r.get('msg', '失败')}")
                time.sleep(1)

            self.manager._save()
            self.root.after(0, self._refresh_account_list)
            self._signing = False
            self._append_log("所有账号签到完成")

        threading.Thread(target=task, daemon=True).start()

    def _show_sign_results(self, results: list, is_query: bool):
        """在 Treeview 中显示签到结果"""
        self.sign_tree.delete(*self.sign_tree.get_children())

        has_data = False
        for r in results:
            game = r.get("game", "")
            nickname = r.get("nickname", "")
            status = r.get("status", "")

            if status == "no_account":
                detail = "未绑定角色"
                status_text = "未绑定"
                tag = "no"
            elif status == "ok" or status == "already_signed":
                is_signed = r.get("is_sign", True)
                total = r.get("total_days", 0)
                award = r.get("award", "")
                detail = f"累计 {total} 天"
                if award:
                    detail += f" | {award}"
                status_text = "已签到" if is_signed else "未签到"
                tag = "signed" if is_signed else "unsigned"
            elif status == "success":
                detail = "签到成功"
                status_text = "已签到"
                tag = "signed"
            elif status == "error":
                detail = r.get("msg", "错误")
                status_text = "错误"
                tag = "error"
            elif status == "failed":
                detail = r.get("msg", "失败")
                status_text = "失败"
                tag = "error"
            else:
                detail = r.get("msg", "")
                status_text = "失败"
                tag = "error"

            display_name = nickname if nickname else ""
            if not display_name and r.get("uid"):
                display_name = f"UID {r['uid']}"

            self.sign_tree.insert("", tk.END,
                                  values=(game, display_name, status_text, detail),
                                  tags=(tag,))
            has_data = True

        if has_data:
            action = "查询" if is_query else "签到"
            self.sign_hint.config(text=f"{action}完成", fg=Theme.OK)
            self._append_log(f"{'查询' if is_query else '签到'}结果已显示")
        else:
            self.sign_hint.config(text="未获取到任何数据", fg=Theme.ERR)

    # ──────────────────────────────────────────
    # 自动签到
    # ──────────────────────────────────────────

    def _toggle_auto_sign(self):
        if self.auto_var.get():
            if not self.manager.accounts:
                messagebox.showwarning("提示", "没有已添加的账号，请先添加账号")
                self.auto_var.set(False)
                return
            self.scheduler.start()
            self._update_timer()
            self._append_log("[自动签到] 已开启")
        else:
            self.scheduler.stop()
            self.timer_label.config(text="自动签到未开启", fg=Theme.TEXT_SECOND)
            self._append_log("[自动签到] 已关闭")
        # 保存自动签到开关状态
        save_auto_sign_pref(self.auto_var.get())

    def _restore_auto_sign(self):
        """启动时恢复自动签到状态"""
        if self.auto_var.get() and self.manager.accounts:
            self.scheduler.start()
            self._update_timer()
            self._append_log("[自动签到] 已自动恢复（上次退出时已开启）")

    def _update_timer(self):
        if not self.auto_var.get():
            self.timer_label.config(text="自动签到未开启", fg=Theme.TEXT_SECOND)
            return

        self.timer_label.config(text=f"距离下次签到: {self.scheduler.next_run}",
                                fg=Theme.ACCENT)
        self.root.after(5000, self._update_timer)

    def _auto_sign_task(self):
        """自动签到任务（由 AutoSignScheduler 回调，运行在后台线程）"""
        if not self.manager.accounts:
            return

        self._append_log(f"[自动签到] 开始签到 {len(self.manager.accounts)} 个账号...")
        all_results = {}
        for uid, acc in self.manager.accounts.items():
            name = acc.nickname or uid
            self._append_log(f"[自动签到] 签到 {name}...")
            results = sign_account_selected(acc, list(GAMES.keys()))
            all_results[uid] = results

            for r in results:
                st = r.get("status", "")
                if st == "success":
                    self._append_log(f"  {r['game']}: 签到成功")
                elif st == "already_signed":
                    self._append_log(f"  {r['game']}: 今日已签")
                elif st == "no_account":
                    self._append_log(f"  {r['game']}: 未绑定")
                else:
                    self._append_log(f"  {r['game']}: {r.get('msg', '失败')}")
            time.sleep(1)

        self.manager._save()
        self._append_log("[自动签到] 所有账号签到完成")

    # ──────────────────────────────────────────
    # 日志
    # ──────────────────────────────────────────

    def _append_log(self, msg: str):
        def _insert():
            self.log_text.configure(state="normal")
            if "[ERROR]" in msg or "失败" in msg or "异常" in msg:
                tag = "error"
            elif "[WARNING]" in msg or "⚠" in msg:
                tag = "warning"
            elif "[OK]" in msg or "签到成功" in msg or "已签到" in msg:
                tag = "success"
            elif "[DEBUG]" in msg:
                tag = "debug"
            else:
                tag = "info"
            self.log_text.insert(tk.END, msg + "\n", tag)
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")

            # 限制日志行数
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > 2000:
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", f"{line_count - 1500}.0")
                self.log_text.configure(state="disabled")

        try:
            self.root.after(0, _insert)
        except Exception:
            pass

    # ──────────────────────────────────────────
    # 关闭
    # ──────────────────────────────────────────

    def _on_close(self):
        if messagebox.askokcancel("退出", "退出后自动签到将停止。\n确定要退出吗？"):
            self.scheduler.stop()
            self.root.destroy()


# ──────────────────────────────────────────────
# 启动公告弹窗
# ──────────────────────────────────────────────

class AboutDialog(tk.Toplevel):
    """启动时弹出的关于/公告窗口"""

    AUTHOR = "晟曦"
    GITHUB = "https://github.com/lingyue161"
    DOUYIN = "https://v.douyin.com/A-uK27ODbFc/"
    VERSION = "v5.1"
    # PyInstaller 打包后，资源文件在 _MEIPASS 临时目录
    if getattr(sys, 'frozen', False):
        PROJECT_DIR = Path(sys._MEIPASS)
    else:
        PROJECT_DIR = Path(__file__).parent

    def __init__(self, parent):
        super().__init__(parent)
        w, h = 600, 440
        self.title("关于 - 米游社自动签到")
        self.geometry(f"{w}x{h}")
        self.configure(bg=Theme.BG_WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # 屏幕居中
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        # 阻止关闭按钮，必须点"我已了解"
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        # 内容
        frame = tk.Frame(self, bg=Theme.BG_WHITE, padx=30, pady=15)
        frame.pack(fill="both", expand=True)

        # 标题
        tk.Label(frame, text="米游社自动签到",
                 font=("Microsoft YaHei UI", 16, "bold"),
                 bg=Theme.BG_WHITE, fg=Theme.ACCENT).pack(pady=(0, 0))

        tk.Label(frame, text=self.VERSION,
                 font=("Microsoft YaHei UI", 9),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT_SECOND).pack(pady=(0, 6))

        # ── 开发者信息 + 贡献者（左右布局）──
        main_info = tk.Frame(frame, bg=Theme.BG_WHITE)
        main_info.pack(fill="x", pady=(0, 6))

        # 左侧：链接信息
        info_frame = tk.Frame(main_info, bg=Theme.BG_WHITE)
        info_frame.pack(side="left", fill="y")

        tk.Label(info_frame, text="开发者：",
                 font=("Microsoft YaHei UI", 10),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT).grid(row=0, column=0, sticky="w", pady=2)
        tk.Label(info_frame, text=self.AUTHOR,
                 font=("Microsoft YaHei UI", 10, "bold"),
                 bg=Theme.BG_WHITE, fg=Theme.ACCENT_DARK).grid(row=0, column=1, sticky="w", padx=(4, 0), pady=2)

        tk.Label(info_frame, text="GitHub：",
                 font=("Microsoft YaHei UI", 10),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT).grid(row=1, column=0, sticky="w", pady=2)
        gh_link = tk.Label(info_frame, text=self.GITHUB,
                           font=("Microsoft YaHei UI", 9),
                           bg=Theme.BG_WHITE, fg=Theme.ACCENT, cursor="hand2", underline=True)
        gh_link.grid(row=1, column=1, sticky="w", padx=(4, 0), pady=2)
        gh_link.bind("<Button-1>", lambda e: webbrowser.open(self.GITHUB))
        gh_link.bind("<Enter>", lambda e: gh_link.configure(fg=Theme.ACCENT_DARK))
        gh_link.bind("<Leave>", lambda e: gh_link.configure(fg=Theme.ACCENT))

        tk.Label(info_frame, text="抖音主页：",
                 font=("Microsoft YaHei UI", 10),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT).grid(row=2, column=0, sticky="w", pady=2)
        dy_link = tk.Label(info_frame, text="点击访问",
                           font=("Microsoft YaHei UI", 9),
                           bg=Theme.BG_WHITE, fg="#FE2C55", cursor="hand2", underline=True)
        dy_link.grid(row=2, column=1, sticky="w", padx=(4, 0), pady=2)
        dy_link.bind("<Button-1>", lambda e: webbrowser.open(self.DOUYIN))
        dy_link.bind("<Enter>", lambda e: dy_link.configure(fg="#E0194A"))
        dy_link.bind("<Leave>", lambda e: dy_link.configure(fg="#FE2C55"))

        tk.Label(info_frame, text="闲鱼小店：",
                 font=("Microsoft YaHei UI", 10),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT).grid(row=3, column=0, sticky="w", pady=2)
        xy_link = tk.Label(info_frame, text="求关照~点我逛逛",
                           font=("Microsoft YaHei UI", 9),
                           bg=Theme.BG_WHITE, fg="#FF6A00", cursor="hand2", underline=True)
        xy_link.grid(row=3, column=1, sticky="w", padx=(4, 0), pady=2)
        xy_link.bind("<Button-1>", lambda e: webbrowser.open("https://m.tb.cn/h.i6sCzog?tk=8Tyx5ZUgbkv"))
        xy_link.bind("<Enter>", lambda e: xy_link.configure(fg="#E65100"))
        xy_link.bind("<Leave>", lambda e: xy_link.configure(fg="#FF6A00"))

        # 右侧：贡献者头像（横向排列）
        contrib_outer = tk.Frame(main_info, bg=Theme.BG_WHITE)
        contrib_outer.pack(side="right", fill="y", padx=(10, 0))

        tk.Label(contrib_outer, text="贡献者",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT).pack(pady=(0, 4))

        contributors = [
            ("CodeBuddy", "贡献者", None, "CB"),
            ("晟曦", "作者", self.PROJECT_DIR / "作者ico.jpg", None),
            ("Theresa", "贡献者", self.PROJECT_DIR / "贡献者3.jpg", None),
        ]

        contrib_frame = tk.Frame(contrib_outer, bg=Theme.BG_WHITE)
        contrib_frame.pack()

        for idx, item in enumerate(contributors):
            name = item[0]
            role = item[1]
            avatar_path = item[2]
            short_name = item[3] if len(item) > 3 else None  # 短名用于显示
            is_author = (role == "作者")
            ht = 1  # 所有贡献者边框一样大
            cw = 80 if is_author else 72
            cell = tk.Frame(contrib_frame, bg=Theme.BG_SECONDARY, bd=0,
                            highlightbackground=Theme.BORDER, highlightthickness=ht, width=cw)
            cell.grid(row=0, column=idx, padx=4, pady=2)
            cell.grid_propagate(False)

            # 头像（作者稍大）
            avatar_size = 48 if is_author else 40
            avatar_label = tk.Label(cell, width=avatar_size, height=avatar_size,
                                    bg=Theme.BG_SECONDARY)
            avatar_label.pack(pady=(4, 1))

            if avatar_path and avatar_path.exists():
                try:
                    img = Image.open(avatar_path).resize((avatar_size, avatar_size), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    avatar_label.configure(image=photo, width=avatar_size, height=avatar_size)
                    avatar_label.image = photo
                except Exception:
                    self._draw_default_avatar(avatar_label, avatar_size, short_name or name)
            else:
                self._draw_default_avatar(avatar_label, avatar_size, short_name or name)

            tk.Label(cell, text=short_name or name,
                     font=("Microsoft YaHei UI", 8, "bold"),
                     bg=Theme.BG_SECONDARY, fg=Theme.TEXT).pack(pady=(1, 0))

            role_color = Theme.ACCENT_DARK if role == "作者" else Theme.TEXT_SECOND
            tk.Label(cell, text=role,
                     font=("Microsoft YaHei UI", 7),
                     bg=Theme.BG_SECONDARY, fg=role_color).pack(pady=(0, 4))

        # 免费声明 + 闲鱼广告合并
        ad_frame = tk.Frame(frame, bg="#FFF8E1", bd=0,
                            highlightbackground="#FFB74D", highlightthickness=1)
        ad_frame.pack(fill="x", pady=(6, 4))
        tk.Label(ad_frame, text="本工具永久免费使用。\n\n如需：免运行自动签到（无需开电脑）/ 多账号稳定托管 / 或一对一配置支持\n\n可查看作者主页获取服务说明。",
                 font=("Microsoft YaHei UI", 9),
                 bg="#FFF8E1", fg="#1565C0",
                 wraplength=480, justify="center").pack(padx=10, pady=(8, 4))
        ad_link = tk.Label(ad_frame, text=">>> 逛逛闲鱼小店 >>>",
                           font=("Microsoft YaHei UI", 9, "bold"),
                           bg="#FFF8E1", fg="#FF6A00", cursor="hand2", underline=True)
        ad_link.pack(pady=(2, 6))
        ad_link.bind("<Button-1>", lambda e: webbrowser.open("https://m.tb.cn/h.i6sCzog?tk=8Tyx5ZUgbkv"))
        ad_link.bind("<Enter>", lambda e: ad_link.configure(fg="#E65100"))
        ad_link.bind("<Leave>", lambda e: ad_link.configure(fg="#FF6A00"))

        # 确认按钮
        btn = tk.Button(frame, text="👉哼，都不看看人家小店…算了，快进去吧🥺", command=self._close,
                        font=("Microsoft YaHei UI", 11, "bold"),
                        bg=Theme.ACCENT, fg="white", bd=0,
                        padx=24, pady=10, cursor="hand2",
                        activebackground=Theme.HOVER, activeforeground="white")
        btn.pack(pady=(8, 4))
        btn.bind("<Enter>", lambda e: btn.configure(bg=Theme.HOVER))
        btn.bind("<Leave>", lambda e: btn.configure(bg=Theme.ACCENT))

        # 免责声明（按钮下方）
        tk.Label(frame, text="本工具仅供学习交流使用，与米哈游官方无关。",
                 font=("Microsoft YaHei UI", 8),
                 bg=Theme.BG_WHITE, fg=Theme.TEXT_SECOND,
                 wraplength=480).pack(pady=(0, 2))

    def _close(self):
        self.destroy()

    def _draw_default_avatar(self, parent, size, name):
        """为没有头像文件的贡献者绘制默认头像"""
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        # 画圆形背景
        draw = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        for y in range(size):
            for x in range(size):
                dx, dy = x - size // 2, y - size // 2
                if dx * dx + dy * dy <= (size // 2) ** 2:
                    draw.putpixel((x, y), (91, 163, 217, 255))  # Theme.ACCENT

        # 在圆形上画首字母
        from PIL import ImageDraw, ImageFont
        text = name[0].upper() if name else "?"
        try:
            font = ImageFont.truetype("arial.ttf", size // 2)
        except Exception:
            font = ImageFont.load_default()

        d = ImageDraw.Draw(draw)
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (size - tw) // 2 - bbox[0]
        ty = (size - th) // 2 - bbox[1] - 2
        d.text((tx, ty), text, fill="white", font=font)

        photo = ImageTk.PhotoImage(draw)
        parent.configure(image=photo)
        parent.image = photo


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

def _center_window(win, w, h):
    """将窗口在屏幕正中央显示"""
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")


def main():
    root = tk.Tk()

    # 设置图标
    _set_icon(root)

    # 先隐藏主窗口，弹出公告
    root.withdraw()

    app = MiYoSheSignerApp(root)

    # 主窗口屏幕居中
    root.update_idletasks()
    _center_window(root, WINDOW_WIDTH, WINDOW_HEIGHT)

    # 弹出公告
    AboutDialog(root)

    # 公告关闭后显示主窗口
    root.deiconify()

    # 恢复自动签到状态
    app._restore_auto_sign()

    root.mainloop()


def _set_icon(root):
    """设置窗口图标"""
    try:
        # PyInstaller 打包后，资源在 _MEIPASS 临时目录
        if getattr(sys, 'frozen', False):
            _res_dir = Path(sys._MEIPASS)
        else:
            _res_dir = Path(__file__).parent

        # 优先使用 jpg 图片设置窗口图标
        icon_jpg = _res_dir / "ico.jpg"
        if icon_jpg.exists():
            img = Image.open(icon_jpg).resize((64, 64), Image.LANCZOS)
            _icon_photo = ImageTk.PhotoImage(img)
            root.iconphoto(False, _icon_photo)

        # Windows: 使用 ico 文件设置任务栏图标
        if sys.platform == "win32":
            import ctypes
            ico_path = _res_dir / "icon.ico"
            if ico_path.exists():
                try:
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("miyoushe.sign")
                    root.iconbitmap(str(ico_path))
                except Exception:
                    pass
    except Exception:
        pass


if __name__ == "__main__":
    main()
