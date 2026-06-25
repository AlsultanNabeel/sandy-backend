import Foundation

/// Talks to the Sandy backend (the Python API we built).
final class APIClient {
    var baseURL: String
    var token: String?

    init(baseURL: String) { self.baseURL = baseURL }

    private func request(_ path: String,
                         method: String = "GET",
                         body: [String: Any]? = nil,
                         auth: Bool = true) async throws -> [String: Any] {
        guard let url = URL(string: baseURL + path) else { throw APIError(message: "عنوان غير صالح") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if auth, let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }

        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if code >= 400 { throw APIError(message: (json["error"] as? String) ?? "خطأ \(code)") }
        return json
    }

    // دخول المطوّر السريع (كلمة سر المالك) — للتجربة.
    func devLogin(password: String) async throws {
        let r = try await request("/api/auth", method: "POST",
                                  body: ["password": password], auth: false)
        guard let t = r["token"] as? String else { throw APIError(message: "ما رجع توكن") }
        token = t
    }

    // تسجيل دخول آبل — يرجّع هل التعارف خلص.
    func signInApple(idToken: String, name: String) async throws -> Bool {
        let r = try await request("/api/auth/apple", method: "POST",
                                  body: ["id_token": idToken, "name": name], auth: false)
        guard let t = r["token"] as? String else { throw APIError(message: "فشل التحقّق") }
        token = t
        return r["onboarding_done"] as? Bool ?? false
    }

    func getOnboarding() async throws -> OnboardingData {
        let r = try await request("/api/onboarding")
        return OnboardingData(done: r["done"] as? Bool ?? false,
                              preferredName: r["preferred_name"] as? String ?? "",
                              interests: r["interests"] as? [String] ?? [],
                              name: r["name"] as? String ?? "")
    }

    func saveOnboarding(preferredName: String, interests: [String]) async throws {
        _ = try await request("/api/onboarding", method: "POST",
                              body: ["preferred_name": preferredName, "interests": interests])
    }

    func sendMessage(_ text: String, conversationId: String? = nil) async throws -> String {
        // نرسل لغة المستخدم الحالية (عربي/إنجليزي) حتى ترد ساندي بنفس اللغة.
        let lang = await LanguageManager.shared.lang.rawValue
        var body: [String: Any] = ["message": text, "lang": lang]
        // سيشن الشات — تخلّي ساندي تتذكّر هالمحادثة لحالها بلا ما تخلط المواضيع.
        if let cid = conversationId, !cid.isEmpty { body["conversation_id"] = cid }
        let r = try await request("/api/agent", method: "POST", body: body)
        return r["reply"] as? String ?? "…"
    }

    // MARK: - سجل المحادثات (متعدد السيشنات)

    // GET /api/conversations → {"items":[{id,title,updated_at}]}
    func listConversations() async throws -> [ConversationMeta] {
        let r = try await request("/api/conversations")
        return (r["items"] as? [[String: Any]] ?? []).map {
            ConversationMeta(id: $0["id"] as? String ?? "",
                             title: $0["title"] as? String ?? "",
                             updatedAt: $0["updated_at"] as? String ?? "")
        }
    }

    // POST /api/conversations → {"id"}
    func createConversation() async throws -> String {
        let r = try await request("/api/conversations", method: "POST", body: [:])
        guard let id = r["id"] as? String, !id.isEmpty else {
            throw APIError(message: "تعذّر إنشاء المحادثة")
        }
        return id
    }

    // GET /api/conversations/<id> → {"title","messages":[{role,text,ts}]}
    func getConversation(id: String) async throws -> (title: String, messages: [ChatMessage]) {
        let r = try await request("/api/conversations/\(id)")
        let msgs = (r["messages"] as? [[String: Any]] ?? []).compactMap { m -> ChatMessage? in
            guard let role = m["role"] as? String, let text = m["text"] as? String else { return nil }
            return ChatMessage(role: role, text: text)
        }
        return (r["title"] as? String ?? "", msgs)
    }

