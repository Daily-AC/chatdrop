<p align="center">
  <img src="Resources/Brand/chatdrop-logo.png" width="144" alt="ChatDrop 标志" />
</p>

# ChatDrop

**把你主动分享的微信聊天，整理成 AI 工具可以持续查询的本地会话库。**

[下载 Mac 版](https://github.com/Daily-AC/chatdrop/releases/latest) · [English](README.md) · [CLI 用法](docs/cli.md) · [存储与去重规则](docs/architecture.md)

从微信分享一段聊天，选择它属于哪个会话。之后可以让 agent 按会话、时间和
关键词查记录。再次导出时复用匹配消息，已经下载的图片或视频可以补齐旧记录。

## 已有能力

- 原生 macOS 分享入口，接收微信导出的 ZIP。
- 创建和复用会话名称，改名后保留原来的归属。
- 增量导入、消息匹配和缺失附件补齐。
- JSON CLI，支持多会话、时间范围、关键词、发送者筛选，以及上下文和附件路径。
- 原始 ZIP、TXT 和导入来源留在本机，方便核对。

应用只读取你主动分享或导入的 ZIP，不需要读取微信数据库或获取解密密钥。

## 系统要求

目前只有 **macOS 版**，首个安装包为 **Apple Silicon（arm64）**。构建目标为
macOS 14 及以上，已在 macOS 26.6.2 实测；更早版本和 Intel Mac 尚未完成运行验证。
Windows、Linux、iOS、Android 暂无安装包。

CLI 需要 Python 3.9 及以上，无第三方 Python 依赖。当前文件锁和默认目录仍按
Unix/macOS 实现，尚不能宣称跨平台支持。

## 开始使用

1. 下载 [Apple Silicon 安装包](https://github.com/Daily-AC/chatdrop/releases/latest)，解压后把 `ChatDrop.app` 放入“应用程序”，启动一次。
2. 如菜单中没有 ChatDrop，在系统设置的共享扩展中启用它。
3. 微信多选消息，选择 **转发到其他应用 → 选择电脑中的应用 → ChatDrop**。
4. 在面板中选择已有会话或输入新名字，点击保存。
5. 在源码或发布包目录中安装 CLI：

```bash
bash scripts/install-cli.sh
```

把 `~/.local/bin` 加到 `PATH` 后即可使用：

```bash
chatdrop conversations

chatdrop search \
  --conversation '项目群' \
  --conversation '客户群' \
  --from 2026-09-01 --to 2026-09-16 --all

chatdrop search '上线' --conversation '项目群'
chatdrop context '<消息 ID>' --radius 3
chatdrop attachments '<消息 ID>'
```

查询时自动导入新收到的 ZIP。关键词可省略；日期包含首尾两天。默认分页，
`--all` 返回全部匹配记录，结果会给出总数和下一页位置。

可以直接告诉具有终端权限的 agent：

> 用 chatdrop 查看项目群上周的消息，整理已确定的决定和未解决的问题，并附上消息 ID。

ChatDrop 本身不把聊天发送到 AI 服务。你让外部 AI 工具读取后，按该工具的数据处理方式执行。

## 已知边界

- 导出没有稳定群 ID 或消息 ID；会话名称是你在本地指定的归属。
- 去重结合会话、发送者、时间、正文和已有附件内容。同一份导出中的重复消息保留出现次数；
  分别导出的、同一分钟内完全相同的消息仍可能无法准确区分。
- 微信里尚未下载的媒体可能不会包含在 ZIP 中。应用会标记缺失，后续匹配导入可以补齐。
- 保留原始文件，目前不自动删除历史。
- 首版使用 ad-hoc 签名，未做公证。首次打开被拦截时，可能需要在系统设置的
  **隐私与安全性** 中选择 **仍要打开**。

## 开发

```bash
bash scripts/build.sh
python3 -m unittest discover -s tests -v
```

需要 macOS Command Line Tools、Swift 和 Python 3.9+。输出位于 `build/ChatDrop.app`。

反馈问题请使用模拟或脱敏样本，不要上传私人聊天、数据库或凭据。

## 致谢与许可

感谢 [Dukou](https://github.com/qzz0518/Dukou) 和
[Dihua](https://github.com/ZHlovecat/dihua) 展示了微信原生导出与系统分享流程的用途。

采用 [MIT 许可](LICENSE)。
