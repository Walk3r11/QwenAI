package com.snapchef.app.services

import com.snapchef.config.AppConfig
import io.ktor.client.*
import io.ktor.client.engine.cio.*
import io.ktor.client.request.*
import io.ktor.client.statement.*
import io.ktor.http.*
import kotlinx.serialization.json.*
import java.util.Base64

object AiService {

    private val client = HttpClient(CIO) {
        engine {
            requestTimeout = 180_000
        }
    }

    suspend fun analyzeImage(imageBytes: ByteArray, mimeType: String): String {
        val base64 = Base64.getEncoder().encodeToString(imageBytes)
        val dataUrl = "data:$mimeType;base64,$base64"

        val payload = buildJsonObject {
            put("model", AppConfig.qwenModel)
            putJsonArray("messages") {
                addJsonObject {
                    put("role", "user")
                    putJsonArray("content") {
                        addJsonObject {
                            put("type", "text")
                            put("text", AppConfig.analyzePrompt)
                        }
                        addJsonObject {
                            put("type", "image_url")
                            putJsonObject("image_url") {
                                put("url", dataUrl)
                            }
                        }
                    }
                }
            }
            put("temperature", 0.2)
        }

        val response = client.post(AppConfig.qwenUrl) {
            contentType(ContentType.Application.Json)
            setBody(payload.toString())
        }

        if (response.status.value >= 400) {
            throw AiServiceException(
                "Model server returned ${response.status.value}: ${response.bodyAsText()}"
            )
        }

        return response.bodyAsText()
    }
}

class AiServiceException(message: String) : RuntimeException(message)
