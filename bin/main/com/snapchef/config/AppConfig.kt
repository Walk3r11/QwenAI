package com.snapchef.config

object AppConfig {
    val databaseUrl: String
        get() {
            val raw = System.getenv("DATABASE_URL") ?: "jdbc:postgresql://localhost:5432/snapchef"
            return if (raw.startsWith("postgres://") || raw.startsWith("postgresql://")) {
                raw.replaceFirst(Regex("^postgres(ql)?://"), "jdbc:postgresql://")
            } else raw
        }

    val jwtSecret: String get() = System.getenv("JWT_SECRET") ?: ""
    val jwtIssuer: String get() = System.getenv("JWT_ISSUER") ?: "snapchef"
    val jwtAudience: String get() = System.getenv("JWT_AUDIENCE") ?: "snapchef-users"
    val jwtExpirationMinutes: Long get() = System.getenv("JWT_EXPIRE_MINUTES")?.toLongOrNull() ?: 10_080L

    val qwenUrl: String get() = System.getenv("QWEN_URL") ?: "http://127.0.0.1:8080/v1/chat/completions"
    val qwenModel: String get() = System.getenv("QWEN_MODEL") ?: "qwen2.5-vl"
    val analyzePrompt: String
        get() = System.getenv("ANALYZE_PROMPT")
            ?: "Identify every food item visible in this image. For each, suggest a recipe. " +
               "Return JSON: {\"items\": [{\"name\": string, \"confidence\": 0-1}], " +
               "\"recipes\": [{\"title\": string, \"ingredients\": [string], \"steps\": [string]}]}"
}
