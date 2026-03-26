package com.snapchef.app.models

import java.time.LocalDateTime

data class User(
    val id: Int,
    val email: String,
    val name: String,
    val hashedPassword: String,
    val createdAt: LocalDateTime
)
