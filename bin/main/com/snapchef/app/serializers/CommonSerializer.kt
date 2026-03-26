package com.snapchef.app.serializers

import kotlinx.serialization.Serializable

@Serializable
data class ErrorResponse(
    val error: String
)

@Serializable
data class HealthResponse(
    val ok: Boolean,
    val dbConnected: Boolean,
    val usingNeon: Boolean,
    val jwtConfigured: Boolean
)
