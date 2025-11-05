-- Дополнительные индексы для производительности
CREATE INDEX IF NOT EXISTS idx_reminders_user_id_due_date ON reminders(user_id, due_date);
CREATE INDEX IF NOT EXISTS idx_finances_user_id_created_at ON finances(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_logs_user_id_created_at ON chat_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_user_id_created_at ON payments(user_id, created_at);