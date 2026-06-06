# 备选取字幕方式 · Bilibili 字幕提取油猴脚本

`scripts/fetch_bili.py` 是**首选**取字幕方式（命令行直接拉）。但 B 站 CC/AI 字幕只在登录态返回，
若你不方便提供 `SESSDATA` Cookie，可以用这个油猴脚本在网页上把字幕导出成 SRT/纯文本，再用
`--srt 文件路径` 传给脚本。

## 这是什么

「Bilibili Subtitle Extractor」(by Haleclipse & Zane, MIT)——在 B 站播放器里集成一个字幕列表面板，
支持 CC 字幕和 AI 字幕，能搜索、同步高亮、一键复制/下载 SRT 与纯文本。

## 安装（国内可直接访问 GreasyFork）

1. 浏览器装 Tampermonkey（油猴）扩展
2. 安装脚本：https://greasyfork.org/scripts/544280  （脚本页 → 安装）
   - 直链：https://update.greasyfork.org/scripts/544280/Bilibili%20Subtitle%20Extractor.user.js
3. 打开任意 `bilibili.com/video/*` 或 `bilibili.com/cheese/*` 页面，播放器下方弹幕列表区会多出「字幕列表」面板

## 用法

1. 打开目标视频，等「字幕列表」面板加载出字幕
2. 点右上角三个点菜单 → **下载 SRT 字幕**（或下载纯文本）
3. 把下载的 `.srt` 文件路径用 `--srt` 传给取数脚本：
   ```
   python scripts/fetch_bili.py <视频链接> --srt ~/Downloads/xxx_字幕.srt
   ```
   这样既能拿到字幕，又能拉到公开的播放/三连/粉丝数据。

## 拿 SESSDATA 的方式（用首选路径时）

登录 b站 → F12 开发者工具 → Application/应用 → Cookies → `https://www.bilibili.com` →
复制 `SESSDATA` 的值，作为 `--sessdata` 参数或环境变量 `BILI_SESSDATA`。
