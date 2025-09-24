-- schema_mysql_anon.sql
-- Схема для MySQL (БД name = anon)

-- (1) створити БД окремо, див. інструкції нижче

CREATE TABLE IF NOT EXISTS admin_user (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  tg_user_id BIGINT UNIQUE NOT NULL,
  email VARCHAR(512),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bot (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  tg_bot_id BIGINT UNIQUE NOT NULL,
  username VARCHAR(255) NOT NULL,
  token_encrypted TEXT NOT NULL,
  mode VARCHAR(50) DEFAULT 'single',
  owners JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_room (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  bot_id BIGINT,
  title VARCHAR(255),
  settings JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_chatroom_bot FOREIGN KEY (bot_id) REFERENCES bot(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS invite_link (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  room_id BIGINT,
  code VARCHAR(255) UNIQUE NOT NULL,
  expires_at DATETIME NOT NULL,
  used BOOLEAN DEFAULT FALSE,
  pseudonym VARCHAR(255),
  tag VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_invite_room FOREIGN KEY (room_id) REFERENCES chat_room(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS participant (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  room_id BIGINT,
  tg_user_id BIGINT NOT NULL,
  pseudonym VARCHAR(255) NOT NULL,
  tag VARCHAR(255),
  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  left_at DATETIME,
  CONSTRAINT fk_participant_room FOREIGN KEY (room_id) REFERENCES chat_room(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS message (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  room_id BIGINT,
  sender_participant_id BIGINT,
  text TEXT,
  content_type VARCHAR(50) DEFAULT 'text',
  media_key VARCHAR(1024),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  edited_at DATETIME,
  deleted BOOLEAN DEFAULT FALSE,
  CONSTRAINT fk_message_room FOREIGN KEY (room_id) REFERENCES chat_room(id) ON DELETE CASCADE,
  CONSTRAINT fk_message_sender FOREIGN KEY (sender_participant_id) REFERENCES participant(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS message_copy (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  message_id BIGINT,
  recipient_participant_id BIGINT,
  recipient_tg_message_id BIGINT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_msgcopy_message FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE,
  CONSTRAINT fk_msgcopy_participant FOREIGN KEY (recipient_participant_id) REFERENCES participant(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  bot_id BIGINT,
  actor_tg_id BIGINT,
  action TEXT,
  payload JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes (MySQL-варіант)
CREATE INDEX idx_participant_room ON participant(room_id);
CREATE INDEX idx_message_room ON message(room_id);