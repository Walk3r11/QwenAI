package com.snapchef.app.controllers

import com.snapchef.app.serializers.ErrorResponse
import com.snapchef.app.services.AiService
import com.snapchef.app.services.AiServiceException
import io.ktor.http.*
import io.ktor.http.content.*
import io.ktor.server.application.*
import io.ktor.server.auth.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*

fun Route.aiRoutes() {
    route("/ai") {
        authenticate("auth-jwt") {

            post("/analyze") {
                var imageBytes: ByteArray? = null
                var mimeType: String? = null

                call.receiveMultipart().forEachPart { part ->
                    when (part) {
                        is PartData.FileItem -> {
                            if (part.name == "file") {
                                mimeType = part.contentType?.toString()
                                imageBytes = part.streamProvider().readBytes()
                            }
                        }
                        else -> Unit
                    }
                    part.dispose()
                }

                if (imageBytes == null || mimeType == null || !mimeType!!.startsWith("image/")) {
                    return@post call.respond(
                        HttpStatusCode.UnsupportedMediaType,
                        ErrorResponse("Upload an image file.")
                    )
                }

                if (imageBytes!!.isEmpty()) {
                    return@post call.respond(HttpStatusCode.BadRequest, ErrorResponse("Empty file."))
                }

                try {
                    val result = AiService.analyzeImage(imageBytes!!, mimeType!!)
                    call.respondText(result, ContentType.Application.Json)
                } catch (e: AiServiceException) {
                    call.respond(
                        HttpStatusCode.BadGateway,
                        ErrorResponse(e.message ?: "Model server error.")
                    )
                }
            }
        }
    }
}
