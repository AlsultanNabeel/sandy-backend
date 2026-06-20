import SwiftUI

struct ChatView: View {
    @EnvironmentObject var state: AppState
    @State private var messages: [ChatMessage] = []
    @State private var input = ""
    @State private var sending = false

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(messages) { m in
                            messageRow(m).id(m.id)
                        }
                    }
                    .padding()
                }
                .onChange(of: messages.count) { _ in
                    if let last = messages.last {
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
            }

            HStack(spacing: 8) {
                TextField("اكتب لساندي…", text: $input, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                Button(action: send) {
                    Image(systemName: sending ? "hourglass" : "paperplane.fill")
                }
                .disabled(sending || input.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding()
        }
        .navigationTitle("ساندي")
    }

    @ViewBuilder
    private func messageRow(_ m: ChatMessage) -> some View {
        HStack {
            if m.role == "user" { Spacer(minLength: 40) }
            Text(m.text)
                .padding(10)
                .background(m.role == "user" ? Color.blue.opacity(0.18) : Color.gray.opacity(0.15))
                .cornerRadius(14)
            if m.role != "user" { Spacer(minLength: 40) }
        }
    }

    private func send() {
        let text = input.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        input = ""; sending = true
        messages.append(ChatMessage(role: "user", text: text))
        Task {
            do {
                let reply = try await state.api.sendMessage(text)
                messages.append(ChatMessage(role: "sandy", text: reply))
            } catch {
                messages.append(ChatMessage(role: "sandy", text: "⚠️ \(error.localizedDescription)"))
            }
            sending = false
        }
    }
}