    // POST /api/conversations/<id>/messages {role,text}
    func appendMessage(cid: String, role: String, text: String) async throws {
        _ = try await request("/api/conversations/\(cid)/messages", method: "POST",
                              body: ["role": role, "text": text])
    }

    // DELETE /api/conversations/<id>
    func deleteConversation(id: String) async throws {
        _ = try await request("/api/conversations/\(id)", method: "DELETE")
    }

    // GET /api/conversations/search?q= → {"items":[{id,title,snippet,updated_at}]}
    func searchConversations(q: String) async throws -> [ConversationHit] {
        let r = try await request("/api/conversations/search?q=\(enc(q))")
        return (r["items"] as? [[String: Any]] ?? []).map {
            ConversationHit(id: $0["id"] as? String ?? "",
                            title: $0["title"] as? String ?? "",
                            snippet: $0["snippet"] as? String ?? "",
                            updatedAt: $0["updated_at"] as? String ?? "")
        }
    }

    // MARK: - الذاكرة (اللي ساندي متذكّراه عنك)

    // GET /api/memory → {"items":[{id,text,type}]}
    func getMemory() async throws -> [MemoryFact] {
        let r = try await request("/api/memory")
        return (r["items"] as? [[String: Any]] ?? []).map {
            MemoryFact(id: $0["id"] as? String ?? "",
                       text: $0["text"] as? String ?? "",
                       type: $0["type"] as? String ?? "general")
        }
    }

    // DELETE /api/memory/<id>
    func deleteMemory(id: String) async throws {
        _ = try await request("/api/memory/\(id)", method: "DELETE")
    }

    // MARK: - الخط الزمني (سجل النشاط الموحّد)

    // GET /api/timeline → {"items":[{type,id,title,subtitle,ts,done}]}
    func getTimeline() async throws -> [TimelineEvent] {
        let r = try await request("/api/timeline")
        return (r["items"] as? [[String: Any]] ?? []).map {
            TimelineEvent(id: $0["id"] as? String ?? "",
                          type: $0["type"] as? String ?? "",
                          title: $0["title"] as? String ?? "",
                          subtitle: $0["subtitle"] as? String ?? "",
                          ts: $0["ts"] as? String ?? "",
                          done: $0["done"] as? Bool ?? false)
        }
    }

    // حذف عنصر من مصدره الأصلي (حسب نوعه) — حرية الحذف من الخط الزمني.
    func deleteTask(id: String) async throws {
        _ = try await request("/api/tasks/\(id)", method: "DELETE")
    }

    func deleteExpense(id: String) async throws {
        _ = try await request("/api/life/expenses/\(id)", method: "DELETE")
    }

    func deleteJournalEntry(id: String) async throws {
        _ = try await request("/api/life/journal/\(id)", method: "DELETE")
    }

    /// يجيب صوت ساندي الطبيعي (WAV من جيميني) لنصّ معيّن — للتشغيل ومزامنة الفم.
    /// نطلب JSON خام (مش عبر `request` لأنه يفكّ JSON؛ هون الناتج بايتات صوت).
    func synthesizeVoice(text: String, mood: String = "neutral") async throws -> Data {
        guard let url = URL(string: baseURL + "/api/voice/tts") else {
            throw APIError(message: "عنوان غير صالح")
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["text": text, "mood": mood])
        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code >= 400 { throw APIError(message: "صوت غير متاح (\(code))") }
        return data
    }

