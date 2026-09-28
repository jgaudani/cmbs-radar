-- Integration tests drop and rebuild every ingest table, so they get their
-- own database. Runs only when the pgdata volume is first created.
CREATE DATABASE radar_test;
