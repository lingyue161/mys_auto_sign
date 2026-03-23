# 米游社自动签到工具 v5.0

基于 Python + Tkinter 的米游社多游戏自动签到工具，支持 GUI 图形界面。

## 功能特性

- **扫码登录** — 通过米游社 App 扫描二维码登录，自动获取并持久化凭证
- **多账号管理** — 支持添加、删除多个账号，凭证自动刷新
- **多游戏签到** — 支持崩坏3、原神、崩坏：星穹铁道、绝区零等游戏
- **游戏勾选** — 可自由勾选/取消要签到的游戏，偏好按账号单独保存
- **签到状态查询** — 点击按钮查询各游戏的签到状态（已签/未签、累计天数、今日奖励）
- **一键签到** — 对当前选中账号执行签到，或一键签到所有账号
- **每天自动签到** — 开启后每天 00:00:05 自动执行签到（需保持程序运行）
- **天空蓝主题** — 清爽的天空蓝 UI 界面
- **运行日志** — 底部实时显示运行日志

## 支持的游戏

| 游戏 | 状态 |
|------|------|
| 崩坏学园2 | ✅ |
| 崩坏3 | ✅ |
| 未定事件簿 | ✅ |
| 原神 | ✅ |
| 崩坏：星穹铁道 | ✅ |
| 绝区零 | ✅ |

## 安装

```bash
# 克隆项目
git clone https://github.com/lingyue161/mys_auto_sign.git
cd mys_auto_sign

# 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

## 使用方法

### GUI 模式（推荐）

```bash
python main.py
```

或显式指定：

```bash
python main.py --gui
```

### 命令行模式

```bash
python main.py --cli
```

### 批量签到（无界面）

```bash
python main.py --sign-all
```

### 下载 exe 免安装版

前往 [Releases](https://github.com/lingyue161/mys_auto_sign/releases) 页面下载最新版本。

## 操作指南

1. **添加账号**：点击「扫码添加」，用米游社 App 扫描二维码
2. **选择账号**：在账号列表中点击选中（选中行高亮 + ▶ 标记）
3. **勾选游戏**：在右侧面板勾选要签到的游戏
4. **查询状态**：点击「查询签到状态」查看各游戏签到详情
5. **手动签到**：点击「一键签到」对当前账号签到
6. **全部签到**：点击「签到所有账号」对所有已保存账号签到
7. **自动签到**：勾选「每天自动签到」开启定时签到

## 项目结构

```
mys_auto_sign/
├── main.py              # 入口文件（支持 --gui/--cli/--sign-all）
├── mys_signer.py        # 核心签到模块（登录、签到、账号管理）
├── mys_gui.py           # GUI 界面（天空蓝主题）
├── ico.jpg              # 窗口图标
├── requirements.txt     # Python 依赖
├── README.md
├── config/              # 配置目录
└── data/                # 数据目录
    ├── accounts.json    # 账号持久化（凭证信息）
    └── game_prefs.json  # 游戏勾选偏好
```

## 依赖

- Python 3.8+
- requests
- qrcode
- Pillow

## 注意事项

- 签到功能需要有效的米游社账号凭证
- 凭证有过期时间，程序会自动刷新，但如果长时间未使用可能需要重新登录
- 自动签到需要保持程序运行

## 免责声明

本工具仅供学习交流使用，与米哈游官方无关。

## 作者

**晟曦**

- GitHub: [lingyue161](https://github.com/lingyue161)
- 抖音: [点击访问](https://v.douyin.com/A-uK27ODbFc/)

## 贡献者

| 贡献者 | 角色 |
|--------|------|
| 晟曦 | 作者 |
| CodeBuddy | 贡献者 |
| Theresa-0328 | 贡献者 |

## 贡献

欢迎提交 Issue 和 Pull Request！

## License

MIT
