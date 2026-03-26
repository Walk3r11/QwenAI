package com.snapchef.app.services

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import com.snapchef.app.models.User
import com.snapchef.config.AppConfig
import com.snapchef.db.tables.UsersTable
import org.jetbrains.exposed.sql.ResultRow
import org.jetbrains.exposed.sql.insertAndGetId
import org.jetbrains.exposed.sql.selectAll
import org.jetbrains.exposed.sql.transactions.transaction
import org.mindrot.jbcrypt.BCrypt
import java.time.Instant
import java.time.LocalDateTime
import java.util.*

object AuthService {

    fun hashPassword(raw: String): String =
        BCrypt.hashpw(raw, BCrypt.gensalt())

    fun verifyPassword(raw: String, hashed: String): Boolean =
        BCrypt.checkpw(raw, hashed)

    fun createToken(userId: Int): String {
        require(AppConfig.jwtSecret.isNotBlank()) { "JWT_SECRET is not configured." }
        return JWT.create()
            .withIssuer(AppConfig.jwtIssuer)
            .withAudience(AppConfig.jwtAudience)
            .withSubject(userId.toString())
            .withExpiresAt(Date.from(Instant.now().plusSeconds(AppConfig.jwtExpirationMinutes * 60)))
            .sign(Algorithm.HMAC256(AppConfig.jwtSecret))
    }

    fun findByEmail(email: String): User? = transaction {
        UsersTable.selectAll()
            .where { UsersTable.email eq email.lowercase() }
            .map { it.toUser() }
            .singleOrNull()
    }

    fun findById(id: Int): User? = transaction {
        UsersTable.selectAll()
            .where { UsersTable.id eq id }
            .map { it.toUser() }
            .singleOrNull()
    }

    fun createUser(email: String, name: String, hashedPassword: String): User = transaction {
        val id = UsersTable.insertAndGetId {
            it[UsersTable.email] = email.lowercase()
            it[UsersTable.name] = name.trim()
            it[UsersTable.hashedPassword] = hashedPassword
        }
        User(id.value, email.lowercase(), name.trim(), hashedPassword, LocalDateTime.now())
    }

    private fun ResultRow.toUser() = User(
        id = this[UsersTable.id].value,
        email = this[UsersTable.email],
        name = this[UsersTable.name],
        hashedPassword = this[UsersTable.hashedPassword],
        createdAt = this[UsersTable.createdAt]
    )
}
