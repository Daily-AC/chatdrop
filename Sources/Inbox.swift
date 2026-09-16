import Foundation

struct Receipt: Codable {
    let id: String
    let importedAt: String
    let originalName: String
    let fileName: String
    let bytes: Int64
    var conversationID: String? = nil
}

enum InboxError: LocalizedError {
    case invalidFile, empty
    var errorDescription: String? {
        switch self {
        case .invalidFile: return "请选择 ZIP 文件。"
        case .empty: return "收件箱里还没有 ZIP。"
        }
    }
}

struct Inbox {
    let root: URL
    init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("ChatDrop", isDirectory: true)
    }

    // Copy before returning from the item-provider callback: its URL is temporary.
    func receive(_ source: URL, conversation: Conversation? = nil) throws -> URL {
        let fm = FileManager.default
        let scoped = source.startAccessingSecurityScopedResource()
        defer { if scoped { source.stopAccessingSecurityScopedResource() } }
        let values = try source.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard source.isFileURL, values.isRegularFile == true, values.isSymbolicLink != true else {
            throw InboxError.invalidFile
        }
        let handle = try FileHandle(forReadingFrom: source)
        defer { try? handle.close() }
        let signature = try handle.read(upToCount: 4) ?? Data()
        guard [Data([0x50, 0x4b, 3, 4]), Data([0x50, 0x4b, 5, 6]), Data([0x50, 0x4b, 7, 8])].contains(signature) else {
            throw InboxError.invalidFile
        }
        try fm.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let now = formatter.string(from: Date())
        let id = now.replacingOccurrences(of: ":", with: "-") + "-" + UUID().uuidString.lowercased()
        let staging = root.appendingPathComponent("." + id, isDirectory: true)
        let destination = root.appendingPathComponent(id, isDirectory: true)
        try fm.createDirectory(at: staging, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? fm.removeItem(at: staging) }
        // A fixed name avoids turning a sender-controlled filename into a path.
        let archive = staging.appendingPathComponent("archive.zip")
        try fm.copyItem(at: source, to: archive)
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: archive.path)
        let attributes = try fm.attributesOfItem(atPath: archive.path)
        let receipt = Receipt(id: id, importedAt: now, originalName: source.lastPathComponent,
                              fileName: "archive.zip", bytes: (attributes[.size] as? NSNumber)?.int64Value ?? 0,
                              conversationID: conversation?.id)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let manifest = staging.appendingPathComponent("receipt.json")
        try encoder.encode(receipt).write(to: manifest, options: .atomic)
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: manifest.path)
        try fm.moveItem(at: staging, to: destination)
        return destination.appendingPathComponent(receipt.fileName)
    }

    func entries() throws -> [(Receipt, URL)] {
        let fm = FileManager.default
        guard fm.fileExists(atPath: root.path) else { return [] }
        return try fm.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isDirectoryKey], options: .skipsHiddenFiles)
            .compactMap { directory in
                guard let data = try? Data(contentsOf: directory.appendingPathComponent("receipt.json")),
                      let receipt = try? JSONDecoder().decode(Receipt.self, from: data),
                      receipt.fileName == "archive.zip", receipt.id == directory.lastPathComponent,
                      fm.fileExists(atPath: directory.appendingPathComponent("archive.zip").path) else { return nil }
                return (receipt, directory.appendingPathComponent("archive.zip"))
            }
            .sorted { $0.0.importedAt > $1.0.importedAt }
    }
    func latest() throws -> URL {
        guard let entry = try entries().first else { throw InboxError.empty }
        return entry.1
    }
}
