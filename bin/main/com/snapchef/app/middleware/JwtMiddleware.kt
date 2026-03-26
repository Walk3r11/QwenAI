package com.snapchef.app.middleware

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import com.snapchef.config.AppConfig
import io.ktor.server.application.*
import io.ktor.server.auth.*
import io.ktor.server.auth.jwt.*

fun Application.configureJwt() {
    install(Authentication) {
        jwt("auth-jwt") {
            realm = "snapchef"
            verifier(
                JWT.require(Algorithm.HMAC256(AppConfig.jwtSecret))
                    .withIssuer(AppConfig.jwtIssuer)
                    .withAudience(AppConfig.jwtAudience)
                    .build()
            )
            validate { credential ->
                val userId = credential.payload.subject?.toIntOrNull()
                if (userId != null && credential.payload.audience.contains(AppConfig.jwtAudience)) {
                    JWTPrincipal(credential.payload)
                } else {
                    null
                }
            }
        }
    }
}
