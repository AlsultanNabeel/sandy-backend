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

    @State private var messages: [ChatMessage] = []
    @State private var input = ""
    @State private var sending = false
    /// رسالة خطأ ودّية (تُعرض كـ SandyNotice أسفل القائمة). فاضي = ما في خطأ.
    @State private var errorMessage = ""

    /// التحكم بتركيز حقل الإدخال — لإخفاء/إظهار الكيبورد برمجيًا.
    @FocusState private var inputFocused: Bool

    /// محرّك الصوت — مكالمة حيّة + قراءة ردود الكتابة بصوت ساندي.
    @StateObject private var speech = SpeechManager()
    /// هل ساندي تقرأ ردود الكتابة بصوت؟ (يتحكم فيه زر السمّاعة، محفوظ).
    @AppStorage("sandy_voice_replies") private var voiceReplies = true
    /// عرض شاشة المكالمة الصوتية الحيّة.
    @State private var showLive = false

    /// لغة التعرّف/الصوت تتبع لغة التطبيق.
    private var voiceLocaleID: String { lang.lang == .ar ? "ar-SA" : "en-US" }

    /// النص بعد التنظيف — مصدر وحيد للحقيقة لتعطيل الزر ومنع الإرسال الفاضي.
    private var trimmedInput: String {
        input.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// هل يُسمح بالإرسال الآن؟ (مو مرسل حاليًا + في نص فعلي).
    private var canSend: Bool {
        !sending && !trimmedInput.isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            messageList
            inputBar
        }
        .background(SandyBackground())
        .navigationTitle(lang.s("chat.title"))
        // إصلاح (1): شريط فوق الكيبورد فيه زر "تم" لإخفائها يدويًا.
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button(lang.s("common.done")) { dismissKeyboard() }
                    .font(Theme.Typography.button)
                    .foregroundColor(Theme.Colors.accent)
            }
            // زر صوت ساندي — يكتم/يشغّل قراءتها لردودها.
            ToolbarItem(placement: .navigationBarTrailing) {
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
        // نوقف صوت ساندي عند مغادرة الشاشة.
        .onDisappear { speech.stopSpeaking() }
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
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    ForEach(messages) { m in
                        messageRow(m)
                            .id(m.id)
                            // حيوية: كل فقاعة تظهر بتكبير لطيف + تلاشٍ.
                            .transition(
                                .scale(scale: 0.85, anchor: .bottom)
                                    .combined(with: .opacity)
                            )
                    }

                    // حيوية: مؤشّر "ساندي تكتب…" بنقاط متحرّكة أثناء الانتظار.
                    if sending {
                        TypingIndicator()
                            .id(Self.typingAnchorID)
                            .transition(.scale(scale: 0.85, anchor: .bottomLeading).combined(with: .opacity))
                    }

                    // خطأ دافئ بصوت ساندي بدل فقاعة حمراء.
                    if !errorMessage.isEmpty {
                        SandyNotice(errorMessage, kind: .gentleWarning)
                            .transition(.opacity)
                    }
                }
                .padding(Theme.Spacing.md)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            // إصلاح (1): سحب القائمة يخفي الكيبورد بسلاسة.
            .scrollDismissesKeyboard(.interactively)
            // حيوية: حركة نابضة عند تغيّر عدد الرسائل أو ظهور مؤشّر الكتابة.
            .animation(.spring(response: 0.4, dampingFraction: 0.8), value: messages.count)
            .animation(.spring(response: 0.4, dampingFraction: 0.8), value: sending)
            .animation(.easeInOut(duration: 0.25), value: errorMessage)
            // إصلاح (1): نقر بأي مكان بالخلفية/القائمة يخفي الكيبورد.
            .contentShape(Rectangle())
            .onTapGesture { dismissKeyboard() }
            .onChange(of: messages.count) { _ in
                scrollToBottom(proxy)
            }
            .onChange(of: sending) { isSending in
                // ننزل لمؤشّر الكتابة لما يظهر.
                if isSending { scrollToBottom(proxy) }
            }
        }
    }

    /// ينزّل العرض لآخر عنصر (مؤشّر الكتابة لو شغّال، وإلا آخر رسالة).
    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
            if sending {
                proxy.scrollTo(Self.typingAnchorID, anchor: .bottom)
            } else if let last = messages.last {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }

    // MARK: - شريط الإدخال

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: Theme.Spacing.sm) {
            liveCallButton

            TextField(lang.s("chat.placeholder"), text: $input, axis: .vertical)
                .focused($inputFocused)
                .font(Theme.Typography.body)
                .lineLimit(1...5)
                .padding(.vertical, Theme.Spacing.sm)
                .padding(.horizontal, Theme.Spacing.md)
                .background(Theme.Colors.surface)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                        .stroke(Theme.Colors.border, lineWidth: 1)
                )
                // إصلاح (2): Return (submit) ما يضيف سطر فاضي ولا يرسل لو النص فاضي —
                // نطمّن أولًا ثم نرسل فقط لو في نص فعلي.
                .onSubmit { handleReturn() }

            sendButton
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

    /// زر المكالمة الحيّة — يفتح شاشة الصوت (تحكي وساندي ترد بصوتها).
    private var liveCallButton: some View {
        Button {
            dismissKeyboard()
            showLive = true
        } label: {
            ZStack {
                Circle()
                    .fill(Theme.Colors.surface)
                    .frame(width: 40, height: 40)
                    .overlay(Circle().stroke(Theme.Colors.border, lineWidth: 1))

                Image(systemName: "waveform")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(Theme.Colors.accent)
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
                            ? AnyShapeStyle(
                                LinearGradient(
                                    colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                                    startPoint: .topLeading, endPoint: .bottomTrailing))
                            : AnyShapeStyle(Theme.Colors.accent.opacity(0.18))
                    )
                    .frame(width: 40, height: 40)
                    .shadow(color: canSend ? Theme.Shadow.glowColor : .clear,
                            radius: 8, x: 0, y: 3)

                if sending {
                    ProgressView()
                        .progressViewStyle(.circular)
                        .tint(Theme.Colors.onAccent)
                } else {
                    Image(systemName: "paperplane.fill")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(canSend ? Theme.Colors.onAccent : Theme.Colors.accentDeep.opacity(0.5))
                }
            }
        }
        .buttonStyle(.plain)
        // إصلاح (3): مستحيل ترسل رسالة فاضية — الزر معطّل ما لم يوجد نص فعلي.
        .disabled(!canSend)
        .animation(.easeInOut(duration: 0.2), value: canSend)
        .accessibilityLabel(lang.s("chat.send"))
    }

    // MARK: - صف الرسالة (فقاعة)

    @ViewBuilder
    private func messageRow(_ m: ChatMessage) -> some View {
        let isUser = (m.role == "user")
        HStack(alignment: .bottom, spacing: Theme.Spacing.sm) {
            if isUser {
                Spacer(minLength: 40)
                bubble(m.text, isUser: true)
            } else {
                // فقاعة ساندي تجيها أفاتار صغير لها.
                SandyAvatar(size: 28, mood: .happy)
                bubble(m.text, isUser: false)
                Spacer(minLength: 40)
            }
        }
    }

    @ViewBuilder
    private func bubble(_ text: String, isUser: Bool) -> some View {
        Text(text)
            .font(Theme.Typography.body)
            .foregroundColor(Theme.Colors.primaryText)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(Theme.Spacing.md)
            // فقاعات زجاج سائل — فقاعتك أزرق أوضح، فقاعة ساندي زجاج صافٍ.
            .liquidGlass(cornerRadius: Theme.Radius.bubble, tint: isUser ? 0.28 : 0.06)
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
    /// فمستحيل توصل رسالة فاضية للباك-إند.
    private func send() {
        let text = trimmedInput
        guard !text.isEmpty, !sending else {
            input = ""
            return
        }

        input = ""
        errorMessage = ""
        sending = true
        speech.stopSpeaking()               // لو عم تقرأ رد قديم، تسكت
        messages.append(ChatMessage(role: "user", text: text))

        Task {
            do {
                let reply = try await state.api.sendMessage(text)
                messages.append(ChatMessage(role: "sandy", text: reply))
                // ساندي تقرأ ردها بصوت جيميني الحقيقي (لو السمّاعة شغّالة).
                if voiceReplies {
                    let wav = try? await state.api.synthesizeVoice(text: reply)
                    speech.playReply(wav: wav, fallbackText: reply, localeID: voiceLocaleID)
                }
            } catch {
                // خطأ دافئ بصوت ساندي بدل فقاعة حمراء.
                errorMessage = lang.s("chat.sendError")
            }
            sending = false
        }
    }

    // ثابت مرساة لمؤشّر الكتابة (للتمرير إليه).
    private static let typingAnchorID = "sandy-typing-indicator"
}

