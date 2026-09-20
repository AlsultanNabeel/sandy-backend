//
//  SandyWidgetBundle.swift
//  SandyWidget
//
//  Created by Nabeel Alsultan  on 29/06/2026.
//

import WidgetKit
import SwiftUI

@main
struct SandyWidgetBundle: WidgetBundle {
    var body: some Widget {
        SandyWidget()
        SandyWidgetControl()
        SandyWidgetLiveActivity()
    }
}
