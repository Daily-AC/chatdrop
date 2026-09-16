import AppKit

final class ConversationPicker: NSComboBox {
    private var conversations: [Conversation] = []
    private var labels: [String] = []

    init() {
        super.init(frame: .zero)
        placeholderString = "选择已有会话，或输入新名字"
        isEditable = true
        completes = true
        numberOfVisibleItems = 7
        setAccessibilityLabel("归入会话")
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func reload() throws {
        conversations = try ConversationStore().list()
        labels = conversations.map { conversation in
            let count = conversations.filter { $0.name == conversation.name }.count
            return count > 1 ? "\(conversation.name) (\(conversation.id.prefix(8)))" : conversation.name
        }
        removeAllItems()
        addItems(withObjectValues: labels)
    }

    func resolve() throws -> Conversation {
        let text = stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if let index = labels.firstIndex(of: text) {
            return try ConversationStore().select(name: conversations[index].name, id: conversations[index].id)
        }
        return try ConversationStore().select(name: text)
    }

}
