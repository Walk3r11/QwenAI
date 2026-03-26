package com.snapchef.config

import com.snapchef.app.controllers.aiRoutes
import com.snapchef.app.controllers.authRoutes
import com.snapchef.app.controllers.healthRoutes
import io.ktor.server.application.*
import io.ktor.server.routing.*

fun Application.configureRoutes() {
    routing {
        healthRoutes()
        authRoutes()
        aiRoutes()
    }
}