    // ── المهام ──────────────────────────────────────────────────────────
    // GET /api/tasks → {"items":[{id,text,done,due_at,note?,priority?}], "demo":bool}
    // note و priority إضافيان واختياريان — نقرأهما بحذر مع قيم افتراضية.
    func getTasks(completed: Bool = false) async throws -> ListResult<TaskItem> {
        let path = completed ? "/api/tasks?completed=1" : "/api/tasks"
        let r = try await request(path)
        let items = r["items"] as? [[String: Any]] ?? []
        let parsed: [TaskItem] = items.compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            let priority = (row["priority"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "normal"
            return TaskItem(id: id,
                            text: row["text"] as? String ?? "",
                            done: row["done"] as? Bool ?? false,
                            dueAt: row["due_at"] as? String ?? "",
                            note: row["note"] as? String ?? "",
                            priority: priority)
        }
        return ListResult(items: parsed, demo: r["demo"] as? Bool ?? false)
    }

    // POST /api/tasks body {"text","due","note"?,"priority"?} → {"ok":true,"id":...}
    // note و priority اختياريان — نضيفهما فقط لو موجودين (additive + آمن).
    func addTask(text: String,
                 due: String = "",
                 note: String? = nil,
                 priority: String? = nil) async throws {
        var body: [String: Any] = ["text": text, "due": due]
        if let note { body["note"] = note }
        if let priority { body["priority"] = priority }
        _ = try await request("/api/tasks", method: "POST", body: body)
    }

    // PATCH /api/tasks/<id> body {"done":bool} (للمالك فقط)
    func setTaskDone(id: String, done: Bool) async throws {
        _ = try await request("/api/tasks/\(id)", method: "PATCH",
                              body: ["done": done])
    }

    // PATCH /api/tasks/<id> — تعديل شامل: نص/إنجاز/ملاحظة/أولوية.
    // الباك-إند يدعم text و done؛ note و priority إضافيان واختياريان وآمنان.
    // نمرّر فقط الحقول غير nil حتى لا نمسح قيمة موجودة عن طريق الخطأ.
    func updateTask(id: String,
                    text: String? = nil,
                    done: Bool? = nil,
                    note: String? = nil,
                    priority: String? = nil,
                    due: String? = nil) async throws {
        var body: [String: Any] = [:]
        if let text { body["text"] = text }
        if let done { body["done"] = done }
        if let note { body["note"] = note }
        if let priority { body["priority"] = priority }
        if let due { body["due"] = due }   // "" يمسح الموعد
        guard !body.isEmpty else { return }
        _ = try await request("/api/tasks/\(id)", method: "PATCH", body: body)
    }

    // DELETE /api/tasks/<id> — deleteTask معرّف بقسم الخط الزمني.

    // ── التذكيرات ───────────────────────────────────────────────────────
    // GET /api/reminders → {"items":[{id,text,remind_at,is_recurring,note?}], "demo":bool}
    // note إضافي واختياري — نقرأه بحذر مع قيمة افتراضية فاضية.
    func getReminders() async throws -> ListResult<ReminderItem> {
        let r = try await request("/api/reminders")
        let items = r["items"] as? [[String: Any]] ?? []
        let parsed: [ReminderItem] = items.compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            return ReminderItem(id: id,
                                text: row["text"] as? String ?? "",
                                remindAt: row["remind_at"] as? String ?? "",
                                isRecurring: row["is_recurring"] as? Bool ?? false,
                                note: row["note"] as? String ?? "")
        }
        return ListResult(items: parsed, demo: r["demo"] as? Bool ?? false)
    }

    // POST /api/reminders body {"text","remind_at","note"?} → {"ok":true} (للمالك فقط)
    // الباك-إند يرفض إن كان أحدهما فاضي (text_and_remind_at_required).
    // note اختياري — نضيفه فقط لو موجود (additive + آمن).
    func addReminder(text: String, remindAt: String, note: String? = nil) async throws {
        var body: [String: Any] = ["text": text, "remind_at": remindAt]
        if let note { body["note"] = note }
        _ = try await request("/api/reminders", method: "POST", body: body)
    }

    // DELETE /api/reminders/<id> → {"ok":true} (للمالك فقط)
    func deleteReminder(id: String) async throws {
        _ = try await request("/api/reminders/\(id)", method: "DELETE")
    }

