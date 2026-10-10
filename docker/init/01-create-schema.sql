-- Runs only when the local PostgreSQL volume is initialized for the first time.
CREATE SCHEMA IF NOT EXISTS taskplanner AUTHORIZATION taskplanner;
REVOKE ALL ON SCHEMA taskplanner FROM PUBLIC;
