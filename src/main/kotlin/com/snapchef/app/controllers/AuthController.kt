package com.snapchef.app.controllers

import com.snapchef.app.serializers.*
import com.snapchef.app.services.AuthService
import io.ktor.http.*
import io.ktor.server.application.*
import io.ktor.server.auth.*
import io.ktor.server.auth.jwt.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*

fun Route.authRoutes() {
    route("/auth") {

        post("/signup") {
            val req = call.receive<SignupRequest>()

            if (req.name.length < 2 || req.name.length > 120) {
                return@post call.respond(HttpStatusCode.BadRequest, ErrorResponse("Name must be 2-120 characters."))
            }
            if (req.password.length < 8 || req.password.length > 128) {
                return@post call.respond(HttpStatusCode.BadRequest, ErrorResponse("Password must be 8-128 characters."))
            }

            if (AuthService.findByEmail(req.email) != null) {
                return@post call.respond(HttpStatusCode.Conflict, ErrorResponse("Email already registered."))
            }

            val hashed = AuthService.hashPassword(req.password)
            val user = AuthService.createUser(req.email, req.name, hashed)
            val token = AuthService.createToken(user.id)

            call.respond(
                HttpStatusCode.Created,
                AuthResponse(
                    accessToken = token,
                    user = UserResponse(user.id, user.email, user.name)
                )
            )
        }

        post("/login") {
            val req = call.receive<LoginRequest>()

            val user = AuthService.findByEmail(req.email)
            if (user == null || !AuthService.verifyPassword(req.password, user.hashedPassword)) {
                return@post call.respond(HttpStatusCode.Unauthorized, ErrorResponse("Invalid email or password."))
            }

            val token = AuthService.createToken(user.id)
            call.respond(
                AuthResponse(
                    accessToken = token,
                    user = UserResponse(user.id, user.email, user.name)
                )
            )
        }

        authenticate("auth-jwt") {
            get("/me") {
                val principal = call.principal<JWTPrincipal>()!!
                val userId = principal.payload.subject.toInt()

                val user = AuthService.findById(userId)
                    ?: return@get call.respond(HttpStatusCode.NotFound, ErrorResponse("User not found."))

                call.respond(UserResponse(user.id, user.email, user.name))
            }
        }
    }
}
