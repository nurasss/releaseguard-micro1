CREATE TABLE payment_methods (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id),
    provider VARCHAR(50) NOT NULL,
    token VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