// MARK: - مؤشّر "ساندي تكتب…" بنقاط متحرّكة

/// فقاعة صغيرة بنفس ستايل فقاعة ساندي، فيها ثلاث نقاط تنبض بالتتابع —
/// تعطي إحساس إن ساندي تفكّر/تكتب أثناء الانتظار (الردود تاخذ ثواني).
private struct TypingIndicator: View {
    @EnvironmentObject var lang: LanguageManager
    @State private var animating = false

    var body: some View {
        HStack(alignment: .bottom, spacing: Theme.Spacing.sm) {
            SandyAvatar(size: 28, mood: .happy)
            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { i in
                    Circle()
                        .fill(Theme.Colors.accent.opacity(0.55))
                        .frame(width: 7, height: 7)
                        .scaleEffect(animating ? 1.0 : 0.5)
                        .opacity(animating ? 1.0 : 0.4)
                        .animation(
                            .easeInOut(duration: 0.6)
                                .repeatForever(autoreverses: true)
                                .delay(Double(i) * 0.18),
                            value: animating
                        )
                }
            }
            .padding(.vertical, Theme.Spacing.md)
            .padding(.horizontal, Theme.Spacing.md)
            .liquidGlass(cornerRadius: Theme.Radius.bubble, tint: 0.06)
            Spacer(minLength: 40)
        }
        .onAppear { animating = true }
        .accessibilityLabel(lang.s("chat.typingA11y"))
    }
}
