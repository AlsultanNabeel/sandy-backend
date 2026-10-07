import SwiftUI

/// شاشة المحادثة مع ساندي.
///
/// إصلاحات الأخطاء (طلب المالك):
///  1) لوحة المفاتيح ما كانت تنزل — صار فيها: سحب لإخفائها، نقر بأي مكان يخفيها،
///     وزر "تم" بشريط فوق الكيبورد.
///  2) زر Return كان يضيف سطر فاضي ويرسل — صار نطمّن (trim) قبل أي إرسال،
///     وما نضيف سطر فاضي ولا نرسل لو النص فاضي.
///  3) رسائل فاضية كانت توصل الباك-إند — صار الإرسال مستحيل لو النص فاضي:
///     الزر معطّل و send() يرجع مبكّرًا.
///
/// + حيوية: ظهور الفقاعات بحركة (scale+opacity)، مؤشّر "ساندي تكتب…" بنقاط
/// متحرّكة أثناء الانتظار، وفقاعات بألوان/حواف ساندي مع أفاتار صغير لها،
/// والأخطاء تظهر كـ SandyNotice دافئ بدل فقاعة حمراء.
struct ChatView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    /// مصدر الحقيقة للمحادثة: الرسائل + الإرسال + الحفظ + سجل السيشنات، مستقل عن
    /// دورة حياة الشاشة (التنقّل بين التبويبات ما يمسح المحادثة، وتُحفظ تلقائيًا).
    @StateObject private var store = ChatStore()

    @State private var input = ""
    /// عرض ورقة سجل المحادثات.
    @State private var showHistory = false

    /// التحكم بتركيز حقل الإدخال — لإخفاء/إظهار الكيبورد برمجيًا.
    @FocusState private var inputFocused: Bool

    /// محرّك الصوت — مكالمة حيّة + قراءة ردود الكتابة بصوت ساندي.
    @StateObject private var speech = SpeechManager()
    /// Photos and documents picked for the next message.
    @StateObject private var composer = AttachmentComposer()
    /// هل ساندي تقرأ ردود الكتابة بصوت؟ (يتحكم فيه زر السمّاعة، محفوظ).
    @AppStorage("sandy_voice_replies") private var voiceReplies = true
    /// عرض شاشة المكالمة الصوتية الحيّة.
    @State private var showLive = false
    /// The field holds the last message being edited; sending replaces it and its reply.
    @State private var editingLast = false
    /// A message opened for picking part of its text.
    @State private var selecting: SelectableMessage?

    /// لغة التعرّف/الصوت تتبع لغة التطبيق.
    private var voiceLocaleID: String { lang.lang == .ar ? "ar-SA" : "en-US" }

    /// النص بعد التنظيف — مصدر وحيد للحقيقة لتعطيل الزر ومنع الإرسال الفاضي.
    private var trimmedInput: String {
        input.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// هل يُسمح بالإرسال الآن؟ (مو مرسل حاليًا + في نص فعلي).
    private var canSend: Bool {
        !store.sending && !composer.busy && (!trimmedInput.isEmpty || !composer.ready.isEmpty)
    }

    var body: some View {
        VStack(spacing: 0) {
            messageList
            inputBar
        }
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها هون (طبقة مهدورة).
        .navigationTitle(lang.s("chat.title"))
        .navigationBarTitleDisplayMode(.inline)
        // إصلاح (1): شريط فوق الكيبورد فيه زر "تم" لإخفائها يدويًا.
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button(lang.s("common.done")) { dismissKeyboard() }
                    .font(Theme.Typography.button)
                    .foregroundColor(Theme.Colors.accent)
            }
            // سجل المحادثات — يفتح قائمة السيشنات السابقة + بحث.
            ToolbarItem(placement: .navigationBarLeading) {
                Button { showHistory = true } label: {
                    Image(systemName: "clock.arrow.circlepath")
                        .foregroundColor(Theme.Colors.accent)
                }
                .accessibilityLabel(lang.s("chat.history"))
            }
            ToolbarItemGroup(placement: .navigationBarTrailing) {
                // محادثة جديدة — يحفظ الحالية بالسجل ويبدأ نظيفة.
                Button { store.startNew(api: state.api) } label: {
                    Image(systemName: "square.and.pencil")
                        .foregroundColor(Theme.Colors.accent)
                }
                .accessibilityLabel(lang.s("chat.new"))
                // زر صوت ساندي — يكتم/يشغّل قراءتها لردودها.
                Button {
                    voiceReplies.toggle()
                    if !voiceReplies { speech.stopSpeaking() }
                } label: {
                    Image(systemName: voiceReplies ? "speaker.wave.2.fill" : "speaker.slash.fill")
                        .foregroundColor(Theme.Colors.accent)
                }
                .accessibilityLabel(lang.s(voiceReplies ? "chat.speakerOn" : "chat.speakerOff"))
            }
        }
        .task { await store.bootstrap(api: state.api) }
        // نوقف صوت ساندي عند مغادرة الشاشة.
        .onDisappear { speech.stopSpeaking() }
        .sheet(item: $selecting) { m in
            SelectTextSheet(text: m.text).environmentObject(lang)
        }
        .onAppear {
            store.userName = state.onboarding.preferredName.isEmpty ? state.onboarding.name
                                                                   : state.onboarding.preferredName
        }
        .sheet(isPresented: $showHistory) {
            ChatHistorySheet(store: store)
                .environmentObject(state).environmentObject(lang)
        }
        // شاشة المكالمة الصوتية الحيّة (جيميني لايف — محرّكها الخاص).
        .sheet(isPresented: $showLive) {
            LiveVoiceView()
                .environmentObject(state)
                .environmentObject(lang)
                .environment(\.layoutDirection, lang.lang.layoutDirection)
        }
    }

    // MARK: - قائمة الرسائل

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                // Lazy: a long thread builds only the rows on screen.
                LazyVStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    if store.messages.count >= 2 { OneTimeTip(tip: MessageActionsTip()) }
                    ForEach(store.messages) { m in
                        messageRow(m)
                            // حيوية: كل فقاعة تظهر بتكبير لطيف + تلاشٍ.
                            .transition(
                                .scale(scale: 0.85, anchor: .bottom)
                                    .combined(with: .opacity)
                            )
                    }

                    // حيوية: مؤشّر "ساندي تكتب…" بنقاط متحرّكة أثناء الانتظار.
                    if store.sending {
                        TypingIndicator(activity: store.activity)
                            .id(Self.typingAnchorID)
                            .transition(.scale(scale: 0.85, anchor: .bottomLeading).combined(with: .opacity))
                    }

                    // خطأ دافئ بصوت ساندي بدل فقاعة حمراء.
                    if !store.errorMessage.isEmpty {
                        SandyNotice(store.errorMessage, kind: .gentleWarning)
                            .transition(.opacity)
                    }
                }
                .padding(Theme.Spacing.md)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            // إصلاح (1): سحب القائمة يخفي الكيبورد بسلاسة.
            .scrollDismissesKeyboard(.interactively)
            // حيوية: حركة نابضة عند تغيّر عدد الرسائل أو ظهور مؤشّر الكتابة.
            .animation(Animation.spring(response: 0.4, dampingFraction: 0.8).reduced, value: store.messages.count)
            .animation(Animation.spring(response: 0.4, dampingFraction: 0.8).reduced, value: store.sending)
            .animation(Animation.easeInOut(duration: 0.25).reduced, value: store.errorMessage)
            // إصلاح (1): نقر بأي مكان بالخلفية/القائمة يخفي الكيبورد.
            .contentShape(Rectangle())
            .onTapGesture { dismissKeyboard() }
            .onChange(of: store.messages.count) {
                scrollToBottom(proxy)
            }
            // Keep the streaming bubble in view as it grows. No animation: this
            // fires per chunk, and stacked springs would lag behind the text.
            .onChange(of: store.messages.last?.text) {
                if !store.sending, let last = store.messages.last {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
            .onChange(of: store.sending) { _, isSending in
                // ننزل لمؤشّر الكتابة لما يظهر.
                if isSending { scrollToBottom(proxy) }
            }
        }
    }

    /// ينزّل العرض لآخر عنصر (مؤشّر الكتابة لو شغّال، وإلا آخر رسالة).
    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        withAnimation(Animation.spring(response: 0.4, dampingFraction: 0.8).reduced) {
            if store.sending {
                proxy.scrollTo(Self.typingAnchorID, anchor: .bottom)
            } else if let last = store.messages.last {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }

    // MARK: - شريط الإدخال

    private var inputBar: some View {
        VStack(spacing: Theme.Spacing.xs) {
            if editingLast { editBanner }
            if !composer.items.isEmpty { AttachmentStrip(composer: composer) }
            inputRow
        }
        .padding(Theme.Spacing.md)
        // شريط إدخال زجاجي مموّه مع خيط أزرق رفيع فوقه.
        .background(
            Rectangle()
                .fill(.ultraThinMaterial)
                .ignoresSafeArea(edges: .bottom)
                .overlay(alignment: .top) {
                    Rectangle().fill(Theme.Colors.accent.opacity(0.18)).frame(height: 1)
                }
        )
    }

    private var editBanner: some View {
        HStack {
            Label(lang.s("chat.editing"), systemImage: "pencil")
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
            Spacer()
            Button(lang.s("chat.cancelEdit")) {
                editingLast = false
                input = ""
            }
            .font(Theme.Typography.caption)
            .foregroundColor(Theme.Colors.accent)
        }
    }

    private var inputRow: some View {
        HStack(alignment: .bottom, spacing: Theme.Spacing.sm) {
            AttachButton(composer: composer)
            liveCallButton

            TextField(lang.s("chat.placeholder"), text: $input, axis: .vertical)
                .focused($inputFocused)
                .font(Theme.Typography.body)
                .lineLimit(1...5)
                .padding(.vertical, Theme.Spacing.sm)
                .padding(.horizontal, Theme.Spacing.md)
                .background(Theme.Colors.surface)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.bubble, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.Radius.bubble, style: .continuous)
                        .stroke(Theme.Colors.border, lineWidth: 1)
                )
                // إصلاح (2): Return (submit) ما يضيف سطر فاضي ولا يرسل لو النص فاضي —
                // نطمّن أولًا ثم نرسل فقط لو في نص فعلي.
                .onSubmit { handleReturn() }

            if store.replying {
                stopButton
            } else {
                sendButton
            }
        }
    }

    /// While a reply is coming: stops it, keeping what already arrived.
    private var stopButton: some View {
        Button { store.stop(api: state.api) } label: {
            ZStack {
                Circle()
                    .fill(Theme.Colors.accent)
                    .frame(width: ChatMetrics.control, height: ChatMetrics.control)
                Image(systemName: "stop.fill")
                    .scaledFont(Theme.Icon.sm, weight: .semibold)
                    .foregroundColor(Theme.Colors.onAccent)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(lang.s("a11y.stop"))
    }

    /// Copy, share and pick text on every message; write the last reply again; edit the
    /// last line of yours.
    @ViewBuilder
    private func menu(for m: ChatMessage) -> some View {
        Button { UIPasteboard.general.string = m.text } label: {
            Label(lang.s("chat.copy"), systemImage: "doc.on.doc")
        }
        ShareLink(item: m.text) { Label(lang.s("chat.share"), systemImage: "square.and.arrow.up") }
        Button { selecting = SelectableMessage(text: m.text) } label: {
            Label(lang.s("chat.selectText"), systemImage: "selection.pin.in.out")
        }
        if !store.replying, !store.stopping, m.role == "sandy", m.id == store.messages.last?.id {
            Button { regenerate() } label: {
                Label(lang.s("chat.regenerate"), systemImage: "arrow.clockwise")
            }
        }
        if !store.replying, !store.stopping, m.role == "user",
           m.id == store.messages.last(where: { $0.role == "user" })?.id {
            Button {
                input = m.text
                editingLast = true
                inputFocused = true
            } label: {
                Label(lang.s("chat.editMessage"), systemImage: "pencil")
            }
        }
    }

    /// One message: its bubble with the long-press menu, and «أعد المحاولة» under a failed one.
    @ViewBuilder
    private func messageRow(_ m: ChatMessage) -> some View {
        // Equatable row: a streamed chunk re-renders only the growing bubble.
        ChatBubbleRow(isUser: m.role == "user", text: m.text, failed: m.failed, attachments: m.attachments)
            .equatable()
            .contextMenu { menu(for: m) }
            .accessibilityAction(named: lang.s("chat.copy")) { UIPasteboard.general.string = m.text }
            .id(m.id)
        if m.failed { retryButton(m) }
    }

    /// Under a line that did not go through.
    private func retryButton(_ m: ChatMessage) -> some View {
        HStack {
            Spacer()
            Button {
                speak { await store.retry(api: state.api, m) }
            } label: {
                Label(lang.s("chat.retry"), systemImage: "arrow.clockwise")
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.warn)
            }
            .buttonStyle(.plain)
        }
    }

    private func regenerate() {
        speech.stopSpeaking()
        speak { await store.regenerate(api: state.api) }
    }

    /// Runs a send and reads the reply aloud when voice replies are on.
    private func speak(_ run: @escaping () async -> String?) {
        Task {
            let reply = await run()
            if voiceReplies, let reply {
                let wav = try? await state.api.synthesizeVoice(text: reply)
                speech.playReply(wav: wav, fallbackText: reply, localeID: voiceLocaleID)
            }
        }
    }

    /// زر المكالمة الحيّة — يفتح شاشة الصوت (تحكي وساندي ترد بصوتها).
    private var liveCallButton: some View {
        Button {
            dismissKeyboard()
            showLive = true
        } label: {
            ZStack {
                Circle()
                    .fill(Theme.Colors.surface)
                    .frame(width: ChatMetrics.control, height: ChatMetrics.control)
                    .overlay(Circle().stroke(Theme.Colors.border, lineWidth: 1))

                Image(systemName: "waveform")
                    .scaledFont(Theme.Icon.sm, weight: .semibold)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(lang.s("chat.liveCall"))
    }

    private var sendButton: some View {
        Button(action: send) {
            ZStack {
                Circle()
                    .fill(
                        canSend
                            ? AnyShapeStyle(Theme.Colors.accent)
                            : AnyShapeStyle(Theme.Colors.accent.opacity(0.18))
                    )
                    .frame(width: ChatMetrics.control, height: ChatMetrics.control)
                    .sandyGlow(canSend)

                // While she replies the stop button stands here instead.
                Image(systemName: "paperplane.fill")
                    .scaledFont(Theme.Icon.sm, weight: .semibold)
                    .foregroundColor(canSend ? Theme.Colors.onAccent : Theme.Colors.accentDeep.opacity(0.5))
            }
        }
        .buttonStyle(.plain)
        // إصلاح (3): مستحيل ترسل رسالة فاضية — الزر معطّل ما لم يوجد نص فعلي.
        .disabled(!canSend)
        .animation(Animation.easeInOut(duration: 0.2).reduced, value: canSend)
        .accessibilityLabel(lang.s("chat.send"))
    }

    // MARK: - الأفعال

    /// يخفي لوحة المفاتيح (نقر بالخلفية / زر "تم").
    private func dismissKeyboard() {
        inputFocused = false
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }

    /// إصلاح (2): عند ضغط Return — لو النص فاضي ما نعمل شيء (ولا حتى نضيف سطر)؛
    /// لو في نص فعلي نرسل.
    private func handleReturn() {
        guard !trimmedInput.isEmpty else {
            // نظّف أي مسافات/أسطر فاضية تسرّبت، وخلّي الحقل فاضيًا فعلًا.
            input = ""
            return
        }
        send()
    }

    /// يرسل الرسالة. إصلاح (3): يرجع مبكّرًا لو النص (بعد التنظيف) فاضي —
    /// فمستحيل توصل رسالة فاضية للباك-إند. الستور يملك الإرسال + الحفظ التلقائي،
    /// والـView يتكفّل بصوت ساندي (لأنه يملك محرّك الصوت).
    private func send() {
        let text = trimmedInput
        let attachments = composer.ready
        guard !text.isEmpty || !attachments.isEmpty, !store.sending, !composer.busy else {
            input = ""
            return
        }

        input = ""
        composer.clear()
        speech.stopSpeaking()               // لو عم تقرأ رد قديم، تسكت

        // ساندي تقرأ ردها بصوت جيميني الحقيقي (لو السمّاعة شغّالة).
        if editingLast {
            editingLast = false
            speak { await store.editLast(api: state.api, to: text) }
        } else {
            speak { await store.send(api: state.api, text: text, attachments: attachments) }
        }
    }

    // ثابت مرساة لمؤشّر الكتابة (للتمرير إليه).
    private static let typingAnchorID = "sandy-typing-indicator"
}

// MARK: - صف الرسالة (فقاعة)

/// Layout constants shared by the chat rows and input bar.
private enum ChatMetrics {
    /// Round buttons in the input bar (live call, send).
    static let control: CGFloat = 40
    static let avatar: CGFloat = 28
    /// Minimum empty space beside a bubble, so it never spans the full width.
    static let bubbleGutter: CGFloat = 40
}

/// One bubble. Equatable on its inputs so SwiftUI skips unchanged rows while a
/// reply streams into the last one.
private struct ChatBubbleRow: View, Equatable {
    let isUser: Bool
    let text: String
    var failed = false
    var attachments: [ChatAttachment] = []

    var body: some View {
        HStack(alignment: .bottom, spacing: Theme.Spacing.sm) {
            if isUser {
                Spacer(minLength: ChatMetrics.bubbleGutter)
                content
            } else {
                // فقاعة ساندي تجيها أفاتار صغير لها.
                SandyAvatar(size: ChatMetrics.avatar, mood: .happy)
                content
                Spacer(minLength: ChatMetrics.bubbleGutter)
            }
        }
    }

    /// Photos and drawn images, then documents, then the words.
    private var content: some View {
        VStack(alignment: isUser ? .trailing : .leading, spacing: Theme.Spacing.xs) {
            ForEach(attachments.filter(\.isImage)) { AttachmentPicture(attachment: $0) }
            ForEach(attachments.filter { !$0.isImage }) { AttachmentFileChip(attachment: $0) }
            if !text.isEmpty { bubble }
        }
    }

    private var bubble: some View {
        Text(text)
            .font(Theme.Typography.body)
            .foregroundColor(Theme.Colors.primaryText)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(Theme.Spacing.md)
            // فقاعات زجاج سائل — فقاعتك أزرق أوضح، فقاعة ساندي زجاج صافٍ.
            .liquidGlass(cornerRadius: Theme.Radius.bubble, tint: isUser ? 0.28 : 0.06)
            .overlay {
                if failed {
                    RoundedRectangle(cornerRadius: Theme.Radius.bubble, style: .continuous)
                        .stroke(Theme.Colors.warn, lineWidth: 1.5)
                }
            }
            .overlay(alignment: .bottomLeading) {
                if failed {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundColor(Theme.Colors.warn)
                        .offset(x: -6, y: 6)
                        .accessibilityHidden(true)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(LanguageManager.shared.s(isUser ? "a11y.fromYou" : "a11y.fromSandy")
                                + LanguageManager.shared.s("common.listSeparator") + text)
            .accessibilityValue(failed ? LanguageManager.shared.s("a11y.failed") : "")
            .accessibilityHint(LanguageManager.shared.s("a11y.messageHint"))
    }
}

/// A message opened so part of it can be picked and copied.
private struct SelectableMessage: Identifiable {
    let id = UUID()
    let text: String
}

private struct SelectTextSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let text: String

    var body: some View {
        NavigationStack {
            SelectableText(text: text)
                .padding(Theme.Spacing.md)
                .navigationTitle(lang.s("chat.selectText"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button(lang.s("common.done")) { dismiss() }
                    }
                }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Read-only text where any part can be selected (SwiftUI's own selection takes all of it).
private struct SelectableText: UIViewRepresentable {
    let text: String

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.isEditable = false
        view.isSelectable = true
        view.backgroundColor = .clear
        view.font = UIFont.preferredFont(forTextStyle: .body)
        view.adjustsFontForContentSizeCategory = true
        view.textColor = UIColor(Theme.Colors.primaryText)
        return view
    }

    func updateUIView(_ view: UITextView, context: Context) {
        view.text = text
    }
}

// MARK: - ورقة سجل المحادثات (قائمة + بحث + جديد)

private struct ChatHistorySheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var store: ChatStore

    @State private var query = ""
    @State private var hits: [ConversationHit] = []
    @State private var searchTask: Task<Void, Never>?
    /// إعادة التسمية عبر تنبيه فيه حقل نص.
    @State private var renameTarget: ConversationMeta?
    @State private var renameText = ""
    @State private var showRename = false

    var body: some View {
        NavigationStack {
            ZStack {
                SandyBackground()
                content
            }
            .navigationTitle(lang.s("chat.history"))
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $query, prompt: lang.s("chat.searchPlaceholder"))
            .onChange(of: query) { scheduleSearch() }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.done")) { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        store.startNew(api: state.api); dismiss()
                    } label: {
                        Image(systemName: "square.and.pencil")
                    }
                    .accessibilityLabel(lang.s("chat.new"))
                }
            }
            .task { await store.loadList(api: state.api) }
            .alert(lang.s("chat.renameTitle"), isPresented: $showRename) {
                TextField(lang.s("chat.renamePlaceholder"), text: $renameText)
                Button(lang.s("common.cancel"), role: .cancel) { renameTarget = nil }
                Button(lang.s("common.save")) {
                    if let c = renameTarget {
                        Task { await store.rename(api: state.api, id: c.id, title: renameText) }
                    }
                    renameTarget = nil
                }
            }
        }
        // The sheet covers the tabs' undo bar, so it shows its own.
        .undoOverlay(bottom: Theme.Spacing.md)
    }

    private func beginRename(_ c: ConversationMeta) {
        renameTarget = c
        renameText = c.title
        showRename = true
    }

    @ViewBuilder
    private var content: some View {
        if query.trimmingCharacters(in: .whitespaces).isEmpty {
            if store.conversations.isEmpty {
                emptyView
            } else {
                List {
                    ForEach(grouped, id: \.0) { bucket, convs in
                        Section(lang.s("chat.\(bucket)")) {
                            ForEach(convs) { c in
                                Button { open(c.id) } label: { row(c.title, sub: "") }
                                    .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                        Button(role: .destructive) {
                                            Task { await store.delete(api: state.api, id: c.id) }
                                        } label: { Label(lang.s("chat.delete"), systemImage: "trash") }
                                    }
                                    .swipeActions(edge: .leading) {
                                        Button { beginRename(c) } label: {
                                            Label(lang.s("chat.rename"), systemImage: "pencil")
                                        }
                                        .tint(Theme.Colors.accent)
                                    }
                                    .contextMenu {
                                        Button { beginRename(c) } label: {
                                            Label(lang.s("chat.rename"), systemImage: "pencil")
                                        }
                                        Button(role: .destructive) {
                                            Task { await store.delete(api: state.api, id: c.id) }
                                        } label: { Label(lang.s("chat.delete"), systemImage: "trash") }
                                    }
                            }
                        }
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        } else {
            List {
                ForEach(hits) { h in
                    Button { open(h.id) } label: { row(h.title, sub: h.snippet) }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.lg) {
            Image(systemName: "bubble.left.and.bubble.right")
                .scaledFont(Theme.Icon.xl, relativeTo: .largeTitle)
                .foregroundColor(Theme.Colors.tertiaryText)
            Text(lang.s("chat.historyEmpty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func row(_ title: String, sub: String) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text(title.isEmpty ? lang.s("chat.untitled") : title)
                .font(Theme.Typography.body)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(1)
            if !sub.isEmpty {
                Text(sub)
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }

    private func open(_ id: String) {
        Task {
            await store.open(api: state.api, id: id)
            dismiss()
        }
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { hits = []; return }
        searchTask = Task {
            // مهلة صغيرة (debounce) حتى ما نبحث كل حرف.
            try? await Task.sleep(nanoseconds: 250_000_000)
            if Task.isCancelled { return }
            if let r = try? await state.api.searchConversations(q: q) { hits = r }
        }
    }

    /// المحادثات مجمّعة زمنيًا (اليوم/أمس/الأسبوع/أقدم)، فاضي تُحذف، والترتيب محفوظ.
    private var grouped: [(String, [ConversationMeta])] {
        let order = ["today", "yesterday", "week", "older"]
        var map: [String: [ConversationMeta]] = [:]
        for c in store.conversations {
            map[bucket(c.updatedAt), default: []].append(c)
        }
        return order.compactMap { key in
            guard let convs = map[key], !convs.isEmpty else { return nil }
            return (key, convs)
        }
    }

    private func bucket(_ iso: String) -> String {
        guard let d = parseISO(iso) else { return "older" }
        let cal = Calendar.current
        if cal.isDateInToday(d) { return "today" }
        if cal.isDateInYesterday(d) { return "yesterday" }
        if let days = cal.dateComponents([.day], from: d, to: Date()).day, days < 7 { return "week" }
        return "older"
    }

    // Built once: `grouped` parses every row's date on each render, and a
    // formatter per call made opening the history sheet visibly slower.
    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let isoPlain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private func parseISO(_ iso: String) -> Date? {
        Self.isoFractional.date(from: iso) ?? Self.isoPlain.date(from: iso)
    }
}

// MARK: - مؤشّر "ساندي تكتب…" بنقاط متحرّكة

/// فقاعة صغيرة بنفس ستايل فقاعة ساندي، فيها ثلاث نقاط تنبض بالتتابع —
/// تعطي إحساس إن ساندي تفكّر/تكتب أثناء الانتظار (الردود تاخذ ثواني).
private struct TypingIndicator: View {
    @EnvironmentObject var lang: LanguageManager
    /// What she is doing, shown beside the dots while a tool runs.
    var activity = ""
    /// A long wait: after a few seconds her short lines take the dots' place.
    @State private var long = false

    var body: some View {
        HStack(alignment: .bottom, spacing: Theme.Spacing.sm) {
            SandyAvatar(size: ChatMetrics.avatar, mood: .happy)
            HStack(spacing: 5) {
                if !activity.isEmpty {
                    LoadingDots()
                    Text(activity)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .padding(.leading, 4)
                        .transition(.opacity)
                } else if long {
                    SandyWaiting(compact: true, showsFace: false)
                } else {
                    LoadingDots()
                }
            }
            .animation(Animation.easeInOut(duration: 0.25).reduced, value: activity)
            .animation(Animation.easeInOut(duration: 0.25).reduced, value: long)
            .padding(.vertical, Theme.Spacing.md)
            .padding(.horizontal, Theme.Spacing.md)
            .liquidGlass(cornerRadius: Theme.Radius.bubble, tint: 0.06)
            Spacer(minLength: ChatMetrics.bubbleGutter)
        }
        .task {
            try? await Task.sleep(for: .seconds(3))
            long = true
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(lang.s("chat.typingA11y"))
    }
}
