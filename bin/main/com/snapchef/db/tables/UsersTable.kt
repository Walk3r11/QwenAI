package com.snapchef.db.tables

import org.jetbrains.exposed.dao.id.IntIdTable
import org.jetbrains.exposed.sql.javatime.datetime
import java.time.LocalDateTime

object UsersTable : IntIdTable("users") {
    val email = varchar("email", 255).uniqueIndex()
    val name = varchar("name", 120)
    val hashedPassword = varchar("hashed_password", 255)
    val createdAt = datetime("created_at").clientDefault { LocalDateTime.now() }
}
