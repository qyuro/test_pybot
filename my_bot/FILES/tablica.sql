-- Таблица для хранения свободных слотов админа
CREATE TABLE admin_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    is_available BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для записи клиентов
CREATE TABLE appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL,
    client_id INTEGER NOT NULL,
    client_username TEXT,
    status TEXT DEFAULT 'pending', -- pending, approved, rejected, cancelled
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    responded_at DATETIME,
    FOREIGN KEY (slot_id) REFERENCES admin_slots(id)
);

-- Таблица для хранения ID админа
CREATE TABLE admin (
    id INTEGER PRIMARY KEY,
    admin_user_id INTEGER UNIQUE NOT NULL
);
