import AppKit
import UniformTypeIdentifiers

@main
struct Main {
    static func main() {
        let args = Array(CommandLine.arguments.dropFirst())
        if let command = args.first, !command.hasPrefix("-psn_"), command != "--share-test" {
            do {
                let inbox = Inbox()
                switch command {
                case "latest": print(try inbox.latest().path)
                case "path": print(inbox.root.path)
                case "list":
                    let entries = try inbox.entries().map { receipt, url in
                        ["id": receipt.id, "importedAt": receipt.importedAt, "name": receipt.originalName, "path": url.path]
                    }
                    let data = try JSONSerialization.data(withJSONObject: entries, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
                    print(String(decoding: data, as: UTF8.self))
                case "import":
                    guard args.count == 2 else { throw InboxError.invalidFile }
                    print(try inbox.receive(URL(fileURLWithPath: args[1])).path)
                case "--probe":
                    guard args.count == 2 else { throw InboxError.invalidFile }
                    _ = NSApplication.shared
                    for service in NSSharingService.sharingServices(forItems: [URL(fileURLWithPath: args[1])]) {
                        print(service.title)
                    }
                default: print("chatdrop latest | list | path | import <file.zip>")
                }
            } catch {
                FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
                exit(1)
            }
            return
        }
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSSharingServiceDelegate {
    private var window: NSWindow!
    private let status = NSTextField(wrappingLabelWithString: "从微信的“转发到其他应用”中选择 ChatDrop。")
    private var service: NSSharingService?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出 ChatDrop", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let item = NSMenuItem()
        item.submenu = appMenu
        menu.addItem(item)
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 270),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "ChatDrop"
        let title = NSTextField(labelWithString: "聊天记录，交给终端。")
        title.font = .systemFont(ofSize: 25, weight: .semibold)
        let subtitle = NSTextField(wrappingLabelWithString: "分享时选择会话，记录保存在本机。\n终端运行 chatdrop，即可按会话和时间查询。")
        subtitle.textColor = .secondaryLabelColor
        status.isSelectable = true
        let buttons = NSStackView(views: [button("打开收件箱", #selector(openInbox)),
                                         button("复制最新路径", #selector(copyLatest)),
                                         button("导入 ZIP…", #selector(importFile))])
        buttons.spacing = 8
        let stack = NSStackView(views: [title, subtitle, buttons, status])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 28)
        ])
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if CommandLine.arguments.count == 3, CommandLine.arguments[1] == "--share-test" {
            let url = URL(fileURLWithPath: CommandLine.arguments[2])
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                self.service = NSSharingService.sharingServices(forItems: [url]).first { $0.title == "ChatDrop" }
                self.service?.delegate = self
                self.service?.perform(withItems: [url])
                if self.service == nil { self.status.stringValue = "系统分享菜单未发现 ChatDrop。" }
            }
        }
    }
    private func button(_ title: String, _ action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        return button
    }
    @objc private func openInbox() {
        do {
            try FileManager.default.createDirectory(at: Inbox().root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            NSWorkspace.shared.open(Inbox().root)
        } catch { status.stringValue = error.localizedDescription }
    }
    @objc private func copyLatest() {
        do {
            let url = try Inbox().latest()
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(url.path, forType: .string)
            status.stringValue = "最新 ZIP 的路径已复制。"
        } catch { status.stringValue = error.localizedDescription }
    }
    @objc private func importFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.zip]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { receive(url) }
    }
    private func receive(_ url: URL) {
        do {
            let picker = ConversationPicker()
            try picker.reload()
            picker.frame = NSRect(x: 0, y: 0, width: 360, height: 28)
            let alert = NSAlert()
            alert.messageText = "归入会话"
            alert.informativeText = "选择已有会话，或输入一个新名字。"
            alert.accessoryView = picker
            alert.addButton(withTitle: "保存")
            alert.addButton(withTitle: "取消")
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            let conversation = try picker.resolve()
            let saved = try Inbox().receive(url, conversation: conversation)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(saved.path, forType: .string)
            status.stringValue = "已保存，路径已复制。"
        } catch { status.stringValue = error.localizedDescription }
    }
    func application(_ application: NSApplication, open urls: [URL]) { urls.forEach(receive) }
    func sharingService(_ sharingService: NSSharingService, didFailToShareItems items: [Any], error: Error) {
        status.stringValue = error.localizedDescription
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
