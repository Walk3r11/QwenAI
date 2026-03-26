package com.snapchef.app.serializers

import kotlinx.serialization.Serializable

@Serializable
data class SignupRequest(
    val email: String,
    val name: String,
    val password: String
)

@Serializable
data class LoginRequest(
    val email: String,
    val password: String
)

@Serializable
data class UserResponse(
    val id: Int,
    val email: String,
    val name: String
)

@Serializable
data class AuthResponse(
    val accessToken: String,
    val tokenType: String = "bearer",
    val user: UserResponse
)
