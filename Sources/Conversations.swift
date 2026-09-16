import Foundation
import Darwin

struct Conversation: Codable {
    let id: String
    var name: String
    let createdAt: String
    var updatedAt: String
    var lastUsedAt: String
}

private struct ConversationCatalog: Codable {
    var schemaVersion = 1
    var conversations: [Conversation] = []
}

struct ConversationStore {
    let root: URL
    init(root: URL = Inbox().root) { self.root = root }

    private func locked<T>(_ operation: (inout ConversationCatalog) throws -> T, write: Bool) throws -> T {
        let fm = FileManager.default
        try fm.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let descriptor = Darwin.open(root.appendingPathComponent(".conversations.lock").path, O_CREAT | O_RDWR, 0o600)
        guard descriptor >= 0 else { throw failure("无法打开会话目录。") }
        defer { Darwin.close(descriptor) }
        guard flock(descriptor, LOCK_EX) == 0 else { throw failure("无法锁定会话目录。") }
        defer { flock(descriptor, LOCK_UN) }
        let file = root.appendingPathComponent("conversations.json")
        var catalog = fm.fileExists(atPath: file.path)
            ? try JSONDecoder().decode(ConversationCatalog.self, from: Data(contentsOf: file))
            : ConversationCatalog()
        guard catalog.schemaVersion == 1 else { throw failure("请更新 ChatDrop 后读取会话目录。") }
        let result = try operation(&catalog)
        if write {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
            try encoder.encode(catalog).write(to: file, options: .atomic)
            try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        }
        return result
    }

    func list() throws -> [Conversation] {
        try locked({ $0.conversations.sorted { $0.lastUsedAt > $1.lastUsedAt } }, write: false)
    }

    func select(name: String, id: String? = nil) throws -> Conversation {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines).precomposedStringWithCanonicalMapping
        guard !name.isEmpty, name.unicodeScalars.count <= 120,
              !name.contains("\n"), !name.contains("\r"), !name.contains("\0") else {
            throw failure("请输入 1–120 个字符的会话名。")
        }
        return try locked({ catalog in
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let now = formatter.string(from: Date())
            let matches = catalog.conversations.indices.filter { id == nil ? catalog.conversations[$0].name == name : catalog.conversations[$0].id == id }
            guard matches.count <= 1 else { throw failure("有多个同名会话，请从列表中选择。") }
            if let index = matches.first {
                catalog.conversations[index].lastUsedAt = now
                return catalog.conversations[index]
            }
            guard id == nil else { throw failure("所选会话不存在，请重新选择。") }
            let item = Conversation(id: UUID().uuidString.lowercased(), name: name,
                                    createdAt: now, updatedAt: now, lastUsedAt: now)
            catalog.conversations.append(item)
            return item
        }, write: true)
    }

    private func failure(_ description: String) -> NSError {
        NSError(domain: "ChatDrop", code: 1, userInfo: [NSLocalizedDescriptionKey: description])
    }
}
