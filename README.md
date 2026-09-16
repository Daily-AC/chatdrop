<p align="center">
  <img src="Resources/Brand/chatdrop-logo.png" width="112" alt="ChatDrop" />
</p>

<h1 align="center">ChatDrop</h1>
<p align="center"><strong>把选中的微信聊天，变成 AI 工具可查询的本地会话库。</strong></p>
<p align="center">
  <a href="https://github.com/Daily-AC/chatdrop/releases/latest">下载 Mac 版</a> ·
  简体中文 · <a href="README.en.md">English</a> ·
  <a href="docs/cli.md">CLI 文档</a> ·
  <a href="https://github.com/Daily-AC/chatdrop/issues">反馈问题</a>
</p>

客户在群里提过什么需求？上周讨论确定了哪些事？那段视频后来下载好了，能不能补进已有记录？

把需要的聊天分享给 ChatDrop，选好会话。之后，让具有终端权限的 AI 工具按会话、时间或关键词查询，随时回到原文和附件。

## 看看它怎么用

<table>
  <tr>
    <td align="center" width="55%"><img src="docs/images/app.jpg" width="480" alt="ChatDrop 原生 Mac 主窗口" /></td>
    <td align="center" width="45%"><img src="docs/images/conversation.jpg" width="392" alt="为导入的聊天指定会话名称" /></td>
  </tr>
  <tr>
    <td align="center">从微信分享，或直接导入 ZIP。</td>
    <td align="center">选择已有会话，或输入一个新名字。</td>
  </tr>
</table>

<sub>截图来自实际运行的 ChatDrop；“产品讨论群”为模拟名称。</sub>

## 能帮你做什么

- **把多次导出归到同一个会话。** 首次命名，以后直接选择；改名不会拆散历史。
- **重复导入时复用匹配消息。** 新导出中的图片、视频可以补齐旧记录缺失的附件。
- **让 agent 按需读取。** 按多个会话、时间段、发送者或关键词查询，返回 JSON、上下文和附件路径。
- **保留可以核对的原件。** ZIP、TXT 和消息来源留在本机，方便检查 AI 总结是否准确。

ChatDrop 接收你主动分享或导入的文件，不需要微信数据库密钥，也不会后台监控聊天。

## 下载与开始使用

**[下载最新 Mac 安装包](https://github.com/Daily-AC/chatdrop/releases/latest)**

| 当前版本 | 要求 |
| --- | --- |
| Mac 应用 | Apple Silicon（M 系列）；构建目标 macOS 14+，已在 macOS 26.6.2 实测 |
| CLI | Python 3.9+，无第三方 Python 依赖 |
| 其他平台 | Intel Mac、Windows、Linux 尚未完成完整支持与验证 |

### 1. 安装并启用分享入口

解压安装包，把 `ChatDrop.app` 放入“应用程序”，启动一次。

若微信菜单里没有 ChatDrop，在系统设置的共享扩展中启用它。首版未做 Apple 公证；首次打开被拦截时，可在 **系统设置 → 隐私与安全性** 中选择 **仍要打开**。

### 2. 分享一段聊天，指定会话

在微信中多选消息，选择 **转发到其他应用 → 选择电脑中的应用 → ChatDrop**。

输入或选择会话名称，点击保存。同一会话后续导出的内容，继续选择这个名称即可。应用也支持直接导入微信导出的 ZIP。

### 3. 让 AI 工具查询

在解压后的发布包目录中安装 CLI：

```bash
bash scripts/install-cli.sh
```

把 `~/.local/bin` 加入 `PATH`。如果你的 agent 有终端权限，就可以直接告诉它：

> 用 chatdrop 查看“产品讨论群”上周的消息，整理已经确定的决定和还没解决的问题，附上原始消息 ID。

也可以自己运行：

```bash
# 列出现有会话
chatdrop conversations

# 读取两个会话在指定日期范围内的全部消息
chatdrop search \
  --conversation '产品讨论群' \
  --conversation '设计沟通群' \
  --from 2026-09-01 --to 2026-09-16 --all

# 查关键词、上下文和附件
chatdrop search '上线' --conversation '产品讨论群'
chatdrop context '<消息 ID>' --radius 3
chatdrop attachments '<消息 ID>'
```

查询时会自动导入新收到的 ZIP。关键词可省略，日期包含首尾两天；默认分页，`--all` 返回全部匹配记录。详见 [CLI 文档](docs/cli.md)。

## 重复导入和附件补齐

例如，第一次分享了 9 条消息，其中一条视频尚未下载。下载完成后，只重新分享这条视频，并选择同一个会话：

| | 首次导入 | 补导视频后 |
| --- | ---: | ---: |
| 会话消息数 | 9 | 9 |
| 缺失附件数 | 1 | 0 |

这个场景已用实际导出验证。匹配依据是会话、发送者、时间、正文及已有附件内容，**不是微信原生消息 ID**。同一份导出中的重复消息会保留出现次数；分别导出的、同一分钟内完全相同的消息仍可能存在歧义。原始文件始终保留，具体规则见 [存储与去重说明](docs/architecture.md)。

## 常见问题

**会自动读取全部微信聊天吗？**

不会。只处理你主动分享或导入的 ZIP。

**聊天会上传到云端吗？**

ChatDrop 本身不上传聊天。你让外部 AI 工具读取后，按该工具的数据处理方式执行。

**为什么视频或图片显示缺失？**

微信未下载的媒体可能不会包含在导出 ZIP 中。先下载，再把对应消息分享给同一个会话，应用会尝试补齐。

**升级后分享菜单还是旧图标？**

用 `⌘Q` 完全退出微信再打开；只关闭窗口不会结束进程。

**能自动识别群名吗？**

当前观察到的导出没有稳定群 ID。会话名称由你指定，是本地归档标签。

## 开发与反馈

需要 macOS Command Line Tools、Swift 和 Python 3.9+：

```bash
bash scripts/build.sh
python3 -m unittest discover -s tests -v
```

输出位于 `build/ChatDrop.app`。[参与贡献](CONTRIBUTING.md)时请使用模拟或脱敏样本，不要上传私人聊天、数据库或凭据。

如果 ChatDrop 对你有用，欢迎点一个 Star，也欢迎反馈你遇到的导出格式和使用问题。

[MIT 许可](LICENSE)
