-- Runs once, when the Postgres volume is first created (the official image's
-- /docker-entrypoint-initdb.d hook). POSTGRES_DB creates `navbat`; this adds
-- the separate database pytest uses, so tests never touch development data.
CREATE DATABASE navbat_test OWNER navbat;
