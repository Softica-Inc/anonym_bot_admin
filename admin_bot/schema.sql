CREATE TABLE `admin_user` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `tg_user_id` bigint NOT NULL,
   `email` varchar(512) DEFAULT NULL,
   `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
   PRIMARY KEY (`id`),
   UNIQUE KEY `tg_user_id` (`tg_user_id`)
 ) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci

CREATE TABLE `audit_log` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `bot_id` bigint DEFAULT NULL,
   `actor_tg_id` bigint DEFAULT NULL,
   `action` text,
   `payload` json DEFAULT NULL,
   `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
   PRIMARY KEY (`id`)
 ) ENGINE=InnoDB AUTO_INCREMENT=83 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci

CREATE TABLE `bot` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `tg_bot_id` bigint NOT NULL,
   `username` varchar(255) NOT NULL,

CREATE TABLE `chat_room` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `bot_id` bigint DEFAULT NULL,
   `title` varchar(255) DEFAULT NULL,
   `settings` json DEFAULT NULL,
   `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
   PRIMARY KEY (`id`),
   KEY `fk_chatroom_bot` (`bot_id`),
   CONSTRAINT `fk_chatroom_bot` FOREIGN KEY (`bot_id`) REFERENCES `bot` (`id`) ON DELETE CASCADE
 ) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci   `token_encrypted` text NOT NULL,
   `mode` varchar(50) DEFAULT 'single',
   `owners` json DEFAULT NULL,
   `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
   PRIMARY KEY (`id`),
   UNIQUE KEY `tg_bot_id` (`tg_bot_id`)
 ) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci

CREATE TABLE `group` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `room_id` bigint NOT NULL,
   `tg_group_id` bigint NOT NULL,
   `title` varchar(255) DEFAULT NULL,
   `group_aliases` json DEFAULT NULL,
   `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
   PRIMARY KEY (`id`),
   UNIQUE KEY `tg_group_id` (`tg_group_id`),
   KEY `fk_group_room` (`room_id`),
   CONSTRAINT `fk_group_room` FOREIGN KEY (`room_id`) REFERENCES `chat_room` (`id`)
 ) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci

CREATE TABLE `invite_link` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `room_id` bigint DEFAULT NULL,
   `code` varchar(255) NOT NULL,
   `expires_at` datetime NOT NULL,
   `used` tinyint(1) DEFAULT '0',
   `pseudonym` varchar(255) DEFAULT NULL,
   `tag` varchar(255) DEFAULT NULL,
   `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
   PRIMARY KEY (`id`),
   UNIQUE KEY `code` (`code`),
   KEY `fk_invite_room` (`room_id`),
   CONSTRAINT `fk_invite_room` FOREIGN KEY (`room_id`) REFERENCES `chat_room` (`id`) ON DELETE CASCADE
 ) ENGINE=InnoDB AUTO_INCREMENT=59 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci

CREATE TABLE `message` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `room_id` bigint DEFAULT NULL,
   `sender_participant_id` bigint DEFAULT NULL,
   `text` text,
   `content_type` varchar(50) DEFAULT 'text',
   `media_key` varchar(1024) DEFAULT NULL,
   `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
   `edited_at` datetime DEFAULT NULL,
   `deleted` tinyint(1) DEFAULT '0',
   PRIMARY KEY (`id`),
   KEY `fk_message_sender` (`sender_participant_id`),
   KEY `idx_message_room` (`room_id`),
   CONSTRAINT `fk_message_room` FOREIGN KEY (`room_id`) REFERENCES `chat_room` (`id`) ON DELETE CASCADE,
   CONSTRAINT `fk_message_sender` FOREIGN KEY (`sender_participant_id`) REFERENCES `participant` (`id`) ON DELETE SET NULL
 ) ENGINE=InnoDB AUTO_INCREMENT=211 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci

CREATE TABLE `message_copy` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `message_id` bigint DEFAULT NULL,
   `recipient_participant_id` bigint DEFAULT NULL,
   `recipient_tg_message_id` bigint DEFAULT NULL,
   `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
   `senders_tg_message_id` bigint DEFAULT NULL,
   PRIMARY KEY (`id`),
   KEY `fk_msgcopy_message` (`message_id`),
   KEY `fk_msgcopy_participant` (`recipient_participant_id`),
   CONSTRAINT `fk_msgcopy_message` FOREIGN KEY (`message_id`) REFERENCES `message` (`id`) ON DELETE CASCADE,
   CONSTRAINT `fk_msgcopy_participant` FOREIGN KEY (`recipient_participant_id`) REFERENCES `participant` (`id`) ON DELETE CASCADE
 ) ENGINE=InnoDB AUTO_INCREMENT=364 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci

CREATE TABLE `participant` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `room_id` bigint DEFAULT NULL,
   `tg_user_id` bigint NOT NULL,
   `pseudonym` varchar(255) NOT NULL,
   `tag` varchar(255) DEFAULT NULL,
   `joined_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
   `left_at` datetime DEFAULT NULL,
   `group_id` bigint DEFAULT NULL,
   PRIMARY KEY (`id`),
   KEY `idx_participant_room` (`room_id`),
   CONSTRAINT `fk_participant_room` FOREIGN KEY (`room_id`) REFERENCES `chat_room` (`id`) ON DELETE CASCADE
 ) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci