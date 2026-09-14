-- V3__evidence_seq.sql — PostgreSQL：证据编号序列（E0001 风格，避免并发 count 冲突）
CREATE SEQUENCE IF NOT EXISTS evidence_seq START 100;
