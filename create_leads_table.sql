-- Lead Management Table Migration
-- Run this in your PostgreSQL database

CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    upwork_job_link TEXT,
    client_name VARCHAR(255) NOT NULL,
    source VARCHAR(50) NOT NULL CHECK (source IN ('upwork', 'email', 'whatsapp', 'linkedin')),
    status VARCHAR(50) NOT NULL DEFAULT 'need_followup' CHECK (status IN ('need_followup', 'won', 'lost')),
    assigned_to VARCHAR(50) NOT NULL DEFAULT 'Saloni' CHECK (assigned_to IN ('Ashish', 'Saloni', 'Madhuri')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_followup_date TIMESTAMP,
    notes TEXT
);

-- Index for better performance
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_assigned_to ON leads(assigned_to);
CREATE INDEX IF NOT EXISTS idx_leads_last_followup ON leads(last_followup_date);

-- Update trigger for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_leads_updated_at BEFORE UPDATE ON leads
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();