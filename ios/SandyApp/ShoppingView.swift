import SwiftUI

/// قائمة التسوّق — تعرض اللي ناوي تجيبه، تسمح بالإضافة والتعديل والحذف، شطب
/// الغرض لما ينشري (مع تسجيل سعره بمصاريفك تلقائياً)، وتحديد سعر/كمية قبل الشراء
/// مع إظهار آخر سعر دفعته لنفس الصنف. فوق `/api/life/shopping`. نمط الستور
/// المعتمد: الجلب بمهمة يملكها الستور (محصّنة ضد إلغاء الإيماءات).
struct ShoppingView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = ShoppingStore()
    @State private var showAdd = false
    /// الغرض الجاري تعديله (nil = ما في ورقة تعديل مفتوحة).
    @State private var editingItem: ShoppingItem?
    /// الغرض الجاري تسجيل شرائه (nil = ما في ورقة شراء مفتوحة).
    @State private var buyingItem: ShoppingItem?

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                content
            }
        }
        .navigationTitle(lang.s("shopping.title"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                SandyButton(title: lang.s("shopping.add"),
                            systemImage: "plus.circle.fill",
                            style: .secondary) {
                    store.notice = ""
                    showAdd = true
                }
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.items.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .fullScreenCover(isPresented: $showAdd) {
            ShoppingSheet { text, category, _, _ in
                await store.add(api: state.api, text: text, category: category)
            }
        }
        .fullScreenCover(item: $editingItem) { item in
            ShoppingSheet(existing: item) { text, category, qty, price in
                await store.update(api: state.api, item: item, text: text,
                                   category: category, qty: qty, price: price)
            }
        }
        .fullScreenCover(item: $buyingItem) { item in
            ShoppingBuySheet(item: item) { price in
                await store.buy(api: state.api, item: item, price: price)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.items.isEmpty && !store.loading {
            emptyView
        } else {
            List {
                // المقدّمة صف غير قابل للسحب يبقى أعلى القائمة.
                header
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: Theme.Spacing.sm, leading: Theme.Spacing.md,
                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                ForEach(store.items) { item in
                    itemCard(item)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                  bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                store.delete(api: state.api, item: item)
                            } label: { Label(lang.s("shopping.delete"), systemImage: "trash") }
                        }
                        .swipeActions(edge: .leading) {
                            if !item.done {
                                Button { buyingItem = item } label: {
                                    Label(lang.s("shopping.buy"), systemImage: "cart.fill.badge.plus")
                                }
                                .tint(Theme.Colors.success)
                            }
                            Button { editingItem = item } label: {
                                Label(lang.s("shopping.edit"), systemImage: "pencil")
                            }
                            .tint(Theme.Colors.accent)
                        }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }

    private var header: some View {
        Text(lang.s("shopping.intro"))
            .font(Theme.Typography.subheadline)
            .foregroundColor(Theme.Colors.secondaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func itemCard(_ item: ShoppingItem) -> some View {
        SandyCard {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                Image(systemName: item.done ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundColor(item.done ? Theme.Colors.success : Theme.Colors.secondaryText)
                    .padding(.top, 1)

                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(item.text)
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.primaryText)
                        .strikethrough(item.done, color: Theme.Colors.secondaryText)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    if !item.metaLine(lang).isEmpty {
                        Text(item.metaLine(lang))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { editingItem = item }
        .contextMenu {
            if !item.done {
                Button { buyingItem = item } label: {
                    Label(lang.s("shopping.buy"), systemImage: "cart.fill.badge.plus")
                }
            }
            Button { editingItem = item } label: {
                Label(lang.s("shopping.edit"), systemImage: "pencil")
            }
            Button(role: .destructive) {
                store.delete(api: state.api, item: item)
            } label: { Label(lang.s("shopping.delete"), systemImage: "trash") }
        }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "cart")
                .font(.system(size: 44))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("shopping.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("shopping.add"),
                        systemImage: "plus.circle.fill") {
                store.notice = ""
                showAdd = true
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }
}

// MARK: - ورقة غرض (إضافة أو تعديل)

/// ورقة بسيطة: اسم الغرض + تصنيف اختياري + (للموجود) كمية وسعر للوحدة. `existing`
/// غير nil ⇒ تعديل (تعبئة مسبقة). تُرسل عبر closure غير متزامن يرجّع نجاح/فشل.
private struct ShoppingSheet: View {
    let existing: ShoppingItem?
    let onSubmit: (_ text: String, _ category: String) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var text: String
    @State private var category: String
    @State private var submitting = false

    init(existing: ShoppingItem? = nil,
         onSubmit: @escaping (_ text: String, _ category: String) async -> Bool) {
        self.existing = existing
        self.onSubmit = onSubmit
        _text = State(initialValue: existing?.text ?? "")
        _category = State(initialValue: existing?.category ?? "")
    }

    private var isEditing: Bool { existing != nil }
    private var trimmedText: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s(isEditing ? "shopping.editTitle" : "shopping.addTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("shopping.sheet.namePrompt"))
                    SandyCard {
                        TextField(lang.s("shopping.sheet.namePlaceholder"), text: $text)
                            .font(Theme.Typography.body)
                    }
                }
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("shopping.sheet.categoryPrompt"))
                    SandyCard {
                        TextField(lang.s("shopping.sheet.categoryPlaceholder"), text: $category)
                            .font(Theme.Typography.body)
                    }
                }
                SandyButton(title: lang.s(isEditing ? "shopping.saveEdit" : "shopping.saveNew"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmedText.isEmpty)
                .opacity(trimmedText.isEmpty ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmedText.isEmpty, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(trimmedText,
                                    category.trimmingCharacters(in: .whitespacesAndNewlines))
            submitting = false
            if ok { dismiss() }
        }
    }
}

// MARK: - ورقة تسجيل الشراء

/// ورقة شطب الغرض كـ"انشترى" مع سعره — تجيب آخر سعر دفعته لنفس الصنف وتقترحه،
/// والسعر بنضيفه تلقائياً لمصاريفك من جهة الباك-إند. closure يرجّع نجاح/فشل.
private struct ShoppingBuySheet: View {
    let item: ShoppingItem
    let onBuy: (_ price: Double) async -> Bool

    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var price: String
    @State private var lastPrice: Double = 0
    @State private var submitting = false

    init(item: ShoppingItem, onBuy: @escaping (_ price: Double) async -> Bool) {
        self.item = item
        self.onBuy = onBuy
        // نعبّي بسعر العنصر المحفوظ لو موجود.
        _price = State(initialValue: item.price > 0 ? Money.plain(item.price) : "")
    }

    private var priceValue: Double {
        Double(price.trimmingCharacters(in: .whitespaces)) ?? 0
    }

    var body: some View {
        SandyPopup(title: lang.s("shopping.priceTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                Text(lang.s("shopping.pricePrompt"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)

                SandyCard {
                    HStack {
                        Image(systemName: "banknote")
                            .foregroundColor(Theme.Colors.accent)
                        TextField(lang.s("shopping.sheet.pricePlaceholder"), text: $price)
                            .keyboardType(.decimalPad)
                            .font(.system(size: 22, weight: .semibold, design: .rounded))
                    }
                }

                if lastPrice > 0 {
                    Button {
                        price = Money.plain(lastPrice)
                    } label: {
                        Label(String(format: lang.s("shopping.lastPrice"), Money.plain(lastPrice)),
                              systemImage: "clock.arrow.circlepath")
                            .font(Theme.Typography.callout)
                            .foregroundColor(Theme.Colors.accent)
                    }
                    .buttonStyle(.plain)
                }

                SandyButton(title: lang.s("shopping.priceSave"),
                            systemImage: "cart.fill.badge.plus",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(priceValue <= 0)
                .opacity(priceValue <= 0 ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
        .task {
            // آخر سعر دفعته لنفس الصنف — اقتراح ذكي بدون ما يلزّم.
            lastPrice = await state.api.shoppingLastPrice(text: item.text)
        }
    }

    private func save() {
        guard priceValue > 0, !submitting else { return }
        submitting = true
        Task {
            let ok = await onBuy(priceValue)
            submitting = false
            if ok { dismiss() }
        }
    }
}

// MARK: - الستور

@MainActor
final class ShoppingStore: ObservableObject {
    @Published var items: [ShoppingItem] = []
    @Published var loading = false
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                items = try await api.getShopping()
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("shopping.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة غرض ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String, category: String) async -> Bool {
        do {
            try await api.addShopping(text: text, category: category)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("shopping.errorAdd")
            return false
        }
    }

    /// تعديل اسم/تصنيف الغرض ثم إعادة جلب. الباك-إند ما عنده PATCH للنص، فبنعمل
    /// التعديل كحذف للقديم + إضافة جديد (نفس النتيجة بنظر المستخدم).
    func update(api: APIClient, item: ShoppingItem, text: String, category: String) async -> Bool {
        do {
            try await api.addShopping(text: text, category: category)
            try await api.deleteShopping(id: item.id)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("shopping.errorEdit")
            return false
        }
    }

    /// شطب الغرض كـ"انشترى" مع سعره (الباك-إند بيضيفه لمصاريفك). ثم إعادة جلب.
    func buy(api: APIClient, item: ShoppingItem, price: Double) async -> Bool {
        do {
            try await api.checkShopping(id: item.id, price: price)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("shopping.errorBuy")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, item: ShoppingItem) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        items.remove(at: idx)
        Task { @MainActor in
            do {
                try await api.deleteShopping(id: item.id)
            } catch {
                items.insert(item, at: min(idx, items.count))
                notice = LanguageManager.shared.s("shopping.errorDelete")
            }
        }
    }
}

// MARK: - النموذج

/// غرض بقائمة التسوّق — يطابق عناصر GET /api/life/shopping:
/// id, text, done, category, price, qty, unit.
struct ShoppingItem: Identifiable {
    let id: String
    let text: String
    let done: Bool
    let category: String
    let price: Double
    let qty: Int
    let unit: String

    /// سطر وصفي ثانوي: التصنيف + الكمية + السعر/الإجمالي التقديري (لو متوفّرة).
    func metaLine(_ lang: LanguageManager) -> String {
        var parts: [String] = []
        if done {
            parts.append(lang.s("shopping.bought"))
        }
        let cat = category.trimmingCharacters(in: .whitespaces)
        if !cat.isEmpty { parts.append(cat) }
        if qty > 1 {
            let unitSuffix = unit.isEmpty ? "" : " \(unit)"
            parts.append("\(lang.s("shopping.qty")) \(qty)\(unitSuffix)")
        }
        if price > 0 {
            let total = price * Double(max(1, qty))
            parts.append(String(format: lang.s("shopping.estTotal"), Money.plain(total)))
        }
        return parts.joined(separator: " · ")
    }
}

/// تنسيق مبلغ بسيط: صحيح بلا كسور، غير ذلك بمنزلتين عشريّتين.
private enum Money {
    static func plain(_ value: Double) -> String {
        value == value.rounded()
            ? String(Int(value.rounded()))
            : String(format: "%.2f", value)
    }
}

// MARK: - نداءات الباك-إند (تعيش هنا حتى ما نلمس APIClient.swift)

extension APIClient {
    /// نسخة محلّية من `request` الخاص بـ APIClient — `request` معرّف `private` فما
    /// بنقدر نناديه من ملف ثاني، فبنكرّر نفس منطق المصادقة وفكّ JSON بدقّة هون.
    /// (لو صار `request` غير-private لاحقاً، احذف هذا واستبدله بـ `request`.)
    private func shoppingRequest(_ path: String,
                                 method: String = "GET",
                                 body: [String: Any]? = nil) async throws -> [String: Any] {
        guard let url = URL(string: baseURL + path) else { throw APIError(message: "عنوان غير صالح") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }

        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if code >= 400 { throw APIError(message: (json["error"] as? String) ?? "خطأ \(code)") }
        return json
    }

    // GET /api/life/shopping → {"items":[{id,text,done,category,price,qty,unit}], "demo":bool}
    func getShopping() async throws -> [ShoppingItem] {
        let r = try await shoppingRequest("/api/life/shopping")
        let items = r["items"] as? [[String: Any]] ?? []
        return items.compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            return ShoppingItem(
                id: id,
                text: row["text"] as? String ?? "",
                done: row["done"] as? Bool ?? false,
                category: row["category"] as? String ?? "",
                price: (row["price"] as? NSNumber)?.doubleValue ?? 0,
                qty: (row["qty"] as? NSNumber)?.intValue ?? 1,
                unit: row["unit"] as? String ?? "")
        }
    }

    // POST /api/life/shopping body {"text","category"} → {"ok":bool} (للمالك فقط)
    func addShopping(text: String, category: String = "") async throws {
        _ = try await shoppingRequest("/api/life/shopping", method: "POST",
                              body: ["text": text, "category": category])
    }

    // PATCH /api/life/shopping/<id> body {"price"?,"qty"?} → {"ok":bool,...}
    // يشطب الغرض كـ"انشترى"؛ لو فيه سعر بيضيفه لمصاريفك تلقائياً.
    func checkShopping(id: String, price: Double? = nil, qty: Int? = nil) async throws {
        var body: [String: Any] = [:]
        if let price { body["price"] = price }
        if let qty { body["qty"] = qty }
        _ = try await shoppingRequest("/api/life/shopping/\(id)", method: "PATCH", body: body)
    }

    // DELETE /api/life/shopping/<id> → {"ok":bool}
    func deleteShopping(id: String) async throws {
        _ = try await shoppingRequest("/api/life/shopping/\(id)", method: "DELETE")
    }

    // POST /api/life/shopping/<id>/price body {"price"?,"qty"?,"unit"?} → {"ok":bool}
    // يحدّد السعر/الكمية بدون ما يشطب — للإجمالي التقديري قبل الشراء.
    func setShoppingPrice(id: String, price: Double? = nil,
                          qty: Int? = nil, unit: String? = nil) async throws {
        var body: [String: Any] = [:]
        if let price { body["price"] = price }
        if let qty { body["qty"] = qty }
        if let unit { body["unit"] = unit }
        guard !body.isEmpty else { return }
        _ = try await shoppingRequest("/api/life/shopping/\(id)/price", method: "POST", body: body)
    }

    // GET /api/life/shopping/last-price?text= → {"price":number}
    // آخر سعر مدفوع لصنف بنفس الاسم. لا يرمي — يرجّع 0 عند أي فشل (اقتراح فقط).
    func shoppingLastPrice(text: String) async -> Double {
        let q = text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        guard let r = try? await shoppingRequest("/api/life/shopping/last-price?text=\(q)") else { return 0 }
        return (r["price"] as? NSNumber)?.doubleValue ?? 0
    }
}
