CREATE TABLE accounts (  
    id SERIAL PRIMARY KEY,  
    name VARCHAR(100),  
    id_number VARCHAR(20) UNIQUE,  
    iban VARCHAR(34) UNIQUE,  
    balance DECIMAL(10, 2) DEFAULT 0.0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP  
);  
  
CREATE TABLE transactions (  
    id SERIAL PRIMARY KEY,  
    from_account VARCHAR(34),  
    to_account VARCHAR(34),  
    amount DECIMAL(10, 2),  
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP  
);  

