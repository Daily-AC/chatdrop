import AppKit
import UniformTypeIdentifiers

@objc(ShareViewController)
final class ShareViewController: NSViewController {
    private let status = NSTextField(wrappingLabelWithString: "归入会话")
    private let detail = NSTextField(wrappingLabelWithString: "同一会话的多次导出可一起查询。")
    private let picker = ConversationPicker()
    private let save = NSButton(title: "保存", target: nil, action: nil)
    private var started = false

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 460, height: 265))
        let title = NSTextField(labelWithString: "ChatDrop")
        title.font = .systemFont(ofSize: 22, weight: .semibold)
        status.font = .systemFont(ofSize: 14, weight: .medium)
        detail.textColor = .secondaryLabelColor
        detail.isSelectable = true
        save.target = self
        save.action = #selector(receive)
        save.bezelStyle = .rounded
        save.keyEquivalent = "\r"
        let stack = NSStackView(views: [title, status, picker, detail, save])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: view.topAnchor, constant: 24),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: view.bottomAnchor, constant: -20)
        ])
        picker.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        preferredContentSize = view.frame.size
    }

    override func viewDidAppear() {
        super.viewDidAppear()
        guard !started else { return }
        started = true
        do { try picker.reload() }
        catch { detail.stringValue = error.localizedDescription }
        view.window?.makeFirstResponder(picker)
    }

    @objc private func receive() {
        let conversation: Conversation
        do { conversation = try picker.resolve() }
        catch { detail.stringValue = error.localizedDescription; return }
        save.isEnabled = false
        picker.isEnabled = false
        status.stringValue = "正在保存到“\(conversation.name)”…"
        let providers = (extensionContext?.inputItems as? [NSExtensionItem] ?? []).flatMap { $0.attachments ?? [] }
        guard !providers.isEmpty else { showResult([], errors: ["没有收到文件附件。"]); return }
        let group = DispatchGroup()
        let lock = NSLock()
        var saved: [URL] = []
        var errors: [String] = []
        for provider in providers {
            group.enter()
            let type = provider.registeredTypeIdentifiers.first { UTType($0)?.conforms(to: .zip) == true }
                ?? (provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) ? UTType.fileURL.identifier : nil)
                ?? provider.registeredTypeIdentifiers.first { UTType($0)?.conforms(to: .data) == true }
            guard let type else {
                lock.lock(); errors.append("附件不是文件。"); lock.unlock()
                group.leave()
                continue
            }
            let complete: (URL?, Error?) -> Void = { url, error in
                defer { group.leave() }
                do {
                    if let error { throw error }
                    guard let url else { throw InboxError.invalidFile }
                    let result = try Inbox().receive(url, conversation: conversation)
                    lock.lock(); saved.append(result); lock.unlock()
                } catch {
                    lock.lock(); errors.append(error.localizedDescription); lock.unlock()
                }
            }
            if type == UTType.fileURL.identifier {
                provider.loadItem(forTypeIdentifier: type, options: nil) { item, error in
                    let url = (item as? URL) ?? (item as? Data).flatMap { URL(dataRepresentation: $0, relativeTo: nil) }
                    complete(url, error)
                }
            } else {
                provider.loadFileRepresentation(forTypeIdentifier: type, completionHandler: complete)
            }
        }
        group.notify(queue: .main) { self.showResult(saved, errors: errors) }
    }

    private func showResult(_ saved: [URL], errors: [String]) {
        if errors.isEmpty {
            status.stringValue = "已保存 \(saved.count) 个 ZIP，路径已复制"
            detail.stringValue = "会话归属已保存，CLI 查询时会自动入库。"
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(saved.map(\.path).joined(separator: "\n"), forType: .string)
        } else {
            status.stringValue = saved.isEmpty ? "接收失败" : "已保存 \(saved.count) 个 ZIP，部分附件失败"
            detail.stringValue = errors.joined(separator: "\n")
        }
        save.title = "完成"
        save.action = #selector(done)
        save.isEnabled = true
    }

    @objc private func done() {
        extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
    }
}