    // ── العادات ─────────────────────────────────────────────────────────
    // GET /api/life/habits → {"items":[{id,name,streak,done_today}], "demo":bool}
    func getHabits() async throws -> ListResult<HabitItem> {
        let r = try await request("/api/life/habits")
        let items = r["items"] as? [[String: Any]] ?? []
        let parsed: [HabitItem] = items.compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            return HabitItem(id: id,
                             name: row["name"] as? String ?? "",
                             streak: (row["streak"] as? NSNumber)?.intValue ?? 0,
                             doneToday: row["done_today"] as? Bool ?? false)
        }
        return ListResult(items: parsed, demo: r["demo"] as? Bool ?? false)
    }

    // POST /api/life/habits body {"name"} → {"ok":bool} (للمالك فقط)
    func addHabit(name: String) async throws {
        _ = try await request("/api/life/habits", method: "POST",
                              body: ["name": name])
    }

    // POST /api/life/habits/checkin body {"name"} → {"ok":bool} (للمالك فقط)
    func checkinHabit(name: String) async throws {
        _ = try await request("/api/life/habits/checkin", method: "POST",
                              body: ["name": name])
    }

    // POST /api/life/habits/uncheckin body {"id"} → {"ok":bool} (للمالك فقط)
    // تراجع عن تسجيل حضور اليوم لو انضغط بالغلط.
    func uncheckinHabit(id: String) async throws {
        _ = try await request("/api/life/habits/uncheckin", method: "POST",
                              body: ["id": id])
    }

    // ── الفوكس (بومودورو) ───────────────────────────────────────────────
    // GET /api/life/focus → حالة الجلسة الحالية.
    func getFocusStatus() async throws -> FocusStatus {
        let r = try await request("/api/life/focus")
        return FocusStatus(
            active: r["active"] as? Bool ?? false,
            label: r["label"] as? String ?? "",
            scene: r["scene"] as? String ?? "",
            phase: r["phase"] as? String ?? "focus",
            cycleIdx: (r["cycle_idx"] as? NSNumber)?.intValue ?? 1,
            cycles: (r["cycles"] as? NSNumber)?.intValue ?? 1,
            focusMin: (r["focus_min"] as? NSNumber)?.intValue ?? 25,
            breakMin: (r["break_min"] as? NSNumber)?.intValue ?? 0,
            remainingSec: (r["remaining_sec"] as? NSNumber)?.intValue ?? 0,
            totalSec: (r["total_sec"] as? NSNumber)?.intValue ?? 0,
            demo: r["demo"] as? Bool ?? false)
    }

    // POST /api/life/focus/start (للمالك فقط)
    func startFocus(focusMin: Int, breakMin: Int, cycles: Int,
                    scene: String, endScene: String, label: String) async throws {
        _ = try await request("/api/life/focus/start", method: "POST", body: [
            "focus_min": focusMin, "break_min": breakMin, "cycles": cycles,
            "scene": scene, "end_scene": endScene, "label": label,
        ])
    }

    // POST /api/life/focus/stop body {"cancel":bool} (للمالك فقط)
    func stopFocus(cancel: Bool) async throws {
        _ = try await request("/api/life/focus/stop", method: "POST",
                              body: ["cancel": cancel])
    }

    // GET /api/life/focus/history?limit=
    func getFocusHistory(limit: Int = 30) async throws -> [FocusSession] {
        let r = try await request("/api/life/focus/history?limit=\(limit)")
        let rows = r["sessions"] as? [[String: Any]] ?? []
        return rows.map { row in
            FocusSession(label: row["label"] as? String ?? "",
                         minutes: (row["minutes"] as? NSNumber)?.intValue ?? 0,
                         completed: row["completed"] as? Bool ?? false,
                         startedAt: row["started_at"] as? String ?? "")
        }
    }

    // ── مشاهد الغرفة (تحكّم room-node عبر MQTT) ──────────────────────────
    // GET /api/life/scenes → {"items":[{name,label,icon,actions:[{device,value}]}], "demo":bool}
    func getScenes() async throws -> ListResult<RoomScene> {
        let r = try await request("/api/life/scenes")
        let items = r["items"] as? [[String: Any]] ?? []
        let parsed: [RoomScene] = items.compactMap { row in
            guard let name = row["name"] as? String, !name.isEmpty else { return nil }
            let acts = (row["actions"] as? [[String: Any]] ?? []).map { a -> SceneAction in
                let dev = a["device"] as? String ?? ""
                let val: String
                if let s = a["value"] as? String { val = s }
                else if let n = a["value"] as? NSNumber { val = n.stringValue }
                else { val = "" }
                return SceneAction(device: dev, value: val)
            }
            return RoomScene(name: name,
                             label: row["label"] as? String ?? name,
                             icon: row["icon"] as? String ?? "🎛️",
                             actions: acts)
        }
        return ListResult(items: parsed, demo: r["demo"] as? Bool ?? false)
    }

    // POST /api/life/scenes/apply body {"name"} → {"ok":bool,"online":bool}
    // ok = طُبّق المشهد، online = وصل لـ room-node فعليًا.
    @discardableResult
    func applyScene(name: String) async throws -> (ok: Bool, online: Bool) {
        let r = try await request("/api/life/scenes/apply", method: "POST",
                                  body: ["name": name])
        return (r["ok"] as? Bool ?? false, r["online"] as? Bool ?? false)
    }

    // POST /api/life/scenes body {"name","label","icon","actions"} (للمالك فقط)
    func addScene(name: String, label: String, icon: String, actions: [SceneAction]) async throws {
        _ = try await request("/api/life/scenes", method: "POST", body: [
            "name": name, "label": label, "icon": icon,
            "actions": actions.map { ["device": $0.device, "value": $0.value] },
        ])
    }

    // POST /api/life/scenes/actions body {"name","actions"} (للمالك فقط)
    func setSceneActions(name: String, actions: [SceneAction]) async throws {
        _ = try await request("/api/life/scenes/actions", method: "POST", body: [
            "name": name,
            "actions": actions.map { ["device": $0.device, "value": $0.value] },
        ])
    }

    // POST /api/life/scenes/delete body {"name"} (للمالك فقط)
    func deleteScene(name: String) async throws {
        _ = try await request("/api/life/scenes/delete", method: "POST",
                              body: ["name": name])
    }

    // MARK: - البحث الخارجي (الويب/الأماكن)

    private func enc(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
    }

    // GET /api/research?q=&kind=web → {"kind","items":[{title,url,text,published_date}],"demo"}
    func researchWeb(q: String) async throws -> ListResult<WebResult> {
        let r = try await request("/api/research?kind=web&q=\(enc(q))")
        let items = (r["items"] as? [[String: Any]] ?? []).map { row in
            WebResult(title: row["title"] as? String ?? "",
                      url: row["url"] as? String ?? "",
                      text: row["text"] as? String ?? "",
                      publishedDate: row["published_date"] as? String ?? "")
        }
        return ListResult(items: items, demo: r["demo"] as? Bool ?? false)
    }

    // GET /api/research?q=&kind=places → {"kind","items":[{name,address,rating,...}],"demo"}
    func researchPlaces(q: String) async throws -> ListResult<PlaceResult> {
        let r = try await request("/api/research?kind=places&q=\(enc(q))")
        let items = (r["items"] as? [[String: Any]] ?? []).map { row in
            PlaceResult(name: row["name"] as? String ?? "",
                        address: row["address"] as? String ?? "",
                        rating: (row["rating"] as? NSNumber)?.doubleValue ?? 0,
                        reviewsCount: (row["reviews_count"] as? NSNumber)?.intValue ?? 0,
                        phone: row["phone"] as? String ?? "",
                        website: row["website"] as? String ?? "",
                        priceLevel: row["price_level"] as? String ?? "",
                        openNow: row["open_now"] as? String ?? "",
                        mapsUrl: row["maps_url"] as? String ?? "")
        }
        return ListResult(items: items, demo: r["demo"] as? Bool ?? false)
    }

    // MARK: - الصور (توليد/تعديل/وصف)

    /// يفك "data:image/png;base64,XXXX" (أو base64 خام) لبايتات الصورة.
    private func decodeDataURI(_ s: String) -> Data? {
        if let comma = s.range(of: ",") {
            return Data(base64Encoded: String(s[comma.upperBound...]))
        }
        return Data(base64Encoded: s)
    }

    // POST /api/image {prompt} → {url:"data:image/png;base64,..."}
    func generateImage(prompt: String) async throws -> Data {
        let r = try await request("/api/image", method: "POST", body: ["prompt": prompt])
        guard let url = r["url"] as? String, let data = decodeDataURI(url) else {
            throw APIError(message: "تعذّر توليد الصورة")
        }
        return data
    }

    // POST /api/image/edit {prompt, image(b64)} → {url:"data:..."}
    func editImage(image: Data, prompt: String) async throws -> Data {
        let r = try await request("/api/image/edit", method: "POST",
                                  body: ["prompt": prompt, "image": image.base64EncodedString()])
        guard let url = r["url"] as? String, let data = decodeDataURI(url) else {
            throw APIError(message: "تعذّر تعديل الصورة")
        }
        return data
    }

    // POST /api/analyze-image {image(b64), question} → {reply}
    func describeImage(image: Data, question: String = "") async throws -> String {
        var body: [String: Any] = ["image": image.base64EncodedString()]
        if !question.isEmpty { body["question"] = question }
        let r = try await request("/api/analyze-image", method: "POST", body: body)
        return r["reply"] as? String ?? ""
    }

    // ── المصاريف ────────────────────────────────────────────────────────
    // GET /api/life/expenses → {"items":[{id,amount,note,category,at}],
    //                           "summary":{total,count,...}, "demo":bool}
    func getExpenses() async throws -> ExpensesResult {
        let r = try await request("/api/life/expenses")
        let items = r["items"] as? [[String: Any]] ?? []
        let parsed: [ExpenseItem] = items.compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            return ExpenseItem(id: id,
                               amount: (row["amount"] as? NSNumber)?.doubleValue ?? 0,
                               note: row["note"] as? String ?? "",
                               category: row["category"] as? String ?? "",
                               at: row["at"] as? String ?? "")
        }
        let s = r["summary"] as? [String: Any] ?? [:]
        let summary = ExpensesSummary(total: (s["total"] as? NSNumber)?.doubleValue ?? 0,
                                      count: (s["count"] as? NSNumber)?.intValue ?? 0)
        return ExpensesResult(items: parsed, summary: summary, demo: r["demo"] as? Bool ?? false)
    }

    // POST /api/life/expenses body {"amount","note","category"} → {"ok":bool} (للمالك فقط)
    func addExpense(amount: Double, note: String, category: String) async throws {
        _ = try await request("/api/life/expenses", method: "POST",
                              body: ["amount": amount, "note": note, "category": category])
    }

    // ── اليوميات ────────────────────────────────────────────────────────
    // GET /api/life/journal → {"items":[{id,date,text}], "demo":bool}
    func getJournal() async throws -> ListResult<JournalEntry> {
        let r = try await request("/api/life/journal")
        let items = r["items"] as? [[String: Any]] ?? []
        let parsed: [JournalEntry] = items.compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            return JournalEntry(id: id,
                                date: row["date"] as? String ?? "",
                                text: row["text"] as? String ?? "")
        }
        return ListResult(items: parsed, demo: r["demo"] as? Bool ?? false)
    }

    // POST /api/life/journal body {"text"} → {"ok":bool} (للمالك فقط)
    func addJournalEntry(text: String) async throws {
        _ = try await request("/api/life/journal", method: "POST",
                              body: ["text": text])
    }

    // ── لقطة الشاشة الرئيسية ─────────────────────────────────────────────
    /// تجميع خفيف وذكي للشاشة الرئيسية: يجلب المهام + التذكيرات + المصاريف
    /// بالتوازي، ويتحمّل فشل كل قسم وحده (لا يرمي خطأ — يرجّع لقطة جزئية).
    /// مبني بالكامل من نداءات GET الموجودة، بدون أي نقطة نهاية جديدة.
    func getHomeSnapshot() async -> HomeSnapshot {
        // نجلب الثلاثة بالتوازي؛ كل واحد محاط بـ try? فلا يُسقط البقية.
        async let tasksRes = try? getTasks()
        async let remindersRes = try? getReminders()
        async let expensesRes = try? getExpenses()

        let tasks = await tasksRes
        let reminders = await remindersRes
        let expenses = await expensesRes

        var snap = HomeSnapshot()
        // hadError = فشل قسم واحد على الأقل (رجّع nil).
        snap.hadError = (tasks == nil) || (reminders == nil) || (expenses == nil)

        let now = Date()
        let cal = Calendar.current
        // مُحلِّل ISO متسامح: ISO8601 يتطلّب منطقة زمنية، لكن الباك-إند يرسل
        // أحيانًا بلا منطقة (مثل "2026-06-05T16:00:00")، فنرجع لـ DateFormatter.
        let isoFull = ISO8601DateFormatter()
        isoFull.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let isoPlain = ISO8601DateFormatter()
        isoPlain.formatOptions = [.withInternetDateTime]
        let plainNoTZ = DateFormatter()
        plainNoTZ.locale = Locale(identifier: "en_US_POSIX")
        plainNoTZ.timeZone = TimeZone.current
        plainNoTZ.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        let dateOnly = DateFormatter()
        dateOnly.locale = Locale(identifier: "en_US_POSIX")
        dateOnly.timeZone = TimeZone.current
        dateOnly.dateFormat = "yyyy-MM-dd"
        func parseISO(_ s: String) -> Date? {
            if s.isEmpty { return nil }
            return isoFull.date(from: s)
                ?? isoPlain.date(from: s)
                ?? plainNoTZ.date(from: s)
                ?? dateOnly.date(from: s)
        }

        // ── المهام ──
        if let tasks {
            if tasks.demo { snap.demo = true }
            let open = tasks.items.filter { !$0.done }
            snap.openTasks = open.count
            for t in open {
                guard let due = parseISO(t.dueAt) else { continue }
                if due < now {
                    snap.overdueTasks += 1
                } else if cal.isDateInToday(due) {
                    snap.todayTasks += 1
                }
            }
            // عيّنة حتى 3 نصوص للعرض (مفتوحة، نتجاهل الفاضي).
            snap.sampleTaskTexts = open
                .map { $0.text }
                .filter { !$0.isEmpty }
                .prefix(3)
                .map { $0 }
        }

        // ── التذكيرات ──
        if let reminders {
            if reminders.demo { snap.demo = true }
            // القادمة فقط (وقتها ≥ الآن)، مرتّبة بالأقرب، حتى 3.
            let upcoming = reminders.items
                .compactMap { r -> (ReminderItem, Date)? in
                    guard let at = parseISO(r.remindAt), at >= now else { return nil }
                    return (r, at)
                }
                .sorted { $0.1 < $1.1 }
                .map { $0.0 }
            snap.upcomingReminders = Array(upcoming.prefix(3))
            if let first = upcoming.first {
                snap.nextReminderText = first.text
                snap.nextReminderAt = first.remindAt
            }
        }

        // ── المصاريف ──
        if let expenses {
            if expenses.demo { snap.demo = true }
            // إجمالي المدى (الملخّص) ≈ مصاريف الأسبوع/الشهر حسب نطاق الـ GET.
            snap.weekExpenseTotal = expenses.summary.total
            // مجموع مصاريف اليوم من العناصر التي وقتها اليوم.
            var todaySum = 0.0
            for e in expenses.items {
                if let at = parseISO(e.at), cal.isDateInToday(at) {
                    todaySum += e.amount
                }
            }
            snap.todayExpenseTotal = todaySum
        }

        return snap
    }
}
