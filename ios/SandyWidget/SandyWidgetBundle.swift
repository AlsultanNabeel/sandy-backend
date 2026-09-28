import WidgetKit
import SwiftUI

@main
struct SandyWidgetBundle: WidgetBundle {
    var body: some Widget {
        SandyWidget()
        SandyCallLiveActivity()
        SandyFocusLiveActivity()
        SandyTasksWidget()
        TalkToSandyControl()
    }
}
