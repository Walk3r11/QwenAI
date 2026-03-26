package com.snapchef.app.controllers

import com.snapchef.app.serializers.HealthResponse
import com.snapchef.config.AppConfig
import io.ktor.server.application.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import org.jetbrains.exposed.sql.transactions.transaction

fun Route.healthRoutes() {
    get("/health") {
        val dbOk = try {
            transaction { exec("SELECT 1") { it.next() } }
            true
        } catch (_: Exception) {
            false
        }

        call.respond(
            HealthResponse(
                ok = true,
                dbConnected = dbOk,
                usingNeon = AppConfig.databaseUrl.contains("neon.tech"),
                jwtConfigured = AppConfig.jwtSecret.isNotBlank()
            )
        )
    }
}
